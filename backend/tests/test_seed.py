import pytest
from sqlalchemy import select

import seed
from config.config import env
from conftest import TestingSession
from models.orm import Condominio, Morador, Usuario, Unidade


def counts():
    with TestingSession() as db:
        return tuple(db.query(model).count() for model in (Condominio, Usuario, Unidade, Morador))


def test_seed_simula_sem_escrever(monkeypatch, capsys):
    monkeypatch.setattr(seed, "SessionLocal", TestingSession)
    before = counts()
    seed.run()
    assert counts() == before
    assert "SIMULAÇÃO" in capsys.readouterr().out


def test_seed_idempotente_e_perfis_preservados(monkeypatch):
    monkeypatch.setattr(seed, "SessionLocal", TestingSession)
    seed.run(condominio_id=1, apply=True)
    before = counts()
    seed.run(condominio_id=1, apply=True)
    assert counts() == before
    with TestingSession() as db:
        user = db.scalar(select(Usuario).where(Usuario.telefone == "5511999999901"))
        user.ativo = False
        db.commit()
    with pytest.raises(RuntimeError, match="perfil/estado"):
        seed.run(condominio_id=1, apply=True)
    with TestingSession() as db:
        assert not db.scalar(select(Usuario).where(Usuario.telefone == "5511999999901")).ativo


def test_seed_bloqueado_em_producao(monkeypatch):
    monkeypatch.setitem(env, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="development"):
        seed.run(apply=True)
