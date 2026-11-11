import smtplib
import ssl
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from config.config import env
from services.otp_delivery import OtpDeliveryError, ResendOtpDelivery, SmtpOtpDelivery, get_otp_delivery
from test_otp import account, challenge, request, verify


def configure(monkeypatch):
    for key, value in {
        "OTP_EMAIL_PROVIDER": "smtp", "MOCK_OTP": False, "APP_ENV": "production",
        "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": 587,
        "SMTP_USERNAME": "sender@example.com", "SMTP_PASSWORD": "fake-test-app-password",
        "SMTP_FROM": "Liven <sender@example.com>",
    }.items():
        monkeypatch.setitem(env, key, value)


def transport(monkeypatch):
    constructor = MagicMock()
    server = constructor.return_value.__enter__.return_value
    server.ehlo.return_value = (250, b"OK")
    server.send_message.return_value = {}
    monkeypatch.setattr("services.otp_delivery.smtplib.SMTP", constructor)
    return constructor, server


def test_smtp_starttls_antes_de_autenticar_e_template_multipart(monkeypatch):
    configure(monkeypatch)
    constructor, server = transport(monkeypatch)
    assert get_otp_delivery().deliver(email="resident@example.com", codigo="603219") is None
    constructor.assert_called_once_with("smtp.gmail.com", 587, timeout=env["OTP_EMAIL_TIMEOUT_SECONDS"])
    assert [item[0] for item in server.method_calls] == ["ehlo", "starttls", "ehlo", "login", "send_message"]
    context = server.starttls.call_args.kwargs["context"]
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    server.login.assert_called_once_with("sender@example.com", "fake-test-app-password")
    args, kwargs = server.send_message.call_args
    message = args[0]
    assert message["From"] == "Liven <sender@example.com>"
    assert message["To"] == "resident@example.com"
    assert message["Subject"] == "Seu código de acesso ao Liven"
    assert kwargs == {"from_addr": "sender@example.com", "to_addrs": ["resident@example.com"]}
    assert "603219" in message.get_body(preferencelist=("plain",)).get_content()
    assert "603219" in message.get_body(preferencelist=("html",)).get_content()
    assert "minutos" in message.get_body(preferencelist=("plain",)).get_content()
    server.set_debuglevel.assert_not_called()


@pytest.mark.parametrize("key,value", [
    ("MOCK_OTP", True), ("SMTP_HOST", ""), ("SMTP_USERNAME", ""),
    ("SMTP_PASSWORD", ""), ("SMTP_FROM", ""), ("SMTP_PORT", 0), ("SMTP_PORT", 65536),
])
def test_configuracao_incompleta_bloqueia_sem_conectar(monkeypatch, key, value):
    configure(monkeypatch)
    constructor, _ = transport(monkeypatch)
    monkeypatch.setitem(env, key, value)
    with pytest.raises(HTTPException) as error:
        get_otp_delivery()
    assert error.value.status_code == 503
    constructor.assert_not_called()


@pytest.mark.parametrize("stage,error", [
    ("connect", ConnectionRefusedError("PRIVATE-DATA")),
    ("connect", TimeoutError("PRIVATE-DATA")),
    ("starttls", smtplib.SMTPNotSupportedError("PRIVATE-DATA")),
    ("starttls", ssl.SSLError("PRIVATE-DATA")),
    ("login", smtplib.SMTPAuthenticationError(535, b"PRIVATE-DATA")),
    ("send_message", smtplib.SMTPRecipientsRefused({"resident@example.com": (550, b"PRIVATE-DATA")})),
    ("send_message", smtplib.SMTPSenderRefused(550, b"PRIVATE-DATA", "sender@example.com")),
    ("send_message", smtplib.SMTPDataError(421, b"PRIVATE-DATA")),
    ("send_message", smtplib.SMTPServerDisconnected("PRIVATE-DATA")),
])
def test_falhas_sanitizadas_e_sem_autenticacao_antes_tls(monkeypatch, caplog, stage, error):
    configure(monkeypatch)
    constructor, server = transport(monkeypatch)
    if stage == "connect": constructor.side_effect = error
    else: getattr(server, stage).side_effect = error
    with pytest.raises(OtpDeliveryError) as result:
        SmtpOtpDelivery().deliver(email="resident@example.com", codigo="603219")
    assert str(result.value) == "Entrega indisponível."
    assert result.value.__suppress_context__
    for sensitive in ("PRIVATE-DATA", "603219", "fake-test-app-password", "resident@example.com"):
        assert sensitive not in str(result.value) and sensitive not in caplog.text
    if stage in ("connect", "starttls"):
        server.login.assert_not_called()
        server.send_message.assert_not_called()


@pytest.mark.parametrize("responses", [[(500, b"PRIVATE")], [(250, b"OK"), (500, b"PRIVATE")]])
def test_ehlo_rejeitado_nao_envia_credenciais(monkeypatch, responses):
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    server.ehlo.side_effect = responses
    with pytest.raises(OtpDeliveryError):
        SmtpOtpDelivery().deliver(email="resident@example.com", codigo="603219")
    server.login.assert_not_called()
    server.send_message.assert_not_called()


def test_destinatario_rejeitado_em_retorno(monkeypatch):
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    server.send_message.return_value = {"resident@example.com": (550, b"PRIVATE")}
    with pytest.raises(OtpDeliveryError):
        SmtpOtpDelivery().deliver(email="resident@example.com", codigo="603219")


def test_injecao_header_e_remetente_invalido_nao_conectam(monkeypatch):
    configure(monkeypatch)
    constructor, _ = transport(monkeypatch)
    for sender in ("invalid", "sender@example.com\nBcc: other@example.com"):
        monkeypatch.setitem(env, "SMTP_FROM", sender)
        with pytest.raises(OtpDeliveryError):
            SmtpOtpDelivery().deliver(email="resident@example.com", codigo="603219")
    constructor.assert_not_called()


def test_smtp_fluxo_otp_preserva_tokens_e_nao_retorna_codigo(client, monkeypatch):
    payload, _ = account()
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    monkeypatch.setattr("routers.auth.secrets.randbelow", lambda _: 603219)
    result = request(client, payload)
    assert result.status_code == 200 and "codigo_mock" not in result.json()
    assert server.send_message.call_count == 1
    assert challenge().email == payload["email"]
    assert verify(client, payload, "603219").status_code == 200
    assert verify(client, payload, "603219").status_code == 401


def test_falha_smtp_reverte_novo_desafio_e_preserva_anterior(client, monkeypatch, caplog):
    payload, _ = account()
    old_code = request(client, payload).json()["codigo_mock"]
    old_id = challenge().id
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"PRIVATE-DATA")
    result = request(client, payload)
    assert result.status_code == 200 and "codigo_mock" not in result.json()
    assert challenge().id == old_id and challenge().used_at is None
    assert "PRIVATE-DATA" not in caplog.text and "fake-test-app-password" not in caplog.text
    assert old_code not in caplog.text
    assert verify(client, payload, old_code).status_code == 200


def test_selecao_resend_preservada(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setitem(env, "OTP_EMAIL_PROVIDER", "resend")
    monkeypatch.setitem(env, "RESEND_API_KEY", "fake-test-key")
    monkeypatch.setitem(env, "OTP_EMAIL_FROM", "sender@example.com")
    assert isinstance(get_otp_delivery(), ResendOtpDelivery)
