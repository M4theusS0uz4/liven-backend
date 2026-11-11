"""Upgrade real apenas em PostgreSQL descartável vazio; preserva fixture de usuário legado."""
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def main():
    url = os.environ["LIVEN_TEST_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or not (parsed.database or "").startswith("liven_test_"):
        raise RuntimeError("Exige PostgreSQL descartável liven_test_*.")
    os.environ["DATABASE_URL"] = url
    os.environ["APP_ENV"] = "development"
    os.environ["MOCK_OTP"] = "true"
    os.environ["OTP_EMAIL_PROVIDER"] = "development"
    os.environ["JWT_SECRET"] = "isolated-migration-test-secret-only-1234567890"
    engine = create_engine(url)
    if inspect(engine).get_table_names():
        raise RuntimeError("Exige banco de teste vazio.")
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "20261110_0008")
    from config.database import SessionLocal
    from models.orm import Condominio, ContaGlobal, Morador, Unidade, Usuario
    with SessionLocal.begin() as db:
        condo = db.query(Condominio).first()
        unit = Unidade(condominio_id=condo.id, bloco="MIGRATION", numero="1")
        user = Usuario(condominio_id=condo.id, telefone="5511999999999", nome="Legacy test", email="legacy@example.com", perfil="morador", ativo=True)
        db.add_all([unit, user])
        db.flush()
        resident = Morador(unidade_id=unit.id, usuario_id=user.id, nome="Legacy test", email=user.email)
        db.add(resident)
        unit_id = unit.id
    with engine.connect() as c:
        before = c.execute(text("SELECT u.id,u.condominio_id,u.telefone,u.nome,u.email,u.perfil,u.ativo,m.id,m.unidade_id FROM usuarios u JOIN moradores m ON m.usuario_id=u.id")).all()
        old_columns = {t: inspect(engine).get_columns(t) for t in ("usuarios", "moradores", "unidades", "otp_challenges")}
    command.upgrade(cfg, "20261111_0009")
    with engine.begin() as c:
        c.execute(text("INSERT INTO contas_globais (email, ativo, email_verificado_em) VALUES (:email, true, now())"), {"email": "existing-global@example.com"})
    command.upgrade(cfg, "20261111_0011")
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "20261111_0011"
        assert c.scalar(text("SELECT password_hash IS NULL FROM contas_globais WHERE email = :email"), {"email": "existing-global@example.com"})
        after = c.execute(text("SELECT u.id,u.condominio_id,u.telefone,u.nome,u.email,u.perfil,u.ativo,m.id,m.unidade_id FROM usuarios u JOIN moradores m ON m.usuario_id=u.id")).all()
        assert before == after
        for table in ("otp_cadastro", "otp_login_global", "sessoes_globais", "otp_definicao_senha", "limites_login"):
            assert c.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        for table, columns in old_columns.items():
            now = inspect(engine).get_columns(table)
            assert [(v["name"],str(v["type"]),v["nullable"]) for v in columns] == [(v["name"],str(v["type"]),v["nullable"]) for v in now]
    # Testa o fluxo HTTP sobre o schema migrado, sem entrega externa.
    from fastapi.testclient import TestClient
    from main import app
    from config.config import env
    env["LEGACY_OTP_LOGIN_ENABLED"] = True  # Regressão explícita da compatibilidade.
    with TestClient(app) as client:
        requested = client.post("/api/v1/auth/register/request-otp", json={"email": "global@example.com", "senha": "Migration-test-password"})
        assert requested.status_code == 200
        registered = client.post("/api/v1/auth/register/verify-otp", json={"email": "global@example.com", "senha": "Migration-test-password", "codigo": requested.json()["codigo_mock"]})
        assert registered.status_code == 201
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        assert client.get("/api/v1/auth/global/me", headers=headers).status_code == 200
        assert client.get("/api/v1/unidades", headers=headers).status_code == 401
        requested = client.post("/api/v1/auth/request-otp", json={"email": "legacy@example.com", "condominio_id": 1})
        assert requested.status_code == 200
        logged = client.post("/api/v1/auth/verify-otp", json={"email": "legacy@example.com", "condominio_id": 1, "codigo": requested.json()["codigo_mock"]})
        assert logged.status_code == 200
        assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {logged.json()['access_token']}"}).json()["unidade_id"] == unit_id
    engine.dispose()
    print("Upgrade 0008 → 0011 validado; conta antiga sem senha preservada; dados/vínculos preservados; cadastro global e login legado aprovados no schema migrado.")


if __name__ == "__main__":
    main()
