"""Testes somente em PostgreSQL descartável explicitamente informado."""
import os
from collections.abc import Generator

import pytest
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.getenv("LIVEN_TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise pytest.UsageError("Defina LIVEN_TEST_DATABASE_URL para um PostgreSQL descartável (banco liven_test_*).")
url = make_url(TEST_DATABASE_URL)
if url.get_backend_name() != "postgresql" or not (url.database or "").startswith("liven_test_"):
    raise pytest.UsageError("Testes exigem PostgreSQL isolado com nome liven_test_*; banco do projeto não é permitido.")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "development"
os.environ["MOCK_OTP"] = "true"
os.environ["OTP_EMAIL_PROVIDER"] = "development"
os.environ["RESEND_API_KEY"] = ""
os.environ["OTP_EMAIL_FROM"] = ""
os.environ["SMTP_USERNAME"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["SMTP_FROM"] = ""
os.environ["SMTP_HOST"] = "smtp.gmail.com"
os.environ["SMTP_PORT"] = "587"
os.environ["JWT_SECRET"] = "isolated-test-secret-never-use-in-production-123456"
os.environ["CORS_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"
os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from config.database import Base, engine, get_db
from config.config import env
from main import app
from security import otp_rate_limiter

TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def reset_database(monkeypatch) -> Generator[None, None, None]:
    # A URL foi validada antes de importar o engine. Nunca aponta para o banco liven.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setitem(env, "APP_ENV", "development")
    monkeypatch.setitem(env, "MOCK_OTP", True)
    # Suítes legadas exercitam compatibilidade; testes novos validam o padrão desativado.
    monkeypatch.setitem(env, "LEGACY_OTP_LOGIN_ENABLED", True)
    monkeypatch.setitem(env, "OTP_EMAIL_PROVIDER", "development")
    def block_delivery(*args, **kwargs):
        raise AssertionError("Rede de e-mail não mockada em teste.")
    monkeypatch.setattr("services.otp_delivery.urlopen", block_delivery)
    monkeypatch.setattr("services.otp_delivery.smtplib.SMTP", block_delivery)
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 0)
    with otp_rate_limiter._lock:
        otp_rate_limiter._events.clear()
    with TestingSession() as db:
        from models.orm import Condominio, Mapa, PerfilUsuario, Usuario
        condominio = Condominio(nome="Condomínio de teste")
        db.add(condominio)
        db.flush()
        db.add(Usuario(condominio_id=condominio.id, nome="Síndico de teste", telefone="5511999999998", perfil=PerfilUsuario.SINDICO))
        db.add(Mapa(nome="Teste", largura=1, altura=1))
        db.commit()
    yield
    Base.metadata.drop_all(engine)


def override_get_db() -> Generator[Session, None, None]:
    with TestingSession() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        from models.orm import Usuario
        from security import create_access_token
        with TestingSession() as db:
            test_client.headers["Authorization"] = f"Bearer {create_access_token(db.query(Usuario).first())}"
        yield test_client
