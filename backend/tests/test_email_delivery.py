import io
import json
from urllib.error import HTTPError, URLError

import pytest
from sqlalchemy import select

from config.config import env
from conftest import TestingSession
from models.orm import OtpChallenge, Usuario
from services.otp_delivery import DevelopmentOtpDelivery, OtpDeliveryError, ResendOtpDelivery, get_otp_delivery
from test_otp import EMAIL, account, challenge, request, verify


class Reply:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return b'{"id":"fake-message-id"}'


def configure(monkeypatch):
    monkeypatch.setitem(env, "OTP_EMAIL_PROVIDER", "resend")
    monkeypatch.setitem(env, "MOCK_OTP", False)
    monkeypatch.setitem(env, "APP_ENV", "production")
    monkeypatch.setitem(env, "RESEND_API_KEY", "fake-test-only")
    monkeypatch.setitem(env, "OTP_EMAIL_FROM", "Liven <login@example.com>")


def test_resend_envia_template_e_nao_expoe_codigo(client, monkeypatch):
    payload, _ = account()
    configure(monkeypatch)
    calls = []
    def fake_send(req, timeout):
        assert req.full_url == "https://api.resend.com/emails" and req.method == "POST"
        assert req.get_header("Authorization") == "Bearer fake-test-only"
        body = json.loads(req.data)
        assert body["to"] == [EMAIL] and "Liven" in body["subject"]
        assert "123456" in body["html"] and "123456" in body["text"]
        assert timeout == env["OTP_EMAIL_TIMEOUT_SECONDS"]
        calls.append(body)
        return Reply()
    monkeypatch.setattr("services.otp_delivery.urlopen", fake_send)
    monkeypatch.setattr("routers.auth.secrets.randbelow", lambda _: 123456)
    response = request(client, payload)
    assert response.status_code == 200 and "codigo_mock" not in response.json()
    assert len(calls) == 1
    assert verify(client, payload, "123456").status_code == 200


@pytest.mark.parametrize("failure", [TimeoutError(), URLError("private provider details"),
    HTTPError("https://api.resend.com/emails", 429, "sensitive", {}, io.BytesIO(b"secret"))])
def test_falha_provedor_generica_sem_vazar_e_sem_consumir_anterior(client, monkeypatch, caplog, failure):
    payload, _ = account()
    old_code = request(client, payload).json()["codigo_mock"]
    configure(monkeypatch)
    def fail(*args, **kwargs): raise failure
    monkeypatch.setattr("services.otp_delivery.urlopen", fail)
    response = request(client, payload)
    unknown = request(client, {**payload, "email": "unknown@example.com"})
    assert response.status_code == unknown.status_code == 200
    assert response.json() == unknown.json()
    assert "private provider details" not in caplog.text and "sensitive" not in caplog.text
    assert "secret" not in caplog.text and old_code not in caplog.text
    with TestingSession() as db:
        assert db.query(OtpChallenge).count() == 1
    assert challenge().used_at is None
    assert verify(client, payload, old_code).status_code == 200


@pytest.mark.parametrize("body", [b"not-json", b"{}", b"[]"])
def test_resposta_invalida_provedor(monkeypatch, body):
    configure(monkeypatch)
    class BadReply(Reply):
        def read(self, limit): return body
    monkeypatch.setattr("services.otp_delivery.urlopen", lambda *a, **kw: BadReply())
    with pytest.raises(OtpDeliveryError):
        ResendOtpDelivery().deliver(email=EMAIL, codigo="123456")


def test_sem_credenciais_falha_globalmente(client, monkeypatch):
    payload, _ = account()
    configure(monkeypatch)
    monkeypatch.setitem(env, "RESEND_API_KEY", "")
    for email in (EMAIL, "unknown@example.com"):
        result = request(client, {**payload, "email": email})
        assert result.status_code == 503 and "codigo_mock" not in result.json()
    assert challenge() is None


def test_mock_producao_nunca_habilitado(monkeypatch):
    monkeypatch.setitem(env, "APP_ENV", "production")
    monkeypatch.setitem(env, "MOCK_OTP", True)
    with pytest.raises(OtpDeliveryError):
        DevelopmentOtpDelivery().deliver(email=EMAIL, codigo="123456")
    from fastapi import HTTPException
    with pytest.raises(HTTPException): get_otp_delivery()


def test_telefone_nao_autentica(client):
    payload, _ = account()
    assert request(client, {"telefone": "5511999999901", "condominio_id": payload["condominio_id"]}).status_code == 422
    assert request(client, {**payload, "telefone": "5511999999901"}).status_code == 422


def test_troca_email_invalida_desafio_anterior(client):
    payload, uid = account()
    code = request(client, payload).json()["codigo_mock"]
    with TestingSession() as db:
        db.get(Usuario, uid).email = "new@example.com"
        db.commit()
    assert verify(client, payload, code).status_code == 401
    assert verify(client, {**payload, "email": "new@example.com"}, code).status_code == 401


def test_conta_legada_sem_email_nao_autentica(client):
    payload, uid = account()
    with TestingSession() as db:
        db.get(Usuario, uid).email = None
        db.commit()
    assert "codigo_mock" not in request(client, payload).json()
    assert verify(client, payload, "123456").status_code == 401
