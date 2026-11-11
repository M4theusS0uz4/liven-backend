import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from config.config import env
from config.database import get_db
from models.orm import ContaGlobal, Condominio, Morador, OtpChallenge, RefreshToken, SessaoGlobal, Usuario
from schemas.auth import AuthResponse, MeResponse, OtpRequest, OtpRequestResponse, OtpVerify, RefreshRequest
from security import as_utc, client_ip, create_access_token, get_current_user, hash_secret, hash_token, otp_rate_limiter, utcnow, verify_secret
from services.otp_delivery import OtpDeliveryError, get_otp_delivery
from services.global_auth import get_session_identity, password_login, refresh_global_session, require_legacy_otp
from schemas.registration import GlobalAuthResponse, PasswordLoginRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticação"])
me_router = APIRouter(prefix="/api/v1", tags=["Autenticação"])


@router.post("/login", response_model=GlobalAuthResponse)
def login(data: PasswordLoginRequest, request: Request, db: Session = Depends(get_db)):
    return password_login(str(data.email), data.senha.get_secret_value(), request, db)


def _locked_user(dados: OtpRequest, db: Session) -> Usuario | None:
    # Todas as solicitações e verificações do mesmo usuário tomam esta trava primeiro.
    # O lock é mantido até commit/rollback e funciona entre processos do backend.
    return db.scalar(
        select(Usuario)
        .where(
            Usuario.condominio_id == dados.condominio_id,
            Usuario.email == str(dados.email),
            Usuario.ativo.is_(True),
            Usuario.condominio.has(Condominio.ativo.is_(True)),
        )
        .with_for_update()
    )


def _issue_tokens(user: Usuario, db: Session) -> AuthResponse:
    # O chamador confirma consumo/revogação e novo refresh em uma única transação.
    raw_refresh = secrets.token_urlsafe(48)
    session = RefreshToken(usuario_id=user.id, token_hash=hash_token(raw_refresh),
                           expires_at=utcnow() + timedelta(days=env["REFRESH_TOKEN_DAYS"]))
    db.add(session)
    db.flush()
    response = AuthResponse(
        access_token=create_access_token(user, session.id),
        refresh_token=raw_refresh,
        expires_in=env["ACCESS_TOKEN_MINUTES"] * 60,
    )
    return response


@router.post("/request-otp", response_model=OtpRequestResponse, response_model_exclude_none=True, deprecated=True)
def request_otp(dados: OtpRequest, request: Request, db: Session = Depends(get_db)) -> OtpRequestResponse:
    require_legacy_otp()
    ip = client_ip(request)
    if not otp_rate_limiter.allow(f"email:{dados.condominio_id}:{dados.email}", env["OTP_RATE_LIMIT"], env["OTP_RATE_WINDOW_SECONDS"]):
        raise HTTPException(429, "Tente novamente mais tarde.")
    if not otp_rate_limiter.allow(f"ip:{ip}", env["OTP_RATE_LIMIT"] * 2, env["OTP_RATE_WINDOW_SECONDS"]):
        raise HTTPException(429, "Tente novamente mais tarde.")
    delivery = get_otp_delivery()
    response = OtpRequestResponse(detail="Se o e-mail estiver cadastrado, um código será enviado.")
    try:
        user = _locked_user(dados, db)
        if user is None:
            db.rollback()
            return response
        now = utcnow()
        # Limite persistido também protege reenvios entre workers/reinicializações.
        recent = db.scalar(select(func.count(OtpChallenge.id)).where(
            OtpChallenge.usuario_id == user.id,
            OtpChallenge.created_at >= now - timedelta(seconds=env["OTP_RATE_WINDOW_SECONDS"]),
        ))
        latest = db.scalar(select(OtpChallenge).where(OtpChallenge.usuario_id == user.id).order_by(desc(OtpChallenge.id)))
        if recent >= env["OTP_RATE_LIMIT"] or (latest and (now - as_utc(latest.created_at)).total_seconds() < env["OTP_RESEND_SECONDS"]):
            # Não distingue conta existente de inexistente pela resposta de cooldown.
            db.rollback()
            return response
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.execute(update(OtpChallenge).where(
            OtpChallenge.usuario_id == user.id, OtpChallenge.used_at.is_(None),
        ).values(used_at=now))
        db.add(OtpChallenge(
            usuario_id=user.id,
            email=str(dados.email),
            code_hash=hash_secret(code),
            expires_at=now + timedelta(minutes=env["OTP_EXPIRY_MINUTES"]),
            max_attempts=env["OTP_MAX_ATTEMPTS"],
            requested_ip=ip,
            created_at=now,
        ))
        db.flush()
        # Envio síncrono antes do commit: falha mantém o desafio anterior utilizável.
        # Não existe transação distribuída entre o provedor HTTP e o PostgreSQL.
        mock_code = delivery.deliver(email=str(dados.email), codigo=code)
        db.commit()
    except OtpDeliveryError:
        db.rollback()
        logger.warning("Entrega OTP indisponível; solicitação não confirmada.")
        return response
    except Exception:
        db.rollback()
        raise
    if env["APP_ENV"] == "development" and env["MOCK_OTP"]:
        response.codigo_mock = mock_code
    return response


@router.post("/verify-otp", response_model=AuthResponse, deprecated=True)
def verify_otp(dados: OtpVerify, db: Session = Depends(get_db)) -> AuthResponse:
    require_legacy_otp()
    error = HTTPException(401, "Código inválido ou expirado.")
    try:
        user = _locked_user(dados, db)
        if user is None:
            raise error
        challenge = db.scalar(select(OtpChallenge).where(
            OtpChallenge.usuario_id == user.id,
            OtpChallenge.email == str(dados.email),
        ).order_by(desc(OtpChallenge.id)).with_for_update())
        if challenge is None or challenge.used_at is not None or as_utc(challenge.expires_at) <= utcnow() or challenge.attempts >= challenge.max_attempts:
            raise error
        challenge.attempts += 1
        if not verify_secret(dados.codigo, challenge.code_hash):
            db.commit()  # A tentativa incorreta precisa sobreviver ao HTTP 401.
            raise error
        challenge.used_at = utcnow()
        response = _issue_tokens(user, db)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


@router.post("/refresh", response_model=GlobalAuthResponse | AuthResponse)
def refresh(dados: RefreshRequest, db: Session = Depends(get_db)):
    try:
        if db.scalar(select(SessaoGlobal.id).where(SessaoGlobal.token_hash == hash_token(dados.refresh_token))) is not None:
            return refresh_global_session(dados.refresh_token, db)
        token = db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(dados.refresh_token),
        ).with_for_update())
        if token is None or token.revoked_at is not None or as_utc(token.expires_at) <= utcnow():
            raise HTTPException(401, "Sessão inválida ou expirada.")
        user = db.get(Usuario, token.usuario_id)
        if user is None or not user.ativo or not user.condominio.ativo:
            raise HTTPException(401, "Sessão inválida ou expirada.")
        token.revoked_at = utcnow()
        response = _issue_tokens(user, db)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(dados: RefreshRequest, db: Session = Depends(get_db), user=Depends(get_session_identity)) -> None:
    try:
        model = SessaoGlobal if isinstance(user, ContaGlobal) else RefreshToken
        owner = model.conta_id if isinstance(user, ContaGlobal) else model.usuario_id
        token = db.scalar(select(model).where(
            model.token_hash == hash_token(dados.refresh_token),
            owner == user.id,
        ).with_for_update())
        if token is not None and token.revoked_at is None:
            token.revoked_at = utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise


@me_router.get("/me", response_model=MeResponse)
def me(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)) -> MeResponse:
    morador = db.scalar(select(Morador).where(Morador.usuario_id == user.id))
    return MeResponse(
        id=user.id,
        condominio_id=user.condominio_id,
        nome=user.nome,
        telefone=user.telefone,
        email=user.email,
        perfil=user.perfil,
        ativo=user.ativo,
        unidade_id=morador.unidade_id if morador else None,
        created_at=user.created_at,
    )
