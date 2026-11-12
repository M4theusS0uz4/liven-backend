"""Registration recovery: real isolated PostgreSQL, simulated SMTP only."""
import logging
import secrets
import smtplib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from config.config import env
from config.database import engine
from conftest import TestingSession
from models.orm import ContaGlobal, OtpCadastro, SessaoGlobal
from security import otp_rate_limiter, verify_secret
from services.passwords import verify_password
from test_registration import EMAIL, PASSWORD, request, verify
from test_smtp_delivery import configure, transport


@pytest.fixture
def smtp(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setitem(env, 'LEGACY_OTP_LOGIN_ENABLED', False)
    monkeypatch.setitem(env, 'OTP_RESEND_SECONDS', 60)
    code = f'{secrets.randbelow(1_000_000):06d}'
    monkeypatch.setattr('services.global_auth.secrets.randbelow', lambda _: int(code))
    constructor, server = transport(monkeypatch)
    return constructor, server, code


def fail_auth(server):
    server.login.side_effect = smtplib.SMTPAuthenticationError(535, b'simulated-private-reply')


def pending():
    with TestingSession() as db:
        row = db.get(OtpCadastro, EMAIL)
        return {key: getattr(row, key) for key in ('password_hash', 'code_hash', 'requests', 'last_requested_at', 'attempts')}


def test_accepted_registration_confirms_session_and_password_login(client, smtp, caplog):
    _, server, code = smtp
    with caplog.at_level(logging.INFO):
        response = request(client)
    assert response.status_code == 200 and 'codigo_mock' not in response.json()
    assert server.send_message.call_count == 1
    assert 'outcome=challenge_prepared' in caplog.text
    assert 'outcome=delivery_accepted' in caplog.text
    assert caplog.text.index('outcome=challenge_prepared') < caplog.text.index('outcome=delivery_started')
    response = verify(client, code)
    assert response.status_code == 201
    result = response.json()
    assert result['scope'] == 'global' and result['vinculos'] == []
    assert result['conta']['ativo'] and result['conta']['email_verificado_em']
    headers = {'Authorization': 'Bearer ' + result['access_token']}
    assert client.get('/api/v1/auth/global/me', headers=headers).status_code == 200
    assert client.get('/api/v1/me', headers=headers).status_code == 401
    assert verify(client, code).status_code == 401
    assert client.post('/api/v1/auth/login', json={'email': EMAIL, 'senha': PASSWORD}).status_code == 200
    assert server.send_message.call_count == 1
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1 and db.query(SessaoGlobal).count() == 2
    for secret in (EMAIL, PASSWORD, code, result['access_token'], result['refresh_token']):
        assert secret not in caplog.text


def test_first_failure_retains_password_without_send_cooldown(client, smtp, caplog):
    _, server, _ = smtp
    fail_auth(server)
    with caplog.at_level(logging.INFO):
        response = request(client)
    assert response.status_code == 200
    row = pending()
    assert row['code_hash'] is None and verify_password(PASSWORD, row['password_hash'])
    assert row['requests'] == 0 and row['last_requested_at'] is None
    assert 'outcome=delivery_failed' in caplog.text and 'outcome=delivery_accepted' not in caplog.text
    assert 'simulated-private-reply' not in caplog.text


def test_immediate_new_request_after_failure_preserves_initial_hash(client, smtp):
    _, server, code = smtp
    fail_auth(server)
    assert request(client).status_code == 200
    original = pending()['password_hash']
    server.login.side_effect = None
    assert request(client).status_code == 200
    assert pending()['password_hash'] == original
    assert pending()['requests'] == 1 and server.send_message.call_count == 1
    assert verify(client, code).status_code == 201


def test_resend_after_initial_failure_uses_original_password(client, smtp):
    _, server, code = smtp
    fail_auth(server)
    request(client)
    original = pending()['password_hash']
    server.login.side_effect = None
    response = client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL})
    assert response.status_code == 200 and server.send_message.call_count == 1
    assert pending()['password_hash'] == original
    assert verify(client, code).status_code == 201


def test_third_party_cannot_change_password_through_resend(client, smtp):
    _, server, code = smtp
    fail_auth(server)
    request(client)
    original = pending()['password_hash']
    other_password = secrets.token_urlsafe(24)
    response = client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL, 'senha': other_password})
    assert response.status_code == 422
    assert pending()['password_hash'] == original
    server.login.side_effect = None
    assert client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL}).status_code == 200
    assert verify(client, code, senha=other_password).status_code == 401
    assert verify(client, code).status_code == 201
    assert client.post('/api/v1/auth/login', json={'email': EMAIL, 'senha': other_password}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'email': EMAIL, 'senha': PASSWORD}).status_code == 200


def test_successful_send_keeps_cooldown(client, smtp, caplog):
    _, server, _ = smtp
    request(client)
    with caplog.at_level(logging.INFO):
        assert client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL}).status_code == 200
    assert server.send_message.call_count == 1 and pending()['requests'] == 1
    assert 'reason=cooldown' in caplog.text


def test_repeated_failures_have_bounded_attempt_budget(client, smtp):
    _, server, _ = smtp
    fail_auth(server)
    for _ in range(env['OTP_RATE_LIMIT'] * 2):
        assert request(client).status_code == 200
    assert request(client).status_code == 429
    assert server.login.call_count == env['OTP_RATE_LIMIT'] * 2
    assert pending()['requests'] == 0


def test_failure_refunds_original_email_and_ip_send_budgets(client, smtp, monkeypatch):
    _, server, _ = smtp
    fail_auth(server)
    request(client)
    server.login.side_effect = None
    monkeypatch.setitem(env, 'OTP_RESEND_SECONDS', 0)
    # One failure must not remove one of the original three successful sends.
    for _ in range(env['OTP_RATE_LIMIT']):
        assert request(client).status_code == 200
    assert server.send_message.call_count == env['OTP_RATE_LIMIT']
    assert request(client).status_code == 429


def test_accepted_smtp_quit_failure_preserves_valid_code(client, smtp, caplog):
    constructor, server, code = smtp
    constructor.return_value.__exit__.side_effect = smtplib.SMTPResponseException(421, b'private-quit-reply')
    with caplog.at_level(logging.INFO):
        assert request(client).status_code == 200
    assert server.send_message.call_count == 1
    assert 'reason=cleanup_failed' in caplog.text and 'outcome=delivery_accepted' in caplog.text
    assert 'private-quit-reply' not in caplog.text
    assert verify(client, code).status_code == 201


def test_disconnect_during_data_is_indeterminate_and_keeps_durable_code(client, smtp, caplog):
    _, server, code = smtp
    server.send_message.side_effect = smtplib.SMTPServerDisconnected('private-send-reply')
    with caplog.at_level(logging.INFO):
        assert request(client).status_code == 200
    row = pending()
    assert verify_secret('cadastro:' + code, row['code_hash']) and row['requests'] == 1
    assert 'outcome=delivery_indeterminate' in caplog.text
    assert 'outcome=delivery_accepted' not in caplog.text and 'private-send-reply' not in caplog.text
    # If the recipient did receive it, it must remain usable exactly once.
    assert verify(client, code).status_code == 201


def test_smtp_rejection_of_data_restores_previous_challenge(client, smtp, monkeypatch):
    _, server, first = smtp
    request(client)
    before = pending()
    monkeypatch.setitem(env, 'OTP_RESEND_SECONDS', 0)
    second = f'{(int(first) + 1) % 1_000_000:06d}'
    monkeypatch.setattr('services.global_auth.secrets.randbelow', lambda _: int(second))
    server.send_message.side_effect = smtplib.SMTPDataError(550, b'simulated-rejection')
    assert request(client).status_code == 200
    assert pending() == before
    assert verify(client, second).status_code == 401
    assert verify(client, first).status_code == 201


def test_preparation_commit_failure_never_calls_smtp(client, smtp, monkeypatch):
    constructor, _, _ = smtp
    original_commit = Session.commit
    def fail_preparation(db):
        if any(isinstance(obj, OtpCadastro) for obj in db.dirty):
            raise OperationalError('simulated', {}, RuntimeError('database unavailable'))
        return original_commit(db)
    with monkeypatch.context() as patch:
        patch.setattr(Session, 'commit', fail_preparation)
        with pytest.raises(OperationalError):
            request(client)
    constructor.assert_not_called()
    with TestingSession() as db:
        assert db.get(OtpCadastro, EMAIL) is None


def test_database_commit_failure_after_smtp_acceptance_cannot_undo_otp(client, smtp, caplog):
    _, server, code = smtp
    state = {'accepted': False, 'failure_injected': False}
    def accepted(*args, **kwargs):
        # Independent connection proves the OTP is already durably committed.
        assert verify_secret('cadastro:' + code, pending()['code_hash'])
        state['accepted'] = True
        return {}
    server.send_message.side_effect = accepted
    def fail_later_commit(connection):
        if state['accepted'] and not state['failure_injected']:
            state['failure_injected'] = True
            raise OperationalError('simulated', {}, RuntimeError('database unavailable'))
    event.listen(engine, 'commit', fail_later_commit)
    try:
        with caplog.at_level(logging.INFO):
            assert request(client).status_code == 200
    finally:
        event.remove(engine, 'commit', fail_later_commit)
    assert state['failure_injected'] and 'outcome=lock_cleanup_failed' in caplog.text
    assert pending()['requests'] == 1
    assert verify(client, code).status_code == 201


def test_existing_account_never_starts_new_delivery(client, smtp):
    _, server, code = smtp
    request(client)
    assert verify(client, code).status_code == 201
    before = server.send_message.call_count
    response = request(client)
    assert response.status_code == 200 and server.send_message.call_count == before
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1


def test_concurrent_resends_after_failure_send_once_with_cooldown(client, smtp):
    _, server, _ = smtp
    fail_auth(server)
    request(client)
    server.login.side_effect = None
    barrier = Barrier(2)
    def resend(_):
        barrier.wait(timeout=10)
        return client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(resend, range(2))) == [200, 200]
    assert server.send_message.call_count == 1 and pending()['requests'] == 1


def test_refund_does_not_remove_other_rate_limit_reservations():
    first = otp_rate_limiter.reserve('isolated-refund-test', 2, 900)
    second = otp_rate_limiter.reserve('isolated-refund-test', 2, 900)
    assert first is not None and second is not None
    otp_rate_limiter.refund('isolated-refund-test', first)
    otp_rate_limiter.refund('isolated-refund-test', first)
    assert otp_rate_limiter.allow('isolated-refund-test', 2, 900)
    assert not otp_rate_limiter.allow('isolated-refund-test', 2, 900)


def test_failed_transport_attempt_limit_survives_worker_restart(client, smtp, caplog):
    _, server, _ = smtp
    fail_auth(server)
    for _ in range(env['OTP_RATE_LIMIT'] * 2):
        with otp_rate_limiter._lock:
            otp_rate_limiter._events.clear()
        assert request(client).status_code == 200
    with otp_rate_limiter._lock:
        otp_rate_limiter._events.clear()
    with caplog.at_level(logging.INFO):
        assert request(client).status_code == 429
    assert 'reason=persistent_attempt_limit' in caplog.text
    assert server.login.call_count == env['OTP_RATE_LIMIT'] * 2


def test_failed_delivery_does_not_reduce_original_shared_ip_send_quota(client, smtp):
    _, server, _ = smtp
    fail_auth(server)
    request(client)
    server.login.side_effect = None
    for number in range(env['OTP_RATE_LIMIT'] * 2):
        assert request(client, f'controlled{number}@example.com').status_code == 200
    assert server.send_message.call_count == env['OTP_RATE_LIMIT'] * 2
    assert request(client, 'over-ip-quota@example.com').status_code == 429


def test_read_transaction_cleanup_failure_after_acceptance_keeps_otp(client, smtp, monkeypatch, caplog):
    _, server, code = smtp
    state = {'accepted': False, 'failure_injected': False}
    def accepted(*args, **kwargs):
        state['accepted'] = True
        return {}
    server.send_message.side_effect = accepted
    original_rollback = Session.rollback
    def fail_cleanup(db):
        if state['accepted'] and not state['failure_injected']:
            state['failure_injected'] = True
            raise OperationalError('simulated', {}, RuntimeError('database unavailable'))
        return original_rollback(db)
    with monkeypatch.context() as patch:
        patch.setattr(Session, 'rollback', fail_cleanup)
        with caplog.at_level(logging.INFO):
            assert request(client).status_code == 200
    assert state['failure_injected']
    assert 'outcome=delivery_accepted reason=database_cleanup_failed' in caplog.text
    assert verify(client, code).status_code == 201


def test_refundable_budget_is_exact_even_when_clock_is_frozen(monkeypatch):
    from security import utcnow
    timestamp = utcnow()
    monkeypatch.setattr('security.utcnow', lambda: timestamp)
    first = otp_rate_limiter.reserve('frozen-clock', 2, 900)
    second = otp_rate_limiter.reserve('frozen-clock', 2, 900)
    assert first is not second
    otp_rate_limiter.refund('frozen-clock', first)
    otp_rate_limiter.refund('frozen-clock', first)
    assert otp_rate_limiter.allow('frozen-clock', 2, 900)
    assert not otp_rate_limiter.allow('frozen-clock', 2, 900)
