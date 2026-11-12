"""Cadastro e sessões globais isolados de Usuario e dos dados de condomínio."""
import logging
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.config import env
from config.database import get_db
from models.orm import ContaGlobal, LimiteLogin, OtpCadastro, OtpDefinicaoSenha, OtpLoginGlobal, SessaoGlobal, Usuario
from schemas.auth import OtpRequestResponse
from schemas.registration import ContaGlobalRead, GlobalAuthResponse
from security import as_utc, bearer_scheme, client_ip, get_current_user, hash_secret, hash_token, load_global_state, otp_rate_limiter, utcnow, verify_secret
from services.otp_delivery import OtpDelivery, OtpDeliveryError, OtpDeliveryIndeterminate, get_otp_delivery
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


@contextmanager
def _serialized_otp_session(db: Session, email: str, purpose: str) -> Iterator[Session]:
    """Pin a connection: a session advisory lock survives the pre-send commit.

    Every requester for this purpose/email uses this lock. Verification still
    takes the row lock, which we reacquire before contacting the transport.
    No new table, migration, background worker or plaintext OTP is needed.
    """
    key = int(hash_token(f"otp:{purpose}:{email}")[:16], 16)
    if key >= 2**63:
        key -= 2**64
    with db.get_bind().connect() as connection:
        try:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
            connection.commit()
            with Session(bind=connection, expire_on_commit=False) as locked_db:
                yield locked_db
        finally:
            try:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()
            except Exception as exc:
                # Never return a connection with an advisory lock to the pool.
                if not connection.closed:
                    connection.invalidate()
                logger.error("otp_request outcome=lock_cleanup_failed error=%s", type(exc).__name__)


def _reserve_otp_attempt(db: Session, email: str, purpose: str, request: Request) -> None:
    """Reuse the existing counter table, with keys isolated from password login.

    Failed transports refund send quotas, never this bounded retry budget.
    Persisting it prevents workers/restarts from bypassing outage protection.
    """
    now = utcnow()
    budgets = [("otp_attempt:" + hash_token(f"{purpose}:email:{email}"), env["OTP_RATE_LIMIT"] * 2),
               ("otp_attempt:" + hash_token(f"{purpose}:ip:{client_ip(request)}"), env["OTP_RATE_LIMIT"] * 4)]
    blocked = False
    for key, limit in sorted(budgets):
        db.execute(insert(LimiteLogin).values(key=key, attempts=0, window_started_at=now)
                   .on_conflict_do_nothing(index_elements=["key"]))
        counter = db.scalar(select(LimiteLogin).where(LimiteLogin.key == key).with_for_update())
        if (now - as_utc(counter.window_started_at)).total_seconds() >= env["OTP_RATE_WINDOW_SECONDS"]:
            counter.window_started_at, counter.attempts = now, 0
        blocked = blocked or counter.attempts >= limit
        counter.attempts = min(counter.attempts + 1, limit)
    db.commit()
    if blocked:
        logger.info("otp_request purpose=%s outcome=blocked reason=persistent_attempt_limit", purpose)
        raise HTTPException(429, "Tente novamente mais tarde.")


def request_global_otp(email: str, purpose: str, request: Request, db: Session, password: str | None = None, resend: bool = False) -> OtpRequestResponse:
    email = normalize_email(email)
    if purpose == "login_global":
        require_legacy_otp()
    window = env["OTP_RATE_WINDOW_SECONDS"]
    # The original send limits are refundable only after proven rejection.
    # A separate bounded attempt budget prevents unlimited failed SMTP retries.
    for key, limit in ((f"{purpose}:attempt_email:{hash_token(email)}", env["OTP_RATE_LIMIT"] * 2),
                       (f"{purpose}:attempt_ip:{client_ip(request)}", env["OTP_RATE_LIMIT"] * 4)):
        if not otp_rate_limiter.allow(key, limit, window):
            logger.info("otp_request purpose=%s outcome=blocked reason=transport_attempt_limit", purpose)
            raise HTTPException(429, "Tente novamente mais tarde.")
    reservations = []
    for key, limit, reason in ((f"{purpose}:email:{hash_token(email)}", env["OTP_RATE_LIMIT"], "email_rate_limit"),
                               (f"{purpose}:ip:{client_ip(request)}", env["OTP_RATE_LIMIT"] * 2, "ip_rate_limit")):
        reservation = otp_rate_limiter.reserve(key, limit, window)
        if reservation is None:
            for previous_key, previous_reservation in reservations:
                otp_rate_limiter.refund(previous_key, previous_reservation)
            logger.info("otp_request purpose=%s outcome=blocked reason=%s", purpose, reason)
            raise HTTPException(429, "Tente novamente mais tarde.")
        reservations.append((key, reservation))

    def refund_send_budget() -> None:
        for key, reservation in reservations:
            otp_rate_limiter.refund(key, reservation)

    delivery = get_otp_delivery()
    request_id = secrets.token_hex(8)
    with _serialized_otp_session(db, email, purpose) as locked_db:
        _reserve_otp_attempt(locked_db, email, purpose, request)
        return _deliver_global_otp(email, purpose, password, resend, delivery, request_id, locked_db, refund_send_budget)


def _deliver_global_otp(
    email: str, purpose: str, password: str | None, resend: bool,
    delivery: OtpDelivery, request_id: str, db: Session,
    refund_send_budget: Callable[[], None],
) -> OtpRequestResponse:
    model = PURPOSES[purpose]
    response = OtpRequestResponse(detail=GENERIC_RESPONSE)
    provider = type(delivery).__name__

    def log(outcome: str, reason: str = "none", level: int = logging.INFO) -> None:
        logger.log(level, "otp_request purpose=%s outcome=%s reason=%s provider=%s request_id=%s",
                   purpose, outcome, reason, provider, request_id)

    prepared = False
    try:
        now = utcnow()
        db.execute(insert(model).values(email=email, attempts=0, requests=0,
                                       max_attempts=env["OTP_MAX_ATTEMPTS"], window_started_at=now)
                   .on_conflict_do_nothing(index_elements=["email"]))
        challenge = db.scalar(select(model).where(model.email == email).with_for_update())
        if (now - as_utc(challenge.window_started_at)).total_seconds() >= env["OTP_RATE_WINDOW_SECONDS"]:
            challenge.window_started_at = now
            challenge.requests = 0
        cooldown = challenge.last_requested_at is not None and (now - as_utc(challenge.last_requested_at)).total_seconds() < env["OTP_RESEND_SECONDS"]
        if cooldown or challenge.requests >= env["OTP_RATE_LIMIT"]:
            db.commit()
            log("skipped", "cooldown" if cooldown else "persistent_rate_limit")
            return response
        account = db.scalar(select(ContaGlobal).where(ContaGlobal.email == email))
        reason = None
        if purpose == "cadastro" and account is not None:
            reason = "existing_account"
        elif purpose == "login_global" and (account is None or not account.ativo or account.email_verificado_em is None):
            reason = "ineligible_account"
        elif purpose == "login_global" and account.password_hash is not None:
            reason = "password_login_required"
        elif purpose == "definicao_senha" and (account is None or not account.ativo or account.email_verificado_em is None or account.password_hash is not None):
            reason = "ineligible_account"
        elif resend and (challenge.password_hash is None or challenge.used_at is not None):
            reason = "no_pending_password"
        if reason:
            db.commit()
            log("skipped", reason)
            return response
        if purpose in ("cadastro", "definicao_senha") and password is None and not resend:
            raise HTTPException(422, "Os dados enviados são inválidos.")

        fields = ("code_hash", "expires_at", "attempts", "max_attempts", "used_at",
                  "requests", "window_started_at", "last_requested_at")
        previous = {name: getattr(challenge, name) for name in fields}
        previous_password = getattr(challenge, "password_hash", None)
        if purpose in ("cadastro", "definicao_senha"):
            # Resend never accepts a password. Repeating the same request also
            # preserves the original salted hash, including after a first failure.
            if resend or (previous_password and verify_password(password, previous_password)):
                pending_password = previous_password
            else:
                pending_password = hash_password(password)
            challenge.password_hash = pending_password
        code = f"{secrets.randbelow(1_000_000):06d}"
        encoded = hash_secret(f"{purpose}:{code}")
        challenge.code_hash = encoded
        challenge.expires_at = now + timedelta(minutes=env["OTP_EXPIRY_MINUTES"])
        challenge.attempts = 0
        challenge.max_attempts = env["OTP_MAX_ATTEMPTS"]
        challenge.used_at = None
        challenge.requests += 1
        challenge.last_requested_at = now
        # Durable before SMTP: a later database outage cannot invalidate a code
        # already accepted by the provider. Reserve quota for ambiguous results.
        db.commit()
        prepared = True
        log("challenge_prepared")
        challenge = db.scalar(select(model).where(model.email == email).with_for_update().execution_options(populate_existing=True))
        if challenge.code_hash != encoded or challenge.used_at is not None:
            db.rollback()
            log("skipped", "challenge_changed")
            return response
        log("delivery_started")
        try:
            mock = delivery.deliver(email=email, codigo=code)
        except OtpDeliveryIndeterminate:
            # DATA may have been accepted before the connection disappeared.
            # Keep the durable OTP and quota; never claim delivery or rejection.
            db.rollback()
            log("delivery_indeterminate", "transport_result_unknown", logging.WARNING)
            return response
        except OtpDeliveryError:
            # A proven rejection restores the previous OTP/attempt budget and
            # successful-send cooldown. A first failure retains its password.
            for name, value in previous.items():
                setattr(challenge, name, value)
            if purpose in ("cadastro", "definicao_senha"):
                challenge.password_hash = previous_password or pending_password
            try:
                db.commit()
            except Exception:
                db.rollback()
                log("recovery_failed", "database_error", logging.ERROR)
                raise
            refund_send_budget()
            log("delivery_failed", "transport_rejected", logging.WARNING)
            return response
        # Read-only transaction: no required persistence remains after acceptance.
        # Even loss of the DB connection here cannot undo the prepared challenge.
        try:
            db.rollback()
        except Exception:
            db.invalidate()
            log("delivery_accepted", "database_cleanup_failed", logging.WARNING)
        else:
            log("delivery_accepted")
        if env["APP_ENV"] == "development" and env["MOCK_OTP"]:
            response.codigo_mock = mock
        return response
    except Exception:
        db.rollback()
        log("request_failed", "after_prepare" if prepared else "before_prepare", logging.ERROR)
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
