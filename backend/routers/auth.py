import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from config.config import env
from config.database import get_db
from models.orm import Condominio, Morador, OtpChallenge, PerfilUsuario, RefreshToken, Usuario
from schemas.auth import AuthResponse, DemoLoginRequest, DemoLoginResponse, DemoUserResponse, MeResponse, OtpRequest, OtpVerify, RefreshRequest
from security import (
    client_ip,
    create_access_token,
    get_current_user,
    hash_secret,
    hash_token,
    otp_rate_limiter,
    as_utc,
    utcnow,
    verify_secret,
    demo_profile_name,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticação"])
me_router = APIRouter(prefix="/api/v1", tags=["Autenticação"])


@router.post("/login", response_model=DemoLoginResponse)
def demo_login(dados: DemoLoginRequest, db: Session = Depends(get_db)) -> DemoLoginResponse:
    if dados.codigo != "123456":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas.")
    user = db.scalar(select(Usuario).where(Usuario.telefone == dados.telefone).order_by(Usuario.id))
    if user is None:
        condominio = db.scalar(select(Condominio).order_by(Condominio.id))
        if condominio is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Serviço indisponível.")
        user = Usuario(
            condominio_id=condominio.id,
            telefone=dados.telefone,
            nome=demo_profile_name(dados.perfil),
            perfil=dados.perfil,
        )
        db.add(user)
    else:
        user.perfil = dados.perfil
        user.nome = demo_profile_name(dados.perfil)
        user.ativo = True
    db.commit()
    db.refresh(user)
    return DemoLoginResponse(
        access_token=create_access_token(user),
        usuario=DemoUserResponse(telefone=user.telefone, nome=user.nome, perfil=user.perfil),
    )


def _issue_tokens(user: Usuario, db: Session) -> AuthResponse:
    raw_refresh = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            usuario_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=utcnow() + timedelta(days=env["REFRESH_TOKEN_DAYS"]),
        )
    )
    db.commit()
    return AuthResponse(
        access_token=create_access_token(user),
        refresh_token=raw_refresh,
        expires_in=env["ACCESS_TOKEN_MINUTES"] * 60,
    )


@router.post("/request-otp")
def request_otp(dados: OtpRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    ip = client_ip(request)
    if not otp_rate_limiter.allow(f"phone:{dados.telefone}", env["OTP_RATE_LIMIT"], env["OTP_RATE_WINDOW_SECONDS"]):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Tente novamente mais tarde.")
    if not otp_rate_limiter.allow(f"ip:{ip}", env["OTP_RATE_LIMIT"] * 2, env["OTP_RATE_WINDOW_SECONDS"]):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Tente novamente mais tarde.")

    user = db.scalar(
        select(Usuario).where(
            Usuario.condominio_id == dados.condominio_id,
            Usuario.telefone == dados.telefone,
            Usuario.ativo.is_(True),
        )
    )
    response = {"detail": "Se o telefone estiver cadastrado, um código será enviado."}
    if user is None:
        return response

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute(
        update(OtpChallenge)
        .where(OtpChallenge.telefone == dados.telefone, OtpChallenge.used_at.is_(None))
        .values(used_at=utcnow())
    )
    db.add(
        OtpChallenge(
            telefone=dados.telefone,
            code_hash=hash_secret(code),
            expires_at=utcnow() + timedelta(minutes=env["OTP_EXPIRY_MINUTES"]),
            max_attempts=env["OTP_MAX_ATTEMPTS"],
            requested_ip=ip,
        )
    )
    db.commit()
    if env["APP_ENV"] != "production" and env["MOCK_OTP"]:
        response["codigo_mock"] = code
    return response


@router.post("/verify-otp", response_model=AuthResponse)
def verify_otp(dados: OtpVerify, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(Usuario).where(Usuario.condominio_id == dados.condominio_id, Usuario.telefone == dados.telefone, Usuario.ativo.is_(True)))
    challenge = db.scalar(select(OtpChallenge).where(OtpChallenge.telefone == dados.telefone).order_by(desc(OtpChallenge.id)))
    generic_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Código inválido ou expirado.")
    if user is None or challenge is None or challenge.used_at is not None or as_utc(challenge.expires_at) <= utcnow() or challenge.attempts >= challenge.max_attempts:
        raise generic_error
    challenge.attempts += 1
    if not verify_secret(dados.codigo, challenge.code_hash):
        db.commit()
        raise generic_error
    challenge.used_at = utcnow()
    response = _issue_tokens(user, db)
    return response


@router.post("/refresh", response_model=AuthResponse)
def refresh(dados: RefreshRequest, db: Session = Depends(get_db)) -> AuthResponse:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(dados.refresh_token)))
    if token is None or token.revoked_at is not None or as_utc(token.expires_at) <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.")
    user = db.get(Usuario, token.usuario_id)
    if user is None or not user.ativo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.")
    token.revoked_at = utcnow()
    return _issue_tokens(user, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(dados: RefreshRequest, db: Session = Depends(get_db), _user: Usuario = Depends(get_current_user)) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(dados.refresh_token)))
    if token is not None and token.revoked_at is None:
        token.revoked_at = utcnow()
        db.commit()


@me_router.get("/me", response_model=MeResponse)
def me(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)) -> MeResponse:
    morador = db.scalar(select(Morador).where(Morador.usuario_id == user.id))
    return MeResponse(
        id=user.id,
        condominio_id=user.condominio_id,
        nome=user.nome,
        telefone=user.telefone,
        perfil=user.perfil,
        ativo=user.ativo,
        unidade_id=morador.unidade_id if morador else None,
        created_at=user.created_at,
    )