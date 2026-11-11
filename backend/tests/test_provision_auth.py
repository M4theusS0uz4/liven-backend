import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import provision_auth
from conftest import TestingSession
from models.orm import Condominio, Morador, PerfilUsuario, Unidade, Usuario
from test_otp import account, challenge, request


def resident():
    with TestingSession() as db:
        unit = Unidade(condominio_id=1, bloco="Provision", numero="1")
        db.add(unit)
        db.flush()
        item = Morador(unidade_id=unit.id, nome="Morador cadastrado", telefone="5511988887777")
        db.add(item)
        db.commit()
        return item.id


def test_provision_simula_e_cria_apenas_com_opcao_explicita(monkeypatch):
    monkeypatch.setattr(provision_auth, "SessionLocal", TestingSession)
    rid = resident()
    args = dict(condominio_id=1, email="  NOVO@EXAMPLE.COM ", morador_id=rid)
    with pytest.raises(ValueError, match="criação exige"):
        provision_auth.provision(**args)
    provision_auth.provision(**args, criar_conta=True)
    with TestingSession() as db:
        assert db.get(Morador, rid).usuario_id is None
    provision_auth.provision(**args, criar_conta=True, apply=True)
    provision_auth.provision(**args, criar_conta=True, apply=True)
    with TestingSession() as db:
        user = db.get(Usuario, db.get(Morador, rid).usuario_id)
        assert user.email == "novo@example.com" and user.perfil == PerfilUsuario.MORADOR
        assert db.query(Usuario).filter(Usuario.email == "novo@example.com").count() == 1


def test_email_conta_existente_nao_muda_perfil_e_revoga_otp(client, monkeypatch):
    monkeypatch.setattr(provision_auth, "SessionLocal", TestingSession)
    payload, uid = account()
    request(client, payload)
    provision_auth.provision(condominio_id=1, usuario_id=uid, email="new@example.com", apply=True)
    assert challenge().used_at is not None
    with TestingSession() as db:
        assert db.get(Usuario, uid).perfil == PerfilUsuario.MORADOR
        assert db.get(Usuario, uid).telefone == "5511999999901"


def test_provision_rejeita_condominio_errado_e_inativo(monkeypatch):
    monkeypatch.setattr(provision_auth, "SessionLocal", TestingSession)
    _, uid = account()
    with TestingSession() as db:
        other = Condominio(nome="Outro")
        db.add(other)
        db.commit()
        oid = other.id
    with pytest.raises(ValueError, match="Conta inválida"):
        provision_auth.provision(condominio_id=oid, usuario_id=uid, email="new@example.com", apply=True)
    with TestingSession() as db:
        db.get(Usuario, uid).ativo = False
        db.commit()
    with pytest.raises(ValueError, match="Conta inválida"):
        provision_auth.provision(condominio_id=1, usuario_id=uid, email="new@example.com", apply=True)


def test_email_unico_no_condominio_e_normalizado():
    _, uid = account()
    with TestingSession() as db:
        db.add(Usuario(condominio_id=1, nome="Outro", telefone="5511888888888", email="morador@example.com", perfil=PerfilUsuario.MORADOR))
        with pytest.raises(IntegrityError): db.commit()
    with TestingSession() as db:
        db.get(Usuario, uid).email = "MORADOR@EXAMPLE.COM"
        with pytest.raises(IntegrityError): db.commit()
