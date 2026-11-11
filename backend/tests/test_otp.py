from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

from config.config import env
from conftest import TestingSession
from models.orm import Condominio, OtpChallenge, PerfilUsuario, RefreshToken, Usuario
from security import hash_token, otp_rate_limiter, utcnow, verify_secret

PHONE = "5511999999901"
EMAIL = "morador@example.com"


def account(condominio_id=None, ativo=True):
    with TestingSession() as db:
        if condominio_id is None:
            condominio_id = db.scalar(select(Condominio.id))
        user = Usuario(condominio_id=condominio_id, nome="Morador OTP", telefone=PHONE, email=EMAIL, perfil=PerfilUsuario.MORADOR, ativo=ativo)
        db.add(user)
        db.commit()
        return {"email": EMAIL, "condominio_id": condominio_id}, user.id


def request(client, payload):
    return client.post("/api/v1/auth/request-otp", json=payload)


def verify(client, payload, code):
    return client.post("/api/v1/auth/verify-otp", json={**payload, "codigo": code})


def challenge():
    with TestingSession() as db:
        return db.scalar(select(OtpChallenge).order_by(OtpChallenge.id.desc()))


def clear_process_limits():
    with otp_rate_limiter._lock:
        otp_rate_limiter._events.clear()


def test_solicitacao_hash_e_normalizacao(client):
    payload, user_id = account()
    response = request(client, {**payload, "email": "  MORADOR@EXAMPLE.COM  "})
    assert response.status_code == 200
    code = response.json()["codigo_mock"]
    assert len(code) == 6 and code.isascii() and code.isdigit()
    stored = challenge()
    assert stored.usuario_id == user_id and stored.email == EMAIL and stored.telefone is None
    assert stored.code_hash != code and verify_secret(code, stored.code_hash)
    assert stored.max_attempts == env["OTP_MAX_ATTEMPTS"]
    assert 290 < (stored.expires_at - utcnow()).total_seconds() <= 300


@pytest.mark.parametrize("inactive", [False, True])
def test_resposta_generica_sem_criar_usuario(client, inactive):
    payload = {"email": EMAIL, "condominio_id": 1}
    if inactive:
        payload, _ = account(ativo=False)
    with TestingSession() as db:
        before = db.query(Usuario).count()
    response = request(client, payload)
    assert response.status_code == 200
    assert response.json() == {"detail": "Se o e-mail estiver cadastrado, um código será enviado."}
    with TestingSession() as db:
        assert db.query(Usuario).count() == before
        assert db.query(OtpChallenge).count() == 0
    assert verify(client, payload, "123456").status_code == 401


@pytest.mark.parametrize("email", ["sem-arroba", "a@", "@example.com", "", "a b@example.com"])
def test_email_invalido(client, email):
    assert request(client, {"email": email, "condominio_id": 1}).status_code == 422


def test_codigo_correto_me_refresh_logout_e_reutilizacao(client):
    payload, user_id = account()
    code = request(client, payload).json()["codigo_mock"]
    result = verify(client, payload, code)
    assert result.status_code == 200
    tokens = result.json()
    assert set(tokens) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == env["ACCESS_TOKEN_MINUTES"] * 60
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/me", headers=headers).json()
    assert me["id"] == user_id and me["condominio_id"] == payload["condominio_id"] and me["perfil"] == "morador"
    assert challenge().used_at is not None
    assert verify(client, payload, code).status_code == 401
    with TestingSession() as db:
        assert db.scalar(select(RefreshToken.token_hash)) == hash_token(tokens["refresh_token"])
    renewed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert renewed.status_code == 200
    assert renewed.json()["refresh_token"] != tokens["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    refresh = renewed.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {renewed.json()['access_token']}"}
    assert client.post("/api/v1/auth/logout", json={"refresh_token": refresh}, headers=headers).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_codigo_incorreto_e_limite_tentativas(client):
    payload, _ = account()
    code = request(client, payload).json()["codigo_mock"]
    wrong = "000000" if code != "000000" else "999999"
    for _ in range(env["OTP_MAX_ATTEMPTS"]):
        assert verify(client, payload, wrong).status_code == 401
    assert challenge().attempts == env["OTP_MAX_ATTEMPTS"]
    assert verify(client, payload, code).status_code == 401
    with TestingSession() as db:
        assert db.query(RefreshToken).count() == 0


def test_expirado_e_usuario_desativado(client):
    payload, uid = account()
    code = request(client, payload).json()["codigo_mock"]
    with TestingSession() as db:
        db.get(OtpChallenge, challenge().id).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert verify(client, payload, code).status_code == 401
    code = request(client, payload).json()["codigo_mock"]
    with TestingSession() as db:
        db.get(Usuario, uid).ativo = False
        db.commit()
    assert verify(client, payload, code).status_code == 401


def test_reenvio_invalida_anterior(client, monkeypatch):
    payload, _ = account()
    values = iter([123456, 654321])
    monkeypatch.setattr("routers.auth.secrets.randbelow", lambda _: next(values))
    first = request(client, payload).json()["codigo_mock"]
    second = request(client, payload).json()["codigo_mock"]
    assert verify(client, payload, first).status_code == 401
    assert verify(client, payload, second).status_code == 200
    with TestingSession() as db:
        assert all(x.used_at is not None for x in db.scalars(select(OtpChallenge)))


def test_cooldown_e_limite_persistido(client, monkeypatch):
    payload, _ = account()
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 60)
    code = request(client, payload).json()["codigo_mock"]
    assert "codigo_mock" not in request(client, payload).json()
    assert verify(client, payload, code).status_code == 200
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 0)
    clear_process_limits()
    for _ in range(env["OTP_RATE_LIMIT"] - 1):
        assert "codigo_mock" in request(client, payload).json()
    clear_process_limits()  # Simula outro worker: o banco ainda limita.
    assert "codigo_mock" not in request(client, payload).json()
    with TestingSession() as db:
        assert db.query(OtpChallenge).count() == env["OTP_RATE_LIMIT"]


def test_limite_solicitacoes_por_contexto_e_ip(client):
    for _ in range(env["OTP_RATE_LIMIT"]):
        assert request(client, {"email": EMAIL, "condominio_id": 1}).status_code == 200
    assert request(client, {"email": EMAIL, "condominio_id": 1}).status_code == 429
    clear_process_limits()
    for i in range(env["OTP_RATE_LIMIT"] * 2):
        assert request(client, {"email": f"user{i}@example.com", "condominio_id": 1}).status_code == 200
    assert request(client, {"email": "other@example.com", "condominio_id": 1}).status_code == 429


def test_mesmo_email_em_dois_condominios(client, monkeypatch):
    first, _ = account()
    with TestingSession() as db:
        condo = Condominio(nome="Outro")
        db.add(condo)
        db.commit()
        second, _ = account(condo.id)
    values = iter([111111, 222222, 333333])
    monkeypatch.setattr("routers.auth.secrets.randbelow", lambda _: next(values))
    code_a = request(client, first).json()["codigo_mock"]
    code_b = request(client, second).json()["codigo_mock"]
    assert verify(client, second, code_a).status_code == 401
    request(client, first)  # Reenvio em A não invalida o desafio de B.
    assert verify(client, second, code_b).status_code == 200
    assert verify(client, first, code_a).status_code == 401


@pytest.mark.parametrize("app_env,mock", [("production", True), ("staging", True), ("development", False)])
def test_mock_somente_desenvolvimento(client, monkeypatch, app_env, mock):
    payload, _ = account()
    monkeypatch.setitem(env, "APP_ENV", app_env)
    monkeypatch.setitem(env, "MOCK_OTP", mock)
    for email in (EMAIL, "unknown@example.com"):
        response = request(client, {**payload, "email": email})
        assert response.status_code == 503 and "codigo_mock" not in response.json()
    assert challenge() is None


@pytest.mark.parametrize("app_env", ["production", "development"])
def test_login_fixo_bloqueado_e_perfil_inalterado(client, monkeypatch, app_env):
    payload, uid = account(ativo=False)
    monkeypatch.setitem(env, "APP_ENV", app_env)
    assert client.post("/api/v1/auth/login", json={**payload, "perfil": "sindico", "codigo": "123456"}).status_code == 422
    with TestingSession() as db:
        user = db.get(Usuario, uid)
        assert user.perfil == PerfilUsuario.MORADOR and not user.ativo


def test_perfil_do_navegador_rejeitado(client):
    payload, uid = account()
    assert request(client, {**payload, "perfil": "sindico"}).status_code == 422
    code = request(client, payload).json()["codigo_mock"]
    assert client.post("/api/v1/auth/verify-otp", json={**payload, "codigo": code, "perfil": "sindico"}).status_code == 422
    tokens = verify(client, payload, code).json()
    assert client.get("/api/v1/unidades", headers={"Authorization": f"Bearer {tokens['access_token']}", "X-User-Profile": "sindico"}).status_code == 403


def test_desafio_legado_nao_e_aceito(client):
    payload, _ = account()
    from security import hash_secret
    with TestingSession() as db:
        db.add(OtpChallenge(telefone=PHONE, code_hash=hash_secret("123456"), expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()
    assert verify(client, payload, "123456").status_code == 401


def parallel(actions):
    barrier = Barrier(len(actions))
    def run(action):
        barrier.wait(timeout=10)
        return action()
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def test_verificacoes_simultaneas_consumem_uma_vez(client):
    payload, _ = account()
    code = request(client, payload).json()["codigo_mock"]
    responses = parallel([lambda: verify(client, payload, code)] * 2)
    assert sorted(r.status_code for r in responses) == [200, 401]
    with TestingSession() as db:
        assert db.query(RefreshToken).count() == 1


def test_solicitacoes_simultaneas_respeitam_cooldown(client, monkeypatch):
    payload, _ = account()
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 60)
    responses = parallel([lambda: request(client, payload)] * 3)
    assert all(r.status_code == 200 for r in responses)
    assert sum("codigo_mock" in r.json() for r in responses) == 1
    with TestingSession() as db:
        assert db.query(OtpChallenge).count() == 1


def test_refresh_simultaneo_rotaciona_uma_vez(client):
    payload, _ = account()
    code = request(client, payload).json()["codigo_mock"]
    refresh = verify(client, payload, code).json()["refresh_token"]
    responses = parallel([lambda: client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})] * 2)
    assert sorted(r.status_code for r in responses) == [200, 401]


def test_falha_emissao_nao_consome_otp(client, monkeypatch):
    payload, _ = account()
    code = request(client, payload).json()["codigo_mock"]
    original = __import__("routers.auth", fromlist=["create_access_token"]).create_access_token
    def fail(_, session_id=None):
        raise RuntimeError("Falha simulada")
    monkeypatch.setattr("routers.auth.create_access_token", fail)
    with pytest.raises(RuntimeError):
        verify(client, payload, code)
    assert challenge().used_at is None
    monkeypatch.setattr("routers.auth.create_access_token", original)
    assert verify(client, payload, code).status_code == 200


def test_condominio_inativo(client):
    payload, _ = account()
    with TestingSession() as db:
        db.get(Condominio, payload["condominio_id"]).ativo = False
        db.commit()
    assert "codigo_mock" not in request(client, payload).json()
    assert verify(client, payload, "123456").status_code == 401


def test_refresh_inativo_e_expirado(client):
    payload, uid = account()
    code = request(client, payload).json()["codigo_mock"]
    refresh = verify(client, payload, code).json()["refresh_token"]
    with TestingSession() as db:
        db.get(Usuario, uid).ativo = False
        db.commit()
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    with TestingSession() as db:
        db.get(Usuario, uid).ativo = True
        db.scalar(select(RefreshToken)).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_logout_nao_revoga_sessao_de_outro_usuario(client):
    payload, _ = account()
    code = request(client, payload).json()["codigo_mock"]
    refresh = verify(client, payload, code).json()["refresh_token"]
    # Bearer padrão da fixture pertence ao síndico, não ao dono do refresh.
    assert client.post("/api/v1/auth/logout", json={"refresh_token": refresh}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 200


def test_codigo_nao_e_registrado_em_logs(client, caplog, monkeypatch):
    payload, _ = account()
    monkeypatch.setattr("routers.auth.secrets.randbelow", lambda _: 918273)
    with caplog.at_level("INFO"):
        result = request(client, payload)
    assert result.json()["codigo_mock"] == "918273"
    assert "918273" not in caplog.text
