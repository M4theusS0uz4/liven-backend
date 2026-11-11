import hashlib
import hmac
import re
import secrets
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.config import env
from config.database import get_db
from models.orm import ContaGlobal, PerfilUsuario, RefreshToken, SessaoGlobal, Usuario


bearer_scheme = HTTPBearer(auto_error=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_phone(value: str) -> str:
    if not re.fullmatch(r"\+?[\d\s().-]+", value.strip()):
        raise ValueError("Telefone inválido.")
    phone = re.sub(r"\D", "", value)
    if len(phone) in (10, 11):
        phone = "55" + phone
    if not 8 <= len(phone) <= 15:
        raise ValueError("Telefone inválido.")
    return phone


def hash_secret(value: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_secret(value: str, encoded: str) -> bool:
    try:
        salt, expected = encoded.split("$", 1)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(actual, expected)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_access_token(user: Usuario, session_id: int | None = None) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "condominio_id": user.condominio_id,
        "perfil": user.perfil.value if isinstance(user.perfil, PerfilUsuario) else user.perfil,
        "iat": now,
        "exp": now + timedelta(minutes=env["ACCESS_TOKEN_MINUTES"]),
        "jti": secrets.token_urlsafe(16),
    }
    if session_id is not None:
        payload["sid"] = session_id
    return jwt.encode(payload, env["JWT_SECRET"], algorithm="HS256")


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = utcnow()
        cutoff = now - timedelta(seconds=window_seconds)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


otp_rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def load_global_state(payload: dict, db: Session) -> tuple[ContaGlobal, SessaoGlobal]:
    error = HTTPException(401, "Sessão inválida ou expirada.")
    if not {"sub", "exp", "iat", "scope", "token_type", "sid"}.issubset(payload):
        raise error
    subject, sid = payload["sub"], payload["sid"]
    if not isinstance(subject, str) or not subject.startswith("global:") or payload["token_type"] != "access" or payload["scope"] not in ("global", "condominio"):
        raise error
    try:
        account_id = int(subject.removeprefix("global:"))
    except ValueError:
        raise error from None
    if not isinstance(sid, int) or isinstance(sid, bool):
        raise error
    account, session = db.get(ContaGlobal, account_id), db.get(SessaoGlobal, sid)
    if account is None or not account.ativo or account.email_verificado_em is None:
        raise error
    if session is None or session.conta_id != account.id or session.revoked_at is not None or as_utc(session.expires_at) <= utcnow():
        raise error
    if (payload["scope"] == "global") != (session.usuario_id is None):
        raise error
    return account, session


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária.")
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado.")
    try:
        payload = jwt.decode(credentials.credentials, env["JWT_SECRET"], algorithms=["HS256"])
        if str(payload.get("sub", "")).startswith("global:") or payload.get("scope") in ("global", "condominio"):
            account, session = load_global_state(payload, db)
            if payload["scope"] != "condominio":
                raise HTTPException(401, "Contexto de condomínio necessário.")
            user = db.get(Usuario, session.usuario_id)
            from services.memberships import valid_membership
            if not valid_membership(user, account.email) or user.id != payload.get("usuario_id") or user.condominio_id != payload.get("condominio_id") or user.perfil != payload.get("perfil"):
                raise HTTPException(401, "Vínculo inválido ou revogado.")
            return user
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado.") from exc
    user = db.get(Usuario, user_id)
    if user is None or not user.ativo or not user.condominio.ativo or user.condominio_id != payload.get("condominio_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado.")
    if "sid" in payload:
        sid = payload["sid"]
        session = db.get(RefreshToken, sid) if isinstance(sid, int) and not isinstance(sid, bool) else None
        if session is None or session.usuario_id != user.id or session.revoked_at is not None or as_utc(session.expires_at) <= utcnow():
            raise HTTPException(401, "Token inválido ou expirado.")
    elif not env["LEGACY_OTP_LOGIN_ENABLED"]:
        # Tokens antigos sem sessão rastreável só existem no modo de transição explícito.
        raise HTTPException(401, "Token inválido ou expirado.")
    return user


def require_profiles(*profiles: PerfilUsuario):
    allowed = set(profiles)

    def dependency(user: Usuario = Depends(get_current_user)) -> Usuario:
        profile = user.perfil if isinstance(user.perfil, PerfilUsuario) else PerfilUsuario(user.perfil)
        if profile not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissão insuficiente.")
        return user

    return dependency
