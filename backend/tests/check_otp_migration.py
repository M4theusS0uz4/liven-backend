"""Verificação isolada de upgrade com um desafio legado; não é coletada pelo pytest.

Executar somente em PostgreSQL descartável vazio via LIVEN_TEST_DATABASE_URL.
"""
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
        raise RuntimeError("Exige banco PostgreSQL de teste liven_test_*.")
    os.environ["DATABASE_URL"] = url
    engine = create_engine(url)
    if inspect(engine).get_table_names():
        raise RuntimeError("Esta verificação exige um banco de teste vazio.")
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "20260928_0006")
    with engine.begin() as db:
        legacy_id = db.scalar(text("INSERT INTO otp_challenges (telefone, code_hash, expires_at) VALUES ('5511999999901', 'legacy-hash', now() + interval '5 minutes') RETURNING id"))
    command.upgrade(cfg, "head")
    with engine.connect() as db:
        legacy = db.execute(text("SELECT usuario_id, code_hash FROM otp_challenges WHERE id=:id"), {"id": legacy_id}).one()
        assert legacy == (None, "legacy-hash")
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261104_0007"
    inspector = inspect(engine)
    assert any(fk["constrained_columns"] == ["usuario_id"] for fk in inspector.get_foreign_keys("otp_challenges"))
    assert any(index["name"] == "ix_otp_challenges_usuario_id" for index in inspector.get_indexes("otp_challenges"))
    engine.dispose()
    print("Migration OTP: upgrade 0006 → 0007 preservou desafio legado, FK e índice validados.")


if __name__ == "__main__":
    main()
