import os
from collections.abc import Generator

os.environ["DATABASE_URL"] = "sqlite:///./test_liven.db"
os.environ["CORS_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.database import Base, get_db
from main import app

engine = create_engine("sqlite:///./test_liven.db", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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
