"""Entrega OTP por e-mail. A factory não realiza chamadas de rede."""
import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from html import escape
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException

from config.config import env

logger = logging.getLogger(__name__)


class OtpDeliveryError(Exception):
    """Falha sanitizada: nunca incluir resposta do SDK, código ou credenciais."""


class OtpDeliveryIndeterminate(OtpDeliveryError):
    """The provider may have accepted DATA; preserve the durable challenge."""


class OtpDelivery(Protocol):
    def deliver(self, *, email: str, codigo: str) -> str | None: ...


class DevelopmentOtpDelivery:
    def deliver(self, *, email: str, codigo: str) -> str:
        if env["APP_ENV"] != "development" or not env["MOCK_OTP"]:
            raise OtpDeliveryError("Entrega indisponível.")
        return codigo


def email_content(codigo: str) -> tuple[str, str]:
    minutes = env["OTP_EXPIRY_MINUTES"]
    text = f"Liven — seu código de acesso: {codigo}. Válido por {minutes} minutos. Não compartilhe este código. Se não solicitou acesso, ignore esta mensagem."
    html = f'''<html lang="pt-BR"><body style="font-family:Arial,sans-serif;background:#f4f6f8;padding:24px">
    <main style="max-width:480px;margin:auto;background:white;padding:32px;border-radius:12px">
    <h1 style="color:#176b57">Liven</h1><h2>Seu código de acesso</h2>
    <p>Use o código abaixo para verificar seu e-mail e acessar o Liven.</p>
    <p style="font-size:32px;letter-spacing:8px;font-weight:bold">{escape(codigo)}</p>
    <p>Válido por {minutes} minutos. Não compartilhe este código.</p>
    <p>Se você não solicitou acesso, ignore esta mensagem.</p></main></body></html>'''
    return text, html


class ResendOtpDelivery:
    def deliver(self, *, email: str, codigo: str) -> None:
        text, html = email_content(codigo)
        req = Request(
            "https://api.resend.com/emails",
            data=json.dumps({"from": env["OTP_EMAIL_FROM"], "to": [email],
                             "subject": "Seu código de acesso ao Liven", "text": text, "html": html}).encode(),
            headers={"Authorization": f"Bearer {env['RESEND_API_KEY']}",
                     "Content-Type": "application/json", "User-Agent": "Liven-OTP/1.0"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=env["OTP_EMAIL_TIMEOUT_SECONDS"]) as result:
                body = json.loads(result.read(65536))
                if not 200 <= result.status < 300 or not isinstance(body, dict) or not body.get("id"):
                    raise OtpDeliveryError("Entrega indisponível.")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            # Não propagar nem registrar detalhes externos que possam conter segredos.
            raise OtpDeliveryError("Entrega indisponível.") from None


class SmtpOtpDelivery:
    def deliver(self, *, email: str, codigo: str) -> None:
        stage = "message"
        try:
            text, html = email_content(codigo)
            message = EmailMessage()
            message["From"] = env["SMTP_FROM"]
            message["To"] = email
            message["Subject"] = "Seu código de acesso ao Liven"
            message.set_content(text)
            message.add_alternative(html, subtype="html")
            sender = parseaddr(env["SMTP_FROM"])[1]
            if not sender or "@" not in sender:
                raise ValueError("Remetente inválido.")
            # Sem debug SMTP: comandos AUTH e conteúdo nunca devem aparecer nos logs.
            stage = "connect"
            with smtplib.SMTP(env["SMTP_HOST"], env["SMTP_PORT"],
                              timeout=env["OTP_EMAIL_TIMEOUT_SECONDS"]) as server:
                stage = "ehlo"
                code, reply = server.ehlo()
                if code != 250:
                    raise smtplib.SMTPHeloError(code, reply)
                stage = "starttls"
                server.starttls(context=ssl.create_default_context())
                stage = "ehlo_tls"
                code, reply = server.ehlo()
                if code != 250:
                    raise smtplib.SMTPHeloError(code, reply)
                stage = "auth"
                server.login(env["SMTP_USERNAME"], env["SMTP_PASSWORD"])
                stage = "send"
                refused = server.send_message(message, from_addr=sender, to_addrs=[email])
                if refused:
                    logger.warning("otp_smtp outcome=failed stage=send reason=recipient_refused")
                    raise OtpDeliveryError("Entrega indisponível.")
                stage = "quit"
        except (smtplib.SMTPException, OSError, ValueError) as exc:
            # Respostas SMTP podem conter destinatários, senha ou conteúdo: não propagá-las.
            smtp_status = getattr(exc, "smtp_code", None)
            if not isinstance(smtp_status, int) or isinstance(smtp_status, bool) or not 100 <= smtp_status <= 599:
                smtp_status = None
            if stage == "quit":
                # send_message already confirmed acceptance. A failed QUIT
                # cannot undo it and must not invalidate the persisted OTP.
                logger.warning("otp_smtp outcome=accepted stage=quit reason=cleanup_failed error=%s smtp_status=%s",
                               type(exc).__name__, smtp_status)
                return None
            if stage == "send" and not isinstance(exc, (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused)):
                logger.warning("otp_smtp outcome=indeterminate stage=send error=%s smtp_status=%s",
                               type(exc).__name__, smtp_status)
                raise OtpDeliveryIndeterminate("Entrega indisponível.") from None
            logger.warning("otp_smtp outcome=failed stage=%s error=%s smtp_status=%s",
                           stage, type(exc).__name__, smtp_status)
            raise OtpDeliveryError("Entrega indisponível.") from None
        # Confirma aceitação pelo transporte; não comprova recebimento na caixa de entrada.
        logger.info("otp_smtp outcome=accepted")


def get_otp_delivery() -> OtpDelivery:
    provider = env["OTP_EMAIL_PROVIDER"]
    if provider == "development" and env["APP_ENV"] == "development" and env["MOCK_OTP"]:
        return DevelopmentOtpDelivery()
    if provider == "resend" and not env["MOCK_OTP"] and env["RESEND_API_KEY"] and env["OTP_EMAIL_FROM"]:
        return ResendOtpDelivery()
    if (provider == "smtp" and not env["MOCK_OTP"]
            and all(env[key] for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"))
            and 1 <= env["SMTP_PORT"] <= 65535):
        return SmtpOtpDelivery()
    # Configuração inválida afeta todos os solicitantes, sem revelar existência de conta.
    raise HTTPException(503, "Entrega de código indisponível.")
