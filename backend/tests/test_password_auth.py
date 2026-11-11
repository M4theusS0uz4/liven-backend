from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import jwt
import pytest
from sqlalchemy import select

from config.config import env
from conftest import TestingSession
from models.orm import ContaGlobal, LimiteLogin, OtpCadastro, OtpDefinicaoSenha, OtpLoginGlobal, SessaoGlobal, Usuario
from security import hash_token, utcnow
from services.passwords import hash_password, verify_password

EMAIL = 'password@example.com'
PASSWORD = 'Correct-password-2026'


def request_signup(client, email=EMAIL, password=PASSWORD, path='register'):
    return client.post('/api/v1/auth/' + path + '/request-otp', json={'email': email, 'senha': password})


def confirm(client, code, password=PASSWORD, path='register'):
    return client.post('/api/v1/auth/' + path + '/verify-otp', json={'email': EMAIL, 'senha': password, 'codigo': code})


def signup(client):
    code = request_signup(client).json()['codigo_mock']
    response = confirm(client, code)
    assert response.status_code == 201
    return response.json()


def login(client, email=EMAIL, password=PASSWORD):
    return client.post('/api/v1/auth/login', json={'email': email, 'senha': password})


def headers(tokens):
    return {'Authorization': 'Bearer ' + tokens['access_token']}


def test_password_scrypt_random_salt_and_bounded_format():
    a, b = hash_password(PASSWORD), hash_password(PASSWORD)
    assert a != b and a.startswith('scrypt$32768$8$3$')
    assert PASSWORD not in a and verify_password(PASSWORD, a)
    assert not verify_password('incorrect', a)
    for value in ('invalid', 'scrypt$1$8$3$00$00', 'scrypt$32768$8$3$zz$zz'):
        assert not verify_password(PASSWORD, value)


@pytest.mark.parametrize('password', ['', '1234567', 'x' * 129])
def test_invalid_password_never_starts_signup(client, password):
    assert request_signup(client, password=password).status_code == 422
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == db.query(OtpCadastro).count() == 0


def test_pending_password_hash_no_login_before_email_confirmation(client):
    requested = request_signup(client, ' PASSWORD@EXAMPLE.COM ')
    with TestingSession() as db:
        pending = db.get(OtpCadastro, EMAIL)
        assert verify_password(PASSWORD, pending.password_hash)
        assert PASSWORD not in pending.password_hash
        assert db.query(ContaGlobal).count() == 0
    assert login(client).status_code == 401
    tokens = confirm(client, requested.json()['codigo_mock']).json()
    assert client.get('/api/v1/auth/global/me', headers=headers(tokens)).status_code == 200
    with TestingSession() as db:
        account = db.scalar(select(ContaGlobal))
        assert account.ativo and account.email_verificado_em
        assert verify_password(PASSWORD, account.password_hash)
        assert db.get(OtpCadastro, EMAIL).password_hash is None


def test_login_email_password_without_any_email_delivery(client, monkeypatch):
    signup(client)
    def forbidden(): raise AssertionError('Login não deve selecionar provedor de e-mail')
    monkeypatch.setattr('services.global_auth.get_otp_delivery', forbidden)
    response = login(client, ' PASSWORD@EXAMPLE.COM ')
    assert response.status_code == 200
    tokens = response.json()
    assert client.get('/api/v1/auth/global/me', headers=headers(tokens)).status_code == 200
    assert client.get('/api/v1/moradores', headers=headers(tokens)).status_code == 401
    claims = jwt.decode(tokens['access_token'], env['JWT_SECRET'], algorithms=['HS256'])
    assert claims['scope'] == 'global' and 'sid' in claims
    assert 'condominio_id' not in claims and 'perfil' not in claims
    with TestingSession() as db:
        assert db.query(OtpLoginGlobal).count() == 0
        assert db.query(Usuario).count() == 1


def test_wrong_unknown_inactive_and_no_password_have_same_public_error(client):
    tokens = signup(client)
    wrong = login(client, password='incorrect').json()
    assert login(client, email='unknown@example.com').json() == wrong
    with TestingSession() as db:
        db.get(ContaGlobal, tokens['conta']['id']).ativo = False
        db.commit()
    assert login(client).json() == wrong
    with TestingSession() as db:
        account = db.get(ContaGlobal, tokens['conta']['id'])
        account.ativo, account.password_hash = True, None
        db.commit()
    assert login(client).json() == wrong


def test_duplicate_does_not_replace_password_or_send_code(client, monkeypatch):
    tokens = signup(client)
    class NoDelivery:
        def deliver(self, **kwargs): raise AssertionError('Duplicate must not send')
    monkeypatch.setattr('services.global_auth.get_otp_delivery', lambda: NoDelivery())
    assert 'codigo_mock' not in request_signup(client, ' PASSWORD@EXAMPLE.COM ', 'Another-password').json()
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1
        assert verify_password(PASSWORD, db.get(ContaGlobal, tokens['conta']['id']).password_hash)


def test_password_is_bound_to_otp_preventing_registration_prehijacking(client):
    code = request_signup(client, password='Attacker-password').json()['codigo_mock']
    assert confirm(client, code).status_code == 401
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 0
        assert db.get(OtpCadastro, EMAIL).attempts == 1
    # Legitimate restart replaces BOTH password and OTP, subject to existing cooldown.
    code = request_signup(client).json()['codigo_mock']
    assert confirm(client, code).status_code == 201
    assert login(client, password='Attacker-password').status_code == 401
    assert login(client).status_code == 200


def test_resend_preserves_pending_password_and_cooldown(client, monkeypatch):
    request_signup(client)
    with TestingSession() as db:
        before = db.get(OtpCadastro, EMAIL).password_hash
    response = client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL})
    code = response.json()['codigo_mock']
    with TestingSession() as db:
        assert db.get(OtpCadastro, EMAIL).password_hash == before
    monkeypatch.setitem(env, 'OTP_RESEND_SECONDS', 60)
    assert 'codigo_mock' not in client.post('/api/v1/auth/register/resend-otp', json={'email': EMAIL}).json()
    assert confirm(client, code).status_code == 201


def test_expired_and_wrong_otp_never_assign_password(client):
    code = request_signup(client).json()['codigo_mock']
    with TestingSession() as db:
        db.get(OtpCadastro, EMAIL).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert confirm(client, code).status_code == 401
    assert login(client).status_code == 401


def test_logout_revokes_access_and_refresh_immediately(client):
    tokens = signup(client)
    assert client.post('/api/v1/auth/global/logout', json={'refresh_token': tokens['refresh_token']}, headers=headers(tokens)).status_code == 204
    assert client.get('/api/v1/auth/global/me', headers=headers(tokens)).status_code == 401
    assert client.post('/api/v1/auth/global/refresh', json={'refresh_token': tokens['refresh_token']}).status_code == 401
    assert client.post('/api/v1/auth/global/logout', json={'refresh_token': tokens['refresh_token']}, headers=headers(tokens)).status_code == 401


def test_common_refresh_and_logout_accept_password_session(client):
    tokens = signup(client)
    refreshed = client.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert refreshed.status_code == 200 and refreshed.json()['conta']['email'] == EMAIL
    new_tokens = refreshed.json()
    assert client.post('/api/v1/auth/logout', json={'refresh_token': new_tokens['refresh_token']}, headers=headers(new_tokens)).status_code == 204
    assert client.get('/api/v1/auth/global/me', headers=headers(new_tokens)).status_code == 401


def test_refresh_invalidates_previous_access_and_preserves_new_session(client):
    original = signup(client)
    rotated = client.post('/api/v1/auth/global/refresh', json={'refresh_token': original['refresh_token']}).json()
    assert client.get('/api/v1/auth/global/me', headers=headers(original)).status_code == 401
    assert client.get('/api/v1/auth/global/me', headers=headers(rotated)).status_code == 200


def test_password_login_limits_persist_across_workers(client, monkeypatch):
    monkeypatch.setitem(env, 'LOGIN_RATE_LIMIT', 2)
    for _ in range(2): assert login(client).status_code == 401
    from security import otp_rate_limiter
    with otp_rate_limiter._lock: otp_rate_limiter._events.clear()
    assert login(client).status_code == 429
    with TestingSession() as db:
        assert db.get(LimiteLogin, 'email:' + hash_token(EMAIL)).attempts == 2
        assert all(EMAIL not in row.key for row in db.scalars(select(LimiteLogin)))


def test_password_ip_limit_and_window_expiry(client, monkeypatch):
    monkeypatch.setitem(env, 'LOGIN_IP_RATE_LIMIT', 2)
    assert login(client, 'a@example.com').status_code == 401
    assert login(client, 'b@example.com').status_code == 401
    assert login(client, 'c@example.com').status_code == 429
    with TestingSession() as db:
        for row in db.scalars(select(LimiteLogin)):
            row.window_started_at = utcnow() - timedelta(seconds=env['LOGIN_RATE_WINDOW_SECONDS'] + 1)
        db.commit()
    assert login(client).status_code == 401


def test_initial_setup_for_verified_legacy_global_only(client):
    with TestingSession() as db:
        account = ContaGlobal(email=EMAIL, ativo=True, email_verificado_em=utcnow())
        db.add(account)
        db.commit()
        account_id = account.id
    assert login(client).status_code == 401
    code = request_signup(client, path='password/setup').json()['codigo_mock']
    assert confirm(client, code).status_code == 401  # Propósitos separados.
    response = confirm(client, code, path='password/setup')
    assert response.status_code == 200
    assert response.json()['conta']['id'] == account_id
    assert confirm(client, code, path='password/setup').status_code == 401
    assert login(client).status_code == 200
    assert 'codigo_mock' not in request_signup(client, path='password/setup').json()
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1
        assert db.get(OtpDefinicaoSenha, EMAIL).password_hash is None


def test_initial_setup_revokes_previous_sessions_and_old_otp_cannot_bypass(client):
    from services.global_auth import issue_global_tokens
    with TestingSession() as db:
        account = ContaGlobal(email=EMAIL, ativo=True, email_verificado_em=utcnow())
        db.add(account)
        db.flush()
        old = issue_global_tokens(account, db).model_dump()
        db.commit()
    legacy_code = client.post('/api/v1/auth/global/request-otp', json={'email': EMAIL}).json()['codigo_mock']
    setup_code = request_signup(client, path='password/setup').json()['codigo_mock']
    new = confirm(client, setup_code, path='password/setup').json()
    assert client.get('/api/v1/auth/global/me', headers=headers(old)).status_code == 401
    assert client.get('/api/v1/auth/global/me', headers=headers(new)).status_code == 200
    assert client.post('/api/v1/auth/global/verify-otp', json={'email': EMAIL, 'codigo': legacy_code}).status_code == 401


def test_signed_global_access_without_valid_owned_session_is_rejected(client):
    tokens = signup(client)
    payload = jwt.decode(tokens['access_token'], env['JWT_SECRET'], algorithms=['HS256'])
    for sid in (999999, True, '1', None):
        tampered = {**payload, 'sid': sid}
        encoded = jwt.encode(tampered, env['JWT_SECRET'], algorithm='HS256')
        assert client.get('/api/v1/auth/global/me', headers={'Authorization': 'Bearer ' + encoded}).status_code == 401
    payload.pop('sid')
    encoded = jwt.encode(payload, env['JWT_SECRET'], algorithm='HS256')
    assert client.get('/api/v1/auth/global/me', headers={'Authorization': 'Bearer ' + encoded}).status_code == 401


def test_wrong_password_consumes_otp_attempt_budget(client):
    code = request_signup(client).json()['codigo_mock']
    for _ in range(env['OTP_MAX_ATTEMPTS']):
        assert confirm(client, code, password='Incorrect-password').status_code == 401
    assert confirm(client, code).status_code == 401
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == db.query(SessaoGlobal).count() == 0


def test_setup_unknown_or_inactive_cannot_create_or_reactivate(client):
    assert 'codigo_mock' not in request_signup(client, path='password/setup').json()
    assert confirm(client, '123456', path='password/setup').status_code == 401
    with TestingSession() as db:
        db.add(ContaGlobal(email=EMAIL, ativo=False, email_verificado_em=utcnow()))
        db.commit()
    assert 'codigo_mock' not in request_signup(client, path='password/setup').json()


def test_legacy_endpoints_require_opt_in_and_cannot_bypass_password(client, monkeypatch):
    signup(client)
    for enabled in (False, True):
        monkeypatch.setitem(env, 'LEGACY_OTP_LOGIN_ENABLED', enabled)
        response = client.post('/api/v1/auth/global/request-otp', json={'email': EMAIL})
        assert response.status_code == (200 if enabled else 410)
        assert 'codigo_mock' not in response.json()
        verified = client.post('/api/v1/auth/global/verify-otp', json={'email': EMAIL, 'codigo': '123456'})
        assert verified.status_code == (401 if enabled else 410)
    assert client.post('/api/v1/auth/request-otp', json={'email': EMAIL, 'condominio_id': 1}).status_code == 200
    monkeypatch.setitem(env, 'LEGACY_OTP_LOGIN_ENABLED', False)
    assert client.post('/api/v1/auth/request-otp', json={'email': EMAIL, 'condominio_id': 1}).status_code == 410


def test_secrets_not_returned_in_validation_or_logs(client, caplog):
    password = 'Private-test-password-2026'
    response = request_signup(client, password=password)
    assert password not in response.text and password not in caplog.text
    bad = client.post('/api/v1/auth/login', json={'email': EMAIL, 'senha': password, 'perfil': 'sindico'})
    assert bad.status_code == 422 and password not in bad.text and password not in caplog.text


def test_concurrent_password_login_obeys_persistent_limit(client, monkeypatch):
    monkeypatch.setitem(env, 'LOGIN_RATE_LIMIT', 1)
    barrier = Barrier(3)
    def attempt(_):
        barrier.wait(timeout=10)
        return login(client).status_code
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(attempt, range(3))) == [401, 429, 429]
