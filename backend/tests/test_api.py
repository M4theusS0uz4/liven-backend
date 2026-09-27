def criar_unidade(client, bloco="A", numero="101"):
    resposta = client.post("/api/v1/unidades", json={"bloco": bloco, "numero": numero, "andar": 1})
    assert resposta.status_code == 201
    return resposta.json()


def criar_morador(client, unidade_id, **extra):
    dados = {"unidade_id": unidade_id, "nome": "Ana Souza", "email": "ana@example.com"}
    dados.update(extra)
    resposta = client.post("/api/v1/moradores", json=dados)
    assert resposta.status_code == 201
    return resposta.json()


def test_health_cors_e_listas_vazias(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/unidades").json() == []
    assert client.get("/api/v1/moradores").json() == []
    assert client.get("/api/v1/entregas").json() == []
    resposta = client.options(
        "/api/v1/unidades",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_crud_unidade_e_integridade_morador(client):
    unidade = criar_unidade(client)
    atualizada = client.put(f"/api/v1/unidades/{unidade['id']}", json={"bloco": "A", "numero": "102", "andar": 1, "ativa": True})
    assert atualizada.status_code == 200
    morador = criar_morador(client, unidade["id"], cpf="123.456.789-09")
    duplicado = client.post("/api/v1/moradores", json={"unidade_id": unidade["id"], "nome": "Outra Pessoa", "cpf": "12345678909"})
    assert duplicado.status_code == 409
    excluir = client.delete(f"/api/v1/unidades/{unidade['id']}")
    assert excluir.status_code == 409
    assert client.get(f"/api/v1/moradores/{morador['id']}").status_code == 200


def test_tipo_residencia_persiste_para_casa_e_apartamento(client):
    casa = client.post(
        "/api/v1/unidades",
        json={"bloco": "Rua das Palmeiras", "numero": "Casa 12", "andar": None, "tipo_residencia": "casa"},
    )
    assert casa.status_code == 201
    assert casa.json()["tipo_residencia"] == "casa"
    assert casa.json()["andar"] is None

    apartamento = client.put(
        f"/api/v1/unidades/{casa.json()['id']}",
        json={"bloco": "Torre A", "numero": "101", "andar": 0, "tipo_residencia": "apartamento", "ativa": True},
    )
    assert apartamento.status_code == 200
    assert apartamento.json()["tipo_residencia"] == "apartamento"
    assert apartamento.json()["andar"] == 0
    assert client.get("/api/v1/unidades").json()[0]["tipo_residencia"] == "apartamento"


def test_regras_de_validacao_e_404(client):
    assert client.post("/api/v1/moradores", json={"unidade_id": 999, "nome": "Ana"}).status_code == 422
    assert client.post("/api/v1/unidades", json={"bloco": "A", "numero": "101"}).status_code == 201
    assert client.post("/api/v1/unidades", json={"bloco": "A", "numero": "101"}).status_code == 409
    assert client.get("/api/v1/unidades/999").status_code == 404
    assert client.post("/api/v1/moradores", json={"unidade_id": 1, "nome": "Ana", "email": "invalido"}).status_code == 422


def test_crud_entrega_status_e_historico(client):
    unidade = criar_unidade(client)
    morador = criar_morador(client, unidade["id"])
    entrega = client.post("/api/v1/entregas", json={"morador_id": morador["id"], "codigo_retirada": "LIV-001"})
    assert entrega.status_code == 201
    assert entrega.json()["status"] == "recebida"
    retirada = client.patch(f"/api/v1/entregas/{entrega.json()['id']}/status", json={"status": "retirada"})
    assert retirada.status_code == 200
    assert retirada.json()["retirada_em"] is not None
    devolvida = client.patch(f"/api/v1/entregas/{entrega.json()['id']}/status", json={"status": "devolvida"})
    assert devolvida.status_code == 200
    assert devolvida.json()["retirada_em"] is not None
    assert client.post("/api/v1/entregas", json={"morador_id": 999, "codigo_retirada": "LIV-002"}).status_code == 422


def test_mapa_persistido_sem_dados_sensiveis_e_posicoes(client):
    unidade = criar_unidade(client, "B", "201")
    mapa = client.get("/api/v1/condominio/mapa")
    assert mapa.status_code == 200
    assert mapa.json()["unidades"] == []
    posicao = client.post(
        "/api/v1/condominio/mapa/unidades",
        json={"unidade_id": unidade["id"], "x": 0.1, "y": 0.2, "largura": 0.1, "altura": 0.1, "rotacao": 0},
    )
    assert posicao.status_code == 201
    assert "nome" not in posicao.json()
    mapa = client.get("/api/v1/condominio/mapa").json()
    assert mapa["unidades"][0]["status"] == "vazia"
    morador = criar_morador(client, unidade["id"])
    assert client.get("/api/v1/condominio/mapa").json()["unidades"][0]["status"] == "ocupada"
    assert "email" not in client.get("/api/v1/condominio/mapa").text
    atualizado = client.patch(f"/api/v1/condominio/mapa/unidades/{posicao.json()['id']}", json={"x": 0.3, "y": 0.4, "largura": 0.1, "altura": 0.1, "rotacao": 15})
    assert atualizado.status_code == 200
    assert morador["id"] > 0
