import logging
import smtplib
from datetime import timedelta

import pytest

from config.config import env
from conftest import TestingSession
from models.orm import ContaGlobal, OtpCadastro
from security import utcnow, verify_secret
from services.passwords import verify_password
from test_registration import EMAIL, PASSWORD, register, request, verify
from test_smtp_delivery import configure, transport


def test_new_registration_actually_calls_smtp_and_records_acceptance(client, monkeypatch, caplog):
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    monkeypatch.setattr('services.global_auth.secrets.randbelow', lambda _: 603219)
    with caplog.at_level(logging.INFO):
        result = request(client)
    assert result.status_code == 200 and 'codigo_mock' not in result.json()
    server.login.assert_called_once()
    server.send_message.assert_called_once()
    assert 'outcome=delivery_started' in caplog.text and 'provider=SmtpOtpDelivery' in caplog.text
    assert 'otp_smtp outcome=accepted' in caplog.text
    assert 'outcome=challenge_prepared' in caplog.text and 'outcome=delivery_accepted' in caplog.text
    with TestingSession() as db:
        pending = db.get(OtpCadastro, EMAIL)
        assert verify_secret('cadastro:603219', pending.code_hash)
        assert verify_password(PASSWORD, pending.password_hash)
        assert db.query(ContaGlobal).count() == 0
    for sensitive in (EMAIL, PASSWORD, '603219', 'fake-test-app-password'):
        assert sensitive not in caplog.text and sensitive not in result.text
    assert verify(client, '603219').status_code == 201


def test_existing_account_200_is_generic_and_does_not_call_smtp(client, monkeypatch, caplog):
    register(client)
    caplog.clear()  # Examina somente a tentativa duplicada, não o envio inicial da fixture.
    configure(monkeypatch)
    constructor, server = transport(monkeypatch)
    with caplog.at_level(logging.INFO):
        duplicate = request(client, ' NEW@EXAMPLE.COM ')
    constructor.assert_not_called()
    server.send_message.assert_not_called()
    assert duplicate.status_code == 200
    assert 'reason=existing_account' in caplog.text
    assert 'outcome=delivery_started' not in caplog.text
    assert 'otp_smtp outcome=accepted' not in caplog.text
    fresh = request(client, 'fresh@example.com')
    assert fresh.status_code == duplicate.status_code and fresh.json() == duplicate.json()
    assert 'existing_account' not in duplicate.text and 'reason' not in duplicate.json()
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1


def test_cooldown_and_persistent_limit_do_not_claim_delivery(client, monkeypatch, caplog):
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    monkeypatch.setitem(env, 'OTP_RESEND_SECONDS', 60)
    request(client)
    with caplog.at_level(logging.INFO):
        assert request(client).status_code == 200
    assert server.send_message.call_count == 1
    assert 'reason=cooldown' in caplog.text
    with TestingSession() as db:
        pending = db.get(OtpCadastro, EMAIL)
        pending.last_requested_at = utcnow() - timedelta(seconds=61)
        pending.requests = env['OTP_RATE_LIMIT']
        db.commit()
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert request(client).status_code == 200
    assert server.send_message.call_count == 1
    assert 'reason=persistent_rate_limit' in caplog.text


@pytest.mark.parametrize('stage,error,logged_stage', [
    ('connect', TimeoutError('PRIVATE-SMTP-REPLY'), 'connect'),
    ('starttls', smtplib.SMTPNotSupportedError('PRIVATE-SMTP-REPLY'), 'starttls'),
    ('login', smtplib.SMTPAuthenticationError(535, b'PRIVATE-SMTP-REPLY'), 'auth'),
    ('send_message', smtplib.SMTPDataError(550, b'PRIVATE-SMTP-REPLY'), 'send'),
])
def test_smtp_failure_is_diagnosable_without_public_account_enumeration(client, monkeypatch, caplog, stage, error, logged_stage):
    configure(monkeypatch)
    constructor, server = transport(monkeypatch)
    if stage == 'connect': constructor.side_effect = error
    else: getattr(server, stage).side_effect = error
    with caplog.at_level(logging.INFO):
        response = request(client)
    assert response.status_code == 200 and 'codigo_mock' not in response.json()
    assert f'outcome=failed stage={logged_stage}' in caplog.text
    assert 'outcome=delivery_failed' in caplog.text and 'provider=SmtpOtpDelivery' in caplog.text
    assert 'outcome=delivery_accepted' not in caplog.text and 'otp_smtp outcome=accepted' not in caplog.text
    if stage == 'login': assert 'smtp_status=535' in caplog.text
    for sensitive in ('PRIVATE-SMTP-REPLY', EMAIL, PASSWORD, 'fake-test-app-password'):
        assert sensitive not in caplog.text and sensitive not in response.text
    with TestingSession() as db:
        pending = db.get(OtpCadastro, EMAIL)
        assert pending.code_hash is None and verify_password(PASSWORD, pending.password_hash)
        assert pending.requests == 0 and pending.last_requested_at is None and db.query(ContaGlobal).count() == 0


def test_expired_pending_resend_calls_smtp_without_replacing_password(client, monkeypatch):
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    request(client)
    with TestingSession() as db:
        pending = db.get(OtpCadastro, EMAIL)
        pending.expires_at = utcnow() - timedelta(seconds=1)
        before = pending.password_hash
        db.commit()
    response = client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL})
    assert response.status_code == 200 and server.send_message.call_count == 2
    with TestingSession() as db:
        assert db.get(OtpCadastro, EMAIL).password_hash == before
        assert db.get(OtpCadastro, EMAIL).expires_at > utcnow()
