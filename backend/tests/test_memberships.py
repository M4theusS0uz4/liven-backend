from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import jwt
import pytest
from sqlalchemy import select

from config.config import env
from conftest import TestingSession
from models.orm import Condominio, ContaGlobal, Morador, PerfilUsuario, Porteiro, SessaoGlobal, Unidade, Usuario
from services.passwords import hash_password

EMAIL = 'authorized@example.com'
PASSWORD = 'Authorized-password-2026'


def existing_user(profile='morador', condo_id=None, email=EMAIL):
    with TestingSession() as db:
        if condo_id is None:
            condo = Condominio(nome='Condomínio autorizado')
            db.add(condo)
            db.flush()
            condo_id = condo.id
        user = Usuario(email=email, nome='Usuário autorizado', telefone=f'551190000{condo_id:04d}',
                       perfil=profile, condominio_id=condo_id, ativo=True)
        db.add(user)
        db.flush()
        if profile == 'morador':
            unit = Unidade(condominio_id=condo_id, bloco=f'LINK-{condo_id}', numero='1')
            db.add(unit)
            db.flush()
            db.add(Morador(usuario_id=user.id, unidade_id=unit.id, nome=user.nome, ativo=True))
        elif profile == 'portaria':
            db.add(Porteiro(usuario_id=user.id, ativo=True))
        db.commit()
        return user.id, condo_id


def global_account():
    with TestingSession() as db:
        account = ContaGlobal(email=EMAIL, ativo=True, email_verificado_em=__import__('security').utcnow(), password_hash=hash_password(PASSWORD))
        db.add(account)
        db.commit()
        return account.id


def login(client):
    result = client.post('/api/v1/auth/login', json={'email': ' AUTHORIZED@EXAMPLE.COM ', 'senha': PASSWORD})
    assert result.status_code == 200
    return result.json()


def auth(tokens):
    return {'Authorization': 'Bearer ' + tokens['access_token']}


def choose(client, tokens, user_id):
    return client.post('/api/v1/auth/global/select-condominio', json={'usuario_id': user_id}, headers=auth(tokens))


@pytest.mark.parametrize('profile', ['morador', 'portaria', 'sindico'])
def test_existing_authorized_user_restored_without_creating_or_changing_links(client, profile):
    user_id, condo_id = existing_user(profile)
    global_account()
    with TestingSession() as db:
        before = (db.query(Usuario).count(), db.query(Morador).count(), db.query(Unidade).count(), db.query(Porteiro).count())
    tokens = login(client)
    assert tokens['scope'] == 'condominio'
    assert tokens['usuario']['id'] == user_id and tokens['usuario']['perfil'] == profile
    assert tokens['usuario']['condominio_id'] == condo_id != 1
    assert tokens['vinculos'][0]['usuario_id'] == user_id
    me = client.get('/api/v1/me', headers=auth(tokens))
    assert me.status_code == 200 and me.json() == tokens['usuario']
    assert client.get('/api/v1/dashboard/sindico', headers=auth(tokens)).status_code == (200 if profile == 'sindico' else 403)
    assert client.get('/api/v1/porteiros', headers=auth(tokens)).status_code == (200 if profile in ('sindico', 'portaria') else 403)
    assert client.get('/api/v1/comunicados', headers=auth(tokens)).status_code == 200
    with TestingSession() as db:
        assert before == (db.query(Usuario).count(), db.query(Morador).count(), db.query(Unidade).count(), db.query(Porteiro).count())
        assert db.scalar(select(SessaoGlobal.usuario_id)) == user_id


def test_verified_registration_enters_original_app_for_existing_authorized_email(client):
    user_id, _ = existing_user()
    requested = client.post('/api/v1/auth/register/request-otp', json={'email': EMAIL, 'senha': PASSWORD})
    assert requested.status_code == 200
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 0
    result = client.post('/api/v1/auth/register/verify-otp', json={'email': EMAIL, 'senha': PASSWORD, 'codigo': requested.json()['codigo_mock']})
    assert result.status_code == 201
    assert result.json()['scope'] == 'condominio' and result.json()['usuario']['id'] == user_id
    assert client.get('/api/v1/me', headers=auth(result.json())).status_code == 200


def test_unknown_account_and_unlinked_resident_email_never_grant_access(client):
    global_account()
    with TestingSession() as db:
        unit = Unidade(condominio_id=1, bloco='UNLINKED', numero='1')
        db.add(unit)
        db.flush()
        db.add(Morador(email=EMAIL, nome='Morador sem conta autorizada', unidade_id=unit.id))
        db.commit()
    tokens = login(client)
    assert tokens['scope'] == 'global' and tokens['usuario'] is None and tokens['vinculos'] == []
    assert client.get('/api/v1/me', headers=auth(tokens)).status_code == 401
    assert client.get('/api/v1/dashboard/sindico', headers=auth(tokens)).status_code == 401
    assert client.get('/api/v1/auth/global/condominios', headers=auth(tokens)).json() == []
    assert choose(client, tokens, 1).status_code == 403
    with TestingSession() as db:
        assert db.query(Usuario).count() == 1
        assert db.scalar(select(Morador.usuario_id)) is None


def test_multiple_memberships_require_selection_and_keep_tenant_filters(client):
    first, first_condo = existing_user('sindico')
    second, second_condo = existing_user('sindico')
    global_account()
    with TestingSession() as db:
        db.add_all([Unidade(condominio_id=first_condo, bloco='FIRST', numero='1'),
                    Unidade(condominio_id=second_condo, bloco='SECOND', numero='2')])
        db.commit()
    tokens = login(client)
    assert tokens['scope'] == 'global' and tokens['usuario'] is None
    assert {item['usuario_id'] for item in tokens['vinculos']} == {first, second}
    assert client.get('/api/v1/unidades', headers=auth(tokens)).status_code == 401
    chosen = choose(client, tokens, second)
    assert chosen.status_code == 200
    selected = chosen.json()
    assert selected['usuario']['condominio_id'] == second_condo
    units = client.get('/api/v1/unidades', headers=auth(selected)).json()
    assert [item['bloco'] for item in units] == ['SECOND']
    assert client.get('/api/v1/dashboard/sindico', headers=auth(selected)).json()['total_unidades'] == 1
    assert client.get('/api/v1/auth/global/me', headers=auth(tokens)).status_code == 401
    assert choose(client, tokens, first).status_code == 401
    switched = choose(client, selected, first)
    assert switched.status_code == 200
    assert [item['bloco'] for item in client.get('/api/v1/unidades', headers=auth(switched.json())).json()] == ['FIRST']


def test_unowned_context_selection_and_client_role_injection_are_rejected(client):
    authorized, _ = existing_user()
    stranger, _ = existing_user('sindico', email='other@example.com')
    global_account()
    tokens = login(client)
    assert choose(client, tokens, stranger).status_code == 403
    assert client.post('/api/v1/auth/global/select-condominio', json={'usuario_id': authorized, 'perfil': 'sindico', 'condominio_id': 1}, headers=auth(tokens)).status_code == 422
    assert client.get('/api/v1/dashboard/sindico', headers={**auth(tokens), 'X-User-Profile': 'sindico'}).status_code == 403


@pytest.mark.parametrize('kind', ['user', 'condo', 'resident', 'unit', 'email', 'unit_other_condo'])
def test_revoked_or_inconsistent_link_is_denied_and_refresh_downgrades_without_switching(client, kind):
    user_id, _ = existing_user()
    global_account()
    tokens = login(client)
    with TestingSession() as db:
        user = db.get(Usuario, user_id)
        if kind == 'user': user.ativo = False
        elif kind == 'condo': user.condominio.ativo = False
        elif kind == 'resident': user.morador.ativo = False
        elif kind == 'unit': user.morador.unidade.ativa = False
        elif kind == 'email': user.email = 'changed@example.com'
        else: user.morador.unidade.condominio_id = 1
        db.commit()
    assert client.get('/api/v1/me', headers=auth(tokens)).status_code == 401
    renewed = client.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert renewed.status_code == 200
    assert renewed.json()['scope'] == 'global' and renewed.json()['usuario'] is None
    assert client.get('/api/v1/me', headers=auth(renewed.json())).status_code == 401


def test_disabled_gatekeeper_not_recovered_from_user_active_alone(client):
    user_id, _ = existing_user('portaria')
    global_account()
    with TestingSession() as db:
        db.get(Usuario, user_id).porteiro.ativo = False
        db.commit()
    assert login(client)['scope'] == 'global'


def test_refresh_and_logout_preserve_then_revoke_tenant_context(client):
    user_id, _ = existing_user('sindico')
    global_account()
    tokens = login(client)
    renewed = client.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert renewed.status_code == 200
    new = renewed.json()
    assert new['usuario']['id'] == user_id and new['scope'] == 'condominio'
    assert client.get('/api/v1/me', headers=auth(new)).status_code == 200
    assert client.get('/api/v1/me', headers=auth(tokens)).status_code == 401
    assert client.post('/api/v1/auth/logout', json={'refresh_token': new['refresh_token']}, headers=auth(new)).status_code == 204
    assert client.get('/api/v1/me', headers=auth(new)).status_code == 401
    assert client.post('/api/v1/auth/refresh', json={'refresh_token': new['refresh_token']}).status_code == 401


def test_signed_claims_must_match_context_persisted_by_server(client):
    user_id, _ = existing_user()
    stranger, stranger_condo = existing_user('sindico', email='stranger@example.com')
    global_account()
    tokens = login(client)
    payload = jwt.decode(tokens['access_token'], env['JWT_SECRET'], algorithms=['HS256'])
    for override in ({'usuario_id': stranger}, {'condominio_id': stranger_condo}, {'perfil': 'sindico'}, {'scope': 'global'}):
        forged = jwt.encode({**payload, **override}, env['JWT_SECRET'], algorithm='HS256')
        assert client.get('/api/v1/me', headers={'Authorization': 'Bearer ' + forged}).status_code == 401
    assert tokens['usuario']['id'] == user_id


def test_concurrent_context_selection_consumes_original_session_once(client):
    first, _ = existing_user()
    second, _ = existing_user('sindico')
    global_account()
    tokens = login(client)
    barrier = Barrier(2)
    def attempt(user_id):
        barrier.wait(timeout=10)
        return choose(client, tokens, user_id).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [first, second])) == [200, 401]


def test_existing_global_session_not_silently_upgraded_during_refresh(client):
    global_account()
    tokens = login(client)
    user_id, _ = existing_user()
    refreshed = client.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']}).json()
    assert refreshed['scope'] == 'global' and refreshed['usuario'] is None
    assert refreshed['vinculos'][0]['usuario_id'] == user_id
    assert choose(client, refreshed, user_id).status_code == 200
