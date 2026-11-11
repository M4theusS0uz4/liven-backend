"""Cadastro e sessões globais isolados de Usuario e dos dados de condomínio."""
import logging
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.config import env
from config.database import get_db
from models.orm import ContaGlobal, LimiteLogin, OtpCadastro, OtpDefinicaoSenha, OtpLoginGlobal, SessaoGlobal, Usuario
from schemas.auth import OtpRequestResponse
from schemas.registration import ContaGlobalRead, GlobalAuthResponse
from security import as_utc, bearer_scheme, client_ip, get_current_user, hash_secret, hash_token, load_global_state, otp_rate_limiter, utcnow, verify_secret
from services.otp_delivery import OtpDeliveryError, get_otp_delivery
from services.email_identity import normalize_email
from services.passwords import DUMMY_PASSWORD_HASH, hash_password, verify_password
from services.memberships import authorized_users, membership_read, user_read, valid_membership

logger = logging.getLogger(__name__)
GENERIC_RESPONSE = "Se a solicitação puder ser atendida, um código será enviado."
PURPOSES = {"cadastro": OtpCadastro, "login_global": OtpLoginGlobal, "definicao_senha": OtpDefinicaoSenha}


def require_legacy_otp():
    if not env["LEGACY_OTP_LOGIN_ENABLED"]:
        raise HTTPException(410, "Use login por e-mail e senha. Contas antigas devem definir uma senha com verificação de e-mail.")


def get_session_identity(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(credentials.credentials, env["JWT_SECRET"], algorithms=["HS256"]) if credentials else {}
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Sessão inválida ou expirada.") from None
    if str(payload.get("sub", "")).startswith("global:"):
        return get_current_global_account(credentials, db)
    return get_current_user(request, credentials, db)


def issue_global_tokens(account: ContaGlobal, db: Session, selected_user: Usuario | None = None, auto_select: bool = True) -> GlobalAuthResponse:
    if not account.ativo or account.email_verificado_em is None:
        raise HTTPException(401, "Conta indisponível.")
    now = utcnow()
    users = authorized_users(account, db)
    if auto_select and len(users) == 1:
        selected_user = users[0]
    if selected_user is not None and not any(user.id == selected_user.id for user in users):
        raise HTTPException(403, "Vínculo indisponível.")
    scope = "condominio" if selected_user is not None else "global"
    refresh = secrets.token_urlsafe(48)
    session = SessaoGlobal(conta_id=account.id, usuario_id=selected_user.id if selected_user else None, token_hash=hash_token(refresh),
                           expires_at=now + timedelta(days=env["REFRESH_TOKEN_DAYS"]))
    db.add(session)
    db.flush()
    claims = {
        "sub": f"global:{account.id}", "scope": scope, "token_type": "access",
        "iat": now, "exp": now + timedelta(minutes=env["ACCESS_TOKEN_MINUTES"]),
        "jti": secrets.token_urlsafe(16),
        "sid": session.id,
    }
    if selected_user is not None:
        claims.update(usuario_id=selected_user.id, condominio_id=selected_user.condominio_id, perfil=selected_user.perfil)
    access = jwt.encode(claims, env["JWT_SECRET"], algorithm="HS256")
    return GlobalAuthResponse(access_token=access, refresh_token=refresh,
                              expires_in=env["ACCESS_TOKEN_MINUTES"] * 60,
                              conta=ContaGlobalRead.model_validate(account), scope=scope,
                              usuario=user_read(selected_user) if selected_user else None,
                              vinculos=[membership_read(user) for user in users])


def get_current_global_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ContaGlobal:
    error = HTTPException(401, "Sessão global inválida ou expirada.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise error
    try:
        payload = jwt.decode(credentials.credentials, env["JWT_SECRET"], algorithms=["HS256"],
                             options={"require": ["sub", "exp", "iat", "scope", "token_type", "sid"]})
        account, _session = load_global_state(payload, db)
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise error from None
    return account


def request_global_otp(email: str, purpose: str, request: Request, db: Session, password: str | None = None, resend: bool = False) -> OtpRequestResponse:
    email = normalize_email(email)
    if purpose == "login_global":
        require_legacy_otp()
    model = PURPOSES[purpose]
    # Propósito faz parte das chaves; o cadastro não esgota o limite do login atual.
    window = env["OTP_RATE_WINDOW_SECONDS"]
    if not otp_rate_limiter.allow(f"{purpose}:email:{hash_token(email)}", env["OTP_RATE_LIMIT"], window):
        logger.info("otp_request purpose=%s outcome=blocked reason=email_rate_limit", purpose)
        raise HTTPException(429, "Tente novamente mais tarde.")
    if not otp_rate_limiter.allow(f"{purpose}:ip:{client_ip(request)}", env["OTP_RATE_LIMIT"] * 2, window):
        logger.info("otp_request purpose=%s outcome=blocked reason=ip_rate_limit", purpose)
        raise HTTPException(429, "Tente novamente mais tarde.")
    delivery = get_otp_delivery()
    response = OtpRequestResponse(detail=GENERIC_RESPONSE)
    try:
        now = utcnow()
        # ON CONFLICT também serializa a primeira solicitação de um e-mail ainda desconhecido.
        db.execute(insert(model).values(email=email, attempts=0, requests=0,
                                       max_attempts=env["OTP_MAX_ATTEMPTS"], window_started_at=now)
                   .on_conflict_do_nothing(index_elements=["email"]))
        challenge = db.scalar(select(model).where(model.email == email).with_for_update())
        if (now - as_utc(challenge.window_started_at)).total_seconds() >= window:
            challenge.window_started_at = now
            challenge.requests = 0
        cooldown = challenge.last_requested_at is not None and (now - as_utc(challenge.last_requested_at)).total_seconds() < env["OTP_RESEND_SECONDS"]
        if cooldown or challenge.requests >= env["OTP_RATE_LIMIT"]:
            logger.info("otp_request purpose=%s outcome=skipped reason=%s", purpose,
                        "cooldown" if cooldown else "persistent_rate_limit")
            db.commit()
            return response
        challenge.requests += 1
        challenge.last_requested_at = now
        # A consulta ocorre sob o mesmo lock usado pela confirmação do cadastro.
        account = db.scalar(select(ContaGlobal).where(ContaGlobal.email == email))
        if purpose == "cadastro" and account is not None:
            # Inclusive contas inativas: nunca emitir código para recriar ou reativar.
            db.commit()
            logger.info("otp_request purpose=cadastro outcome=skipped reason=existing_account")
            return response
        if purpose == "login_global" and (account is None or not account.ativo or account.email_verificado_em is None):
            db.commit()
            logger.info("otp_request purpose=login_global outcome=skipped reason=ineligible_account")
            return response
        if purpose == "login_global" and account.password_hash is not None:
            db.commit()
            logger.info("otp_request purpose=login_global outcome=skipped reason=password_login_required")
            return response
        if purpose == "definicao_senha" and (account is None or not account.ativo or account.email_verificado_em is None or account.password_hash is not None):
            db.commit()
            logger.info("otp_request purpose=definicao_senha outcome=skipped reason=ineligible_account")
            return response
        if resend and (challenge.password_hash is None or challenge.used_at is not None):
            db.commit()
            logger.info("otp_request purpose=%s outcome=skipped reason=no_pending_password", purpose)
            return response
        if purpose in ("cadastro", "definicao_senha") and password is None and not resend:
            raise HTTPException(422, "Os dados enviados são inválidos.")
        pending_password = challenge.password_hash if resend else (hash_password(password) if password is not None else None)
        code = f"{secrets.randbelow(1_000_000):06d}"
        encoded = hash_secret(f"{purpose}:{code}")
        try:
            logger.info("otp_request purpose=%s outcome=delivery_started provider=%s", purpose, type(delivery).__name__)
            mock = delivery.deliver(email=email, codigo=code)
        except OtpDeliveryError:
            # Preserva OTP anterior e registra cooldown/contagem mesmo com falha de entrega.
            db.commit()
            logger.warning("otp_request purpose=%s outcome=delivery_failed provider=%s", purpose, type(delivery).__name__)
            return response
        challenge.code_hash = encoded
        challenge.expires_at = now + timedelta(minutes=env["OTP_EXPIRY_MINUTES"])
        challenge.attempts = 0
        challenge.max_attempts = env["OTP_MAX_ATTEMPTS"]
        challenge.used_at = None
        if purpose in ("cadastro", "definicao_senha"):
            challenge.password_hash = pending_password
        db.commit()
        logger.info("otp_request purpose=%s outcome=challenge_committed provider=%s", purpose, type(delivery).__name__)
        if env["APP_ENV"] == "development" and env["MOCK_OTP"]:
            response.codigo_mock = mock
        return response
    except Exception:
        db.rollback()
        raise


def verify_global_otp(email: str, code: str, purpose: str, db: Session, password: str | None = None) -> GlobalAuthResponse:
    email = normalize_email(email)
    if purpose == "login_global":
        require_legacy_otp()
    model = PURPOSES[purpose]
    error = HTTPException(401, "Código inválido ou expirado.")
    try:
        challenge = db.scalar(select(model).where(model.email == email).with_for_update())
        if challenge is None or challenge.code_hash is None or challenge.expires_at is None or challenge.used_at is not None or as_utc(challenge.expires_at) <= utcnow() or challenge.attempts >= challenge.max_attempts:
            raise error
        challenge.attempts += 1
        if not verify_secret(f"{purpose}:{code}", challenge.code_hash):
            db.commit()
            raise error
        if purpose in ("cadastro", "definicao_senha") and (password is None or challenge.password_hash is None or not verify_password(password, challenge.password_hash)):
            db.commit()
            raise error
        account = db.scalar(select(ContaGlobal).where(ContaGlobal.email == email).with_for_update())
        challenge.used_at = utcnow()
        if purpose == "cadastro":
            if account is not None:
                # Nunca reativa, substitui ou autentica conta existente pela rota de cadastro.
                db.commit()
                raise error
            account = ContaGlobal(email=email, ativo=True, email_verificado_em=utcnow(), password_hash=challenge.password_hash)
            db.add(account)
            db.flush()
        elif purpose == "definicao_senha":
            if account is None or not account.ativo or account.email_verificado_em is None or account.password_hash is not None:
                db.commit()
                raise error
            account.password_hash = challenge.password_hash
            # Nenhuma sessão anterior continua válida após definir a senha inicial.
            from sqlalchemy import update
            db.execute(update(SessaoGlobal).where(SessaoGlobal.conta_id == account.id, SessaoGlobal.revoked_at.is_(None)).values(revoked_at=utcnow()))
        elif account is None or not account.ativo or account.email_verificado_em is None:
            db.commit()
            raise error
        elif account.password_hash is not None:
            db.commit()
            raise error
        if purpose in ("cadastro", "definicao_senha"):
            challenge.password_hash = None
        response = issue_global_tokens(account, db)
        db.commit()
        return response
    except IntegrityError as exc:
        db.rollback()
        # A constraint é a defesa final se outro escritor inserir sem o lock OTP.
        # Não mascarar violações de integridade sem relação com duplicidade de conta.
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if purpose == "cadastro" and constraint == "uq_contas_globais_email":
            raise error from None
        raise
    except Exception:
        db.rollback()
        raise


def refresh_global_session(raw_token: str, db: Session) -> GlobalAuthResponse:
    try:
        token = db.scalar(select(SessaoGlobal).where(SessaoGlobal.token_hash == hash_token(raw_token)))
        if token is None:
            raise HTTPException(401, "Sessão global inválida ou expirada.")
        # Mesmo ordenamento de setup/login: conta antes da sessão, evitando deadlocks.
        account = db.scalar(select(ContaGlobal).where(ContaGlobal.id == token.conta_id).with_for_update())
        token = db.scalar(select(SessaoGlobal).where(SessaoGlobal.id == token.id).with_for_update().execution_options(populate_existing=True))
        if token is None or token.revoked_at is not None or as_utc(token.expires_at) <= utcnow():
            raise HTTPException(401, "Sessão global inválida ou expirada.")
        if account is None or not account.ativo or account.email_verificado_em is None:
            raise HTTPException(401, "Sessão global inválida ou expirada.")
        token.revoked_at = utcnow()
        user = db.get(Usuario, token.usuario_id) if token.usuario_id is not None else None
        if not valid_membership(user, account.email):
            user = None
        result = issue_global_tokens(account, db, selected_user=user, auto_select=False)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def password_login(email: str, password: str, request: Request, db: Session) -> GlobalAuthResponse:
    email = normalize_email(email)
    try:
        now = utcnow()
        blocked = False
        # Contadores persistidos e locks ordenados: funcionam entre workers.
        for key, limit in sorted((("email:" + hash_token(email), env["LOGIN_RATE_LIMIT"]),
                                  ("ip:" + hash_token(client_ip(request)), env["LOGIN_IP_RATE_LIMIT"]))):
            db.execute(insert(LimiteLogin).values(key=key, attempts=0, window_started_at=now).on_conflict_do_nothing(index_elements=["key"]))
            counter = db.scalar(select(LimiteLogin).where(LimiteLogin.key == key).with_for_update())
            if (now - as_utc(counter.window_started_at)).total_seconds() >= env["LOGIN_RATE_WINDOW_SECONDS"]:
                counter.window_started_at, counter.attempts = now, 0
            blocked = blocked or counter.attempts >= limit
            counter.attempts = min(counter.attempts + 1, limit)
        db.commit()
        if blocked:
            raise HTTPException(429, "Tente novamente mais tarde.")
        account = db.scalar(select(ContaGlobal).where(ContaGlobal.email == email).with_for_update())
        eligible = account is not None and account.ativo and account.email_verificado_em is not None and account.password_hash is not None
        valid = verify_password(password, account.password_hash if eligible else DUMMY_PASSWORD_HASH)
        if not eligible or not valid:
            raise HTTPException(401, "E-mail ou senha inválidos.")
        response = issue_global_tokens(account, db)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def select_membership(account: ContaGlobal, access_token: str, user_id: int, db: Session) -> GlobalAuthResponse:
    try:
        payload = jwt.decode(access_token, env["JWT_SECRET"], algorithms=["HS256"])
        account = db.scalar(select(ContaGlobal).where(ContaGlobal.id == account.id).with_for_update())
        if account is None or not account.ativo or account.email_verificado_em is None:
            raise HTTPException(401, "Sessão inválida ou expirada.")
        session = db.scalar(select(SessaoGlobal).where(SessaoGlobal.id == payload["sid"]).with_for_update().execution_options(populate_existing=True))
        if session is None or session.conta_id != account.id or session.revoked_at is not None or as_utc(session.expires_at) <= utcnow():
            raise HTTPException(401, "Sessão inválida ou expirada.")
        user = next((user for user in authorized_users(account, db) if user.id == user_id), None)
        if user is None:
            raise HTTPException(403, "Vínculo indisponível.")
        response = issue_global_tokens(account, db, selected_user=user, auto_select=False)
        session.revoked_at = utcnow()
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
