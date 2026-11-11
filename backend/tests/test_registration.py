from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import jwt
import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.config import env
from config.database import engine
from conftest import TestingSession
from models.orm import ContaGlobal, Condominio, Morador, OtpCadastro, OtpChallenge, OtpLoginGlobal, SessaoGlobal, Unidade, Usuario
from security import hash_secret, hash_token, otp_rate_limiter, utcnow, verify_secret
from services.otp_delivery import OtpDeliveryError

EMAIL = "new@example.com"
PASSWORD = "Strong-test-password-2026"


def request(client, email=EMAIL, kind="register", **extra):
    return client.post(f"/api/v1/auth/{kind}/request-otp", json={"email": email, **({"senha": PASSWORD} if kind == "register" else {}), **extra})


def verify(client, code, email=EMAIL, kind="register", **extra):
    return client.post(f"/api/v1/auth/{kind}/verify-otp", json={"email": email, "codigo": code, **({"senha": PASSWORD} if kind == "register" else {}), **extra})


def register(client, email=EMAIL):
    code = request(client, email).json()["codigo_mock"]
    response = verify(client, code, email)
    assert response.status_code == 201
    return response.json()


def clear_limits():
    with otp_rate_limiter._lock:
        otp_rate_limiter._events.clear()


def parallel(actions):
    barrier = Barrier(len(actions))
    def run(action):
        barrier.wait(timeout=10)
        return action()
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def test_email_apenas_sem_conta_antes_de_confirmar(client):
    with TestingSession() as db:
        baseline = tuple(db.query(model).count() for model in (Usuario, Morador, Unidade, Condominio))
    response = request(client, " NEW@EXAMPLE.COM ")
    assert response.status_code == 200
    code = response.json()["codigo_mock"]
    assert len(code) == 6 and code.isascii() and code.isdigit()
    with TestingSession() as db:
        otp = db.get(OtpCadastro, EMAIL)
        assert otp.code_hash != code and verify_secret("cadastro:" + code, otp.code_hash)
        assert not verify_secret(code, otp.code_hash)
        assert db.query(ContaGlobal).count() == 0
        assert db.query(OtpChallenge).count() == 0
    result = verify(client, code)
    assert result.status_code == 201
    data = result.json()
    assert data["conta"]["email"] == EMAIL and data["conta"]["ativo"] is True
    assert data["conta"]["email_verificado_em"]
    assert "perfil" not in data["conta"] and "condominio_id" not in data["conta"]
    assert "telefone" not in data["conta"] and "nome" not in data["conta"]
    with TestingSession() as db:
        assert tuple(db.query(model).count() for model in (Usuario, Morador, Unidade, Condominio)) == baseline
        assert db.get(OtpCadastro, EMAIL).used_at is not None
        assert db.query(ContaGlobal).count() == 1
        assert db.scalar(select(SessaoGlobal.token_hash)) == hash_token(data["refresh_token"])


def test_cadastro_autentica_sem_segundo_otp_e_sem_vinculo(client):
    code = request(client).json()["codigo_mock"]
    response = verify(client, code)
    assert response.status_code == 201
    tokens = response.json()
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    me = client.get("/api/v1/auth/global/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == tokens["conta"]["id"]
    assert "condominio_id" not in me.json() and "perfil" not in me.json()
    assert client.get("/api/v1/moradores", headers=headers).status_code == 401
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    renewed = client.post("/api/v1/auth/global/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert renewed.status_code == 200
    assert client.get("/api/v1/auth/global/me", headers={"Authorization": "Bearer " + renewed.json()["access_token"]}).status_code == 200
    assert verify(client, code).status_code == 401
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1
        assert db.query(OtpLoginGlobal).count() == 0
        assert db.query(Morador).count() == db.query(Unidade).count() == 0


@pytest.mark.parametrize("email", ["", "invalid", "a@", "@example.com", "a b@example.com"])
def test_email_invalido(client, email):
    assert request(client, email).status_code == 422
    assert verify(client, "123456", email).status_code == 422


@pytest.mark.parametrize("extra", [{"perfil": "sindico"}, {"condominio_id": 1}, {"telefone": "5511999999999"}, {"nome": "Injected"}, {"ativo": True}])
def test_nao_aceita_perfis_vinculos_ou_outros_campos(client, extra):
    assert request(client, **extra).status_code == 422
    assert verify(client, "123456", **extra).status_code == 422


def test_sem_codigo_valido_nao_cria_conta(client):
    assert verify(client, "123456").status_code == 401
    code = request(client).json()["codigo_mock"]
    wrong = "000000" if code != "000000" else "999999"
    for _ in range(env["OTP_MAX_ATTEMPTS"]):
        assert verify(client, wrong).status_code == 401
    assert verify(client, code).status_code == 401
    with TestingSession() as db:
        assert db.get(OtpCadastro, EMAIL).attempts == env["OTP_MAX_ATTEMPTS"]
        assert db.query(ContaGlobal).count() == 0
        assert db.query(SessaoGlobal).count() == 0
    assert request(client, kind="global").status_code == 200
    assert verify(client, code, kind="global").status_code == 401


def test_expiracao_e_reutilizacao(client):
    code = request(client).json()["codigo_mock"]
    with TestingSession() as db:
        db.get(OtpCadastro, EMAIL).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert verify(client, code).status_code == 401
    code = request(client).json()["codigo_mock"]
    assert verify(client, code).status_code == 201
    assert verify(client, code).status_code == 401


def test_reenvio_substitui_codigo(client, monkeypatch):
    numbers = iter([111111, 222222])
    monkeypatch.setattr("services.global_auth.secrets.randbelow", lambda _: next(numbers))
    old = request(client).json()["codigo_mock"]
    new = request(client).json()["codigo_mock"]
    assert verify(client, old).status_code == 401
    assert verify(client, new).status_code == 201


def test_cooldown_e_limite_persistido_entre_workers(client, monkeypatch):
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 60)
    code = request(client).json()["codigo_mock"]
    assert "codigo_mock" not in request(client).json()
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 0)
    clear_limits()
    for _ in range(env["OTP_RATE_LIMIT"] - 1):
        assert "codigo_mock" in request(client).json()
    clear_limits()
    assert "codigo_mock" not in request(client).json()
    with TestingSession() as db:
        assert db.get(OtpCadastro, EMAIL).requests == env["OTP_RATE_LIMIT"]


def test_rate_limit_por_email_e_ip(client):
    for _ in range(env["OTP_RATE_LIMIT"]):
        assert request(client).status_code == 200
    assert request(client).status_code == 429
    clear_limits()
    for i in range(env["OTP_RATE_LIMIT"] * 2):
        assert request(client, f"person{i}@example.com").status_code == 200
    assert request(client, "last@example.com").status_code == 429


def test_falha_entrega_preserva_anterior_e_contabiliza_limite(client, monkeypatch, caplog):
    code = request(client).json()["codigo_mock"]
    class Broken:
        def deliver(self, **kwargs): raise OtpDeliveryError("PRIVATE")
    monkeypatch.setattr("services.global_auth.get_otp_delivery", lambda: Broken())
    response = request(client)
    assert response.status_code == 200 and "codigo_mock" not in response.json()
    assert "PRIVATE" not in caplog.text and code not in caplog.text
    with TestingSession() as db:
        otp = db.get(OtpCadastro, EMAIL)
        assert otp.requests == 2 and verify_secret("cadastro:" + code, otp.code_hash)
        assert db.query(ContaGlobal).count() == 0
    assert verify(client, code).status_code == 201


def test_jwt_global_sem_permissoes_ou_claims_de_condominio(client):
    data = register(client)
    payload = jwt.decode(data["access_token"], env["JWT_SECRET"], algorithms=["HS256"])
    assert payload["scope"] == "global" and payload["sub"].startswith("global:")
    assert "perfil" not in payload and "condominio_id" not in payload
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/v1/auth/global/me", headers=headers).status_code == 200
    # Inclui rotas sem require_profiles que não podem depender só de filtros de condomínio.
    paths = ["/me", "/unidades", "/moradores", "/entregas", "/veiculos", "/condominio/mapa", "/visitantes", "/acessos/historico", "/porteiros", "/comunicados", "/ocorrencias", "/dashboard/sindico", "/auditoria"]
    for path in paths:
        assert client.get("/api/v1" + path, headers=headers).status_code == 401, path
    for path in ["/unidades", "/moradores", "/visitantes", "/veiculos", "/entregas"]:
        assert client.post("/api/v1" + path, headers=headers, json={}).status_code == 401, path
    # Endpoint comum reconhece o tipo da sessão sem converter escopo/permissões.
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert refreshed.status_code == 200 and "condominio_id" not in refreshed.json()["conta"]


def test_token_condominio_nao_acessa_conta_global(client):
    assert client.get("/api/v1/auth/global/me").status_code == 401
    assert client.get("/api/v1/auth/global/me", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_login_global_separado_do_cadastro_e_login_condominio(client, monkeypatch):
    data = register(client)
    # Compatibilidade explicitamente autorizada só para conta antiga sem senha.
    with TestingSession() as db:
        db.get(ContaGlobal, data["conta"]["id"]).password_hash = None
        db.commit()
    numbers = iter([654321])
    monkeypatch.setattr("services.global_auth.secrets.randbelow", lambda _: next(numbers))
    assert "codigo_mock" not in request(client).json()
    reg_code = "123456"
    login_code = request(client, kind="global").json()["codigo_mock"]
    assert verify(client, reg_code, kind="global").status_code == 401
    assert verify(client, login_code).status_code == 401
    result = verify(client, login_code, kind="global")
    assert result.status_code == 200 and result.json()["conta"]["id"] == data["conta"]["id"]
    assert verify(client, login_code, kind="global").status_code == 401
    assert client.post("/api/v1/auth/verify-otp", json={"email": EMAIL, "condominio_id": 1, "codigo": reg_code}).status_code == 401
    assert verify(client, reg_code).status_code == 401  # Não substitui conta existente.
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1 and db.query(Usuario).count() == 1


def test_email_ja_existente_tem_resposta_publica_igual_sem_reativacao(client, monkeypatch):
    data = register(client)
    with TestingSession() as db:
        db.get(ContaGlobal, data["conta"]["id"]).ativo = False
        db.commit()
    # Modo real não inclui codigo_mock em nenhuma resposta pública.
    monkeypatch.setitem(env, "MOCK_OTP", False)
    class Delivery:
        def deliver(self, **kwargs): return None
    monkeypatch.setattr("services.global_auth.get_otp_delivery", lambda: Delivery())
    existing = request(client)
    unknown = request(client, "other@example.com")
    assert existing.status_code == unknown.status_code == 200
    assert existing.json()["detail"] == unknown.json()["detail"]
    assert set(existing.json()) == set(unknown.json())
    assert verify(client, "123456").status_code == 401
    assert verify(client, "123456", kind="global").status_code == 401
    assert client.get("/api/v1/auth/global/me", headers={"Authorization": f"Bearer {data['access_token']}"}).status_code == 401
    with TestingSession() as db:
        assert not db.get(ContaGlobal, data["conta"]["id"]).ativo


def test_global_com_mesmo_email_nao_vincula_usuario_existente(client):
    from test_otp import account
    tenant_payload, user_id = account()
    data = register(client, tenant_payload["email"])
    assert data["conta"]["email"] == tenant_payload["email"]
    with TestingSession() as db:
        assert db.get(Usuario, user_id).perfil == "morador"
        assert db.get(Usuario, user_id).condominio_id == 1
        assert db.query(Morador).count() == 0


def test_refresh_logout_e_escopos_isolados(client):
    data = register(client)
    renewed = client.post("/api/v1/auth/global/refresh", json={"refresh_token": data["refresh_token"]})
    assert renewed.status_code == 200
    assert client.post("/api/v1/auth/global/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401
    current = renewed.json()
    assert current["refresh_token"] != data["refresh_token"]
    assert client.post("/api/v1/auth/global/logout", json={"refresh_token": current["refresh_token"]}, headers={"Authorization": f"Bearer {current['access_token']}"}).status_code == 204
    assert client.post("/api/v1/auth/global/refresh", json={"refresh_token": current["refresh_token"]}).status_code == 401


def test_cadastro_concorrente_cria_so_uma_conta(client):
    code = request(client).json()["codigo_mock"]
    results = parallel([lambda: verify(client, code)] * 2)
    assert sorted(r.status_code for r in results) == [201, 401]
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1 and db.query(SessaoGlobal).count() == 1


def test_primeira_solicitacao_concorrente_respeita_cooldown(client, monkeypatch):
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 60)
    results = parallel([lambda: request(client)] * 3)
    assert all(r.status_code == 200 for r in results)
    assert sum("codigo_mock" in r.json() for r in results) == 1
    with TestingSession() as db:
        assert db.query(OtpCadastro).count() == 1 and db.get(OtpCadastro, EMAIL).requests == 1


def test_refresh_concorrente_consumido_uma_vez(client):
    data = register(client)
    results = parallel([lambda: client.post("/api/v1/auth/global/refresh", json={"refresh_token": data["refresh_token"]})] * 2)
    assert sorted(r.status_code for r in results) == [200, 401]


def test_falha_emissao_jwt_reverte_criacao_e_consumo(client, monkeypatch):
    code = request(client).json()["codigo_mock"]
    def fail(*args, **kwargs): raise RuntimeError("Simulated")
    monkeypatch.setattr("services.global_auth.issue_global_tokens", fail)
    with pytest.raises(RuntimeError): verify(client, code)
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 0
        assert db.get(OtpCadastro, EMAIL).used_at is None


def test_producao_mock_bloqueado_e_provedor_simulado_sem_expor_codigo(client, monkeypatch):
    monkeypatch.setitem(env, "APP_ENV", "production")
    assert request(client).status_code == 503
    class Fake:
        def deliver(self, **kwargs): return "123456"
    monkeypatch.setattr("services.global_auth.get_otp_delivery", lambda: Fake())
    result = request(client)
    assert result.status_code == 200 and "codigo_mock" not in result.json()


def test_codigo_nao_aparece_nos_logs(client, monkeypatch, caplog):
    monkeypatch.setattr("services.global_auth.secrets.randbelow", lambda _: 918273)
    response = request(client)
    assert response.json()["codigo_mock"] == "918273"
    assert "918273" not in caplog.text


def test_email_global_unico_e_conta_exige_verificacao():
    with TestingSession() as db:
        db.add(ContaGlobal(email=EMAIL, ativo=True))
        with pytest.raises(IntegrityError): db.commit()
    with TestingSession() as db:
        db.add_all([ContaGlobal(email=EMAIL, ativo=True, email_verificado_em=utcnow()), ContaGlobal(email=EMAIL, ativo=True, email_verificado_em=utcnow())])
        with pytest.raises(IntegrityError): db.commit()


def test_otp_login_existente_e_cadastro_nao_se_consumem(client, monkeypatch):
    from test_otp import account
    tenant, _ = account()
    monkeypatch.setattr("routers.auth.secrets.randbelow", lambda _: 111111)
    tenant_requested = client.post("/api/v1/auth/request-otp", json=tenant)
    assert tenant_requested.status_code == 200
    monkeypatch.setattr("services.global_auth.secrets.randbelow", lambda _: 222222)
    requested = request(client, tenant["email"])
    assert verify(client, "111111", tenant["email"]).status_code == 401
    assert client.post("/api/v1/auth/verify-otp", json={**tenant, "codigo": "222222"}).status_code == 401
    assert verify(client, requested.json()["codigo_mock"], tenant["email"]).status_code == 201
    assert client.post("/api/v1/auth/verify-otp", json={**tenant, "codigo": tenant_requested.json()["codigo_mock"]}).status_code == 200


def test_cadastro_utiliza_smtp_mockado_sem_retornar_codigo(client, monkeypatch):
    from test_smtp_delivery import configure, transport
    configure(monkeypatch)
    _, server = transport(monkeypatch)
    monkeypatch.setattr("services.global_auth.secrets.randbelow", lambda _: 603219)
    result = request(client)
    assert result.status_code == 200 and "codigo_mock" not in result.json()
    assert server.send_message.call_args.kwargs["to_addrs"] == [EMAIL]
    assert verify(client, "603219").status_code == 201


def test_token_global_expirado_refresh_expirado_e_desativacao(client):
    data = register(client)
    payload = jwt.decode(data["access_token"], env["JWT_SECRET"], algorithms=["HS256"])
    payload["exp"] = utcnow() - timedelta(seconds=1)
    expired = jwt.encode(payload, env["JWT_SECRET"], algorithm="HS256")
    assert client.get("/api/v1/auth/global/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    with TestingSession() as db:
        db.scalar(select(SessaoGlobal)).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post("/api/v1/auth/global/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401
    with TestingSession() as db:
        db.get(ContaGlobal, data["conta"]["id"]).ativo = False
        db.commit()
    assert client.get("/api/v1/auth/global/me", headers={"Authorization": f"Bearer {data['access_token']}"}).status_code == 401
    assert "codigo_mock" not in request(client, kind="global").json()


def test_logout_global_nao_revoga_outra_conta(client):
    first = register(client)
    second = register(client, "another@example.com")
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    assert client.post("/api/v1/auth/global/logout", headers=headers, json={"refresh_token": second["refresh_token"]}).status_code == 204
    assert client.post("/api/v1/auth/global/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 200


@pytest.mark.parametrize("active", [True, False])
def test_email_cadastrado_nao_gera_nem_envia_otp(client, monkeypatch, active):
    data = register(client)
    with TestingSession() as db:
        db.get(ContaGlobal, data["conta"]["id"]).ativo = active
        previous = db.get(OtpCadastro, EMAIL).code_hash
        db.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError("Conta existente não deve gerar nem receber OTP de cadastro")
    monkeypatch.setattr("services.global_auth.secrets.randbelow", forbidden)
    class NoDelivery:
        deliver = forbidden
    monkeypatch.setattr("services.global_auth.get_otp_delivery", lambda: NoDelivery())
    assert request(client, " NEW@EXAMPLE.COM ").json() == {"detail": "Se a solicitação puder ser atendida, um código será enviado."}
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1
        assert db.get(OtpCadastro, EMAIL).code_hash == previous
        assert db.get(ContaGlobal, data["conta"]["id"]).ativo == active


def test_pendente_normalizado_reutiliza_desafio_e_preserva_tentativas_no_cooldown(client, monkeypatch):
    monkeypatch.setitem(env, "OTP_RESEND_SECONDS", 60)
    code = request(client, " NEW@EXAMPLE.COM ").json()["codigo_mock"]
    wrong = "000000" if code != "000000" else "999999"
    assert verify(client, wrong, "New@Example.COM").status_code == 401
    assert "codigo_mock" not in request(client, "new@EXAMPLE.com").json()
    with TestingSession() as db:
        challenge = db.get(OtpCadastro, EMAIL)
        assert db.query(OtpCadastro).count() == 1
        assert challenge.attempts == 1 and challenge.requests == 1
        assert db.query(ContaGlobal).count() == 0
    assert verify(client, code, " NEW@example.COM ").status_code == 201


def test_confirmacao_concorrente_variantes_email_cria_uma_conta(client):
    code = request(client).json()["codigo_mock"]
    results = parallel([lambda: verify(client, code, " NEW@EXAMPLE.COM "), lambda: verify(client, code, EMAIL)])
    assert sorted(result.status_code for result in results) == [201, 401]
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == db.query(SessaoGlobal).count() == 1


def test_constraint_banco_impede_inserts_concorrentes_sem_endpoint(client):
    def direct_insert():
        with TestingSession() as db:
            db.add(ContaGlobal(email=EMAIL, ativo=True, email_verificado_em=utcnow()))
            try:
                db.commit()
                return "created"
            except IntegrityError as exc:
                db.rollback()
                assert exc.orig.diag.constraint_name == "uq_contas_globais_email"
                return "duplicate"
    assert sorted(parallel([direct_insert, direct_insert])) == ["created", "duplicate"]


@pytest.mark.parametrize("email", ["NEW@example.com", " new@example.com "])
def test_banco_rejeita_email_global_nao_canonico(email):
    with TestingSession() as db:
        db.add(ContaGlobal(email=email, ativo=True, email_verificado_em=utcnow()))
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert error.value.orig.diag.constraint_name == "ck_contas_globais_email_normalizado"


def test_conflito_com_escritor_externo_retorna_401_sem_sobrescrever(client, monkeypatch):
    code = request(client).json()["codigo_mock"]
    original_flush = Session.flush
    injected = False
    def flush_with_external_insert(db, *args, **kwargs):
        nonlocal injected
        if not injected and any(isinstance(obj, ContaGlobal) for obj in db.new):
            injected = True
            with engine.begin() as connection:
                connection.execute(insert(ContaGlobal).values(email=EMAIL, ativo=False, email_verificado_em=utcnow()))
        return original_flush(db, *args, **kwargs)
    monkeypatch.setattr(Session, "flush", flush_with_external_insert)
    assert verify(client, code).status_code == 401
    assert injected
    with TestingSession() as db:
        assert db.query(ContaGlobal).count() == 1
        assert not db.scalar(select(ContaGlobal)).ativo
        assert db.query(SessaoGlobal).count() == 0
        assert db.get(OtpCadastro, EMAIL).used_at is None
