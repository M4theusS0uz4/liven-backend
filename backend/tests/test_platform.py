from models.orm import Condominio, Morador, PerfilUsuario, Usuario, Unidade


def seed_user():
    from conftest import TestingSession

    with TestingSession() as db:
        condominio = db.query(Condominio).first()
        unidade = Unidade(condominio_id=condominio.id, bloco="A", numero="101", andar=1)
        db.add(unidade)
        db.flush()
        user = Usuario(condominio_id=condominio.id, nome="Ana Souza", telefone="5511999999999", perfil=PerfilUsuario.MORADOR)
        db.add(user)
        db.flush()
        db.add(Morador(unidade_id=unidade.id, usuario_id=user.id, nome="Ana Souza", telefone="5511999999999"))
        db.commit()
        return condominio.id


def test_otp_temporario_e_me(client):
    condominio_id = seed_user()
    solicitado = client.post("/api/v1/auth/request-otp", json={"telefone": "+55 (11) 99999-9999", "condominio_id": condominio_id})
    assert solicitado.status_code == 200
    codigo = solicitado.json()["codigo_mock"]
    login = client.post("/api/v1/auth/verify-otp", json={"telefone": "5511999999999", "condominio_id": condominio_id, "codigo": codigo})
    assert login.status_code == 200
    token = login.json()["access_token"]
    perfil = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert perfil.status_code == 200
    assert perfil.json()["perfil"] == "morador"
    assert client.post("/api/v1/auth/verify-otp", json={"telefone": "5511999999999", "condominio_id": condominio_id, "codigo": codigo}).status_code == 401


def test_rotas_privadas_rejeitam_sem_token():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as anonymous:
        resposta = anonymous.get("/api/v1/unidades")
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Autenticação necessária."}


def test_validacao_facial_demonstrativa(client):
    resposta = client.post(
        "/api/v1/facial/validate",
        files={"image": ("imagem.txt", b"conteudo-invalido", "text/plain")},
    )
    assert resposta.status_code == 200
    assert resposta.json() == {
        "success": False,
        "validated": False,
        "demo": True,
        "message": "Não foi possível processar a imagem.",
        "confidence": None,
    }


def test_cors_para_as_duas_origens_frontend(client):
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        resposta = client.options(
            "/api/v1/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert resposta.status_code == 200
        assert resposta.headers["access-control-allow-origin"] == origin


def test_login_demonstrativo_para_todos_os_perfis(client):
    for perfil, telefone in (("morador", "5511999999991"), ("portaria", "5511999999992"), ("sindico", "5511999999993")):
        resposta = client.post(
            "/api/v1/auth/login",
            json={"telefone": telefone, "perfil": perfil, "codigo": "123456"},
        )
        assert resposta.status_code == 200
        body = resposta.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["usuario"]["perfil"] == perfil


def test_portaria_e_sindico_acessam_rotas_administrativas(client):
    for perfil, telefone in (("portaria", "5511999999994"), ("sindico", "5511999999995")):
        login = client.post("/api/v1/auth/login", json={"telefone": telefone, "perfil": perfil, "codigo": "123456"})
        token = login.json()["access_token"]
        resposta = client.get("/api/v1/unidades", headers={"Authorization": f"Bearer {token}"})
        assert resposta.status_code == 200


def test_morador_recebe_403_em_rota_administrativa(client):
    login = client.post("/api/v1/auth/login", json={"telefone": "5511999999996", "perfil": "morador", "codigo": "123456"})
    resposta = client.get("/api/v1/unidades", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert resposta.status_code == 403


def test_token_invalido_e_credencial_ausente(client):
    invalido = client.get("/api/v1/unidades", headers={"Authorization": "Bearer token-invalido"})
    assert invalido.status_code == 401
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as anonymous:
        ausente = anonymous.get("/api/v1/unidades")
    assert ausente.status_code == 401


def test_headers_de_compatibilidade_em_desenvolvimento(client):
    resposta = client.get(
        "/api/v1/unidades",
        headers={"X-User-Profile": "portaria", "X-User-Phone": "5511999999997"},
    )
    assert resposta.status_code == 200