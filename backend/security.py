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
from models.orm import Condominio, PerfilUsuario, Usuario


bearer_scheme = HTTPBearer(auto_error=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_phone(value: str) -> str:
    phone = re.sub(r"\D", "", value)
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


def create_access_token(user: Usuario) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "condominio_id": user.condominio_id,
        "perfil": user.perfil.value if isinstance(user.perfil, PerfilUsuario) else user.perfil,
        "iat": now,
        "exp": now + timedelta(minutes=env["ACCESS_TOKEN_MINUTES"]),
        "jti": secrets.token_urlsafe(16),
    }
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


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    if credentials is None:
        if env["APP_ENV"] == "development" and env.get("MOCK_OTP", False):
            return get_demo_header_user(request, db)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária.")
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado.")
    try:
        payload = jwt.decode(credentials.credentials, env["JWT_SECRET"], algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado.") from exc
    user = db.get(Usuario, user_id)
    if user is None or not user.ativo or user.condominio_id != payload.get("condominio_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado.")
    return user


def get_demo_header_user(request: Request, db: Session) -> Usuario:
    profile_value = request.headers.get("X-User-Profile")
    phone_value = request.headers.get("X-User-Phone")
    if profile_value not in {profile.value for profile in PerfilUsuario} or not phone_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária.")
    try:
        phone = normalize_phone(phone_value)
        profile = PerfilUsuario(profile_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credencial inválida.") from exc
    user = db.scalar(select(Usuario).where(Usuario.telefone == phone).order_by(Usuario.id))
    if user is None:
        condominio = db.scalar(select(Condominio).order_by(Condominio.id))
        if condominio is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Serviço indisponível.")
        user = Usuario(condominio_id=condominio.id, telefone=phone, nome=demo_profile_name(profile), perfil=profile)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.perfil != profile:
        user.perfil = profile
        db.commit()
    return user


def demo_profile_name(profile: PerfilUsuario) -> str:
    return {
        PerfilUsuario.MORADOR: "Morador da apresentação",
        PerfilUsuario.PORTARIA: "Equipe da portaria",
        PerfilUsuario.SINDICO: "Síndico da apresentação",
    }[profile]


def require_profiles(*profiles: PerfilUsuario):
    allowed = set(profiles)

    def dependency(user: Usuario = Depends(get_current_user)) -> Usuario:
        profile = user.perfil if isinstance(user.perfil, PerfilUsuario) else PerfilUsuario(user.perfil)
        if profile not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissão insuficiente.")
        return user

    return dependency