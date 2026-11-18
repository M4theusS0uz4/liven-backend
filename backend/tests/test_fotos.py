from base64 import b64decode, b64encode
from io import BytesIO

import pytest
from PIL import Image

from conftest import TestingSession
from models.orm import Condominio, PerfilUsuario, Usuario
from security import create_access_token


def foto(tom: str) -> str:
    arquivo = BytesIO()
    Image.new("RGB", (900, 450), tom).save(arquivo, "PNG")
    return "data:image/png;base64," + b64encode(arquivo.getvalue()).decode()


@pytest.mark.parametrize(
    ("colecao", "dados"),
    [
        ("moradores", {"nome": "Pessoa teste", "unidade_id": 1}),
        ("porteiros", {"nome": "Porteiro teste", "telefone": "5511987654321", "turno": "Noite"}),
        ("veiculos", {"placa": "ABC1D23", "modelo": "Modelo teste"}),
        ("visitantes", {"nome": "Visitante teste"}),
    ],
)
def test_fotos_criar_substituir_preservar_remover_e_isolar(client, colecao, dados):
    if colecao == "moradores":
        unidade = client.post("/api/v1/unidades", json={"bloco": "B", "numero": "12"}).json()
        dados = {**dados, "unidade_id": unidade["id"]}

    inicio = f"/api/v1/{colecao}"
    foto_original = foto("red")
    foto_nova = foto("blue")
    invalido = client.post(inicio, json={**dados, "foto": "data:image/svg+xml;base64,PHN2Zz4="})
    assert invalido.status_code == 422
    criado = client.post(inicio, json={**dados, "foto": foto_original})
    assert criado.status_code == 201
    item = criado.json()
    assert item["tem_foto"]
    assert "foto" not in item and "foto_jpeg" not in item
    if colecao == "porteiros":
        assert item["turno"] == "Noite"
    recurso = f"{inicio}/{item['id']}"
    imagem = f"{recurso}/foto"

    resposta = client.get(imagem)
    assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"] == "no-store"
    anterior = resposta.json()["foto"]
    assert anterior.startswith("data:image/jpeg;base64,")
    with Image.open(BytesIO(b64decode(anterior.split(",")[1]))) as retrato:
        assert retrato.size == (640, 320)

    resposta = client.get(imagem, headers={"Authorization": ""})
    assert resposta.status_code == 401
    with TestingSession.begin() as db:
        outro = Condominio(nome="Outro condomínio")
        db.add(outro)
        db.flush()
        usuario = Usuario(condominio_id=outro.id, nome="Síndico externo", telefone="5511987651111", perfil=PerfilUsuario.SINDICO)
        db.add(usuario)
        db.flush()
        token = create_access_token(usuario)
    assert client.get(imagem, headers={"Authorization": f"Bearer {token}"}).status_code == 404
    assert client.put(recurso, json={**dados, "foto": None}, headers={"Authorization": f"Bearer {token}"}).status_code == 404

    assert client.put(recurso, json=dados).json()["tem_foto"]
    assert client.get(imagem).json()["foto"] == anterior
    assert client.put(recurso, json={**dados, "foto": foto_nova}).json()["tem_foto"]
    assert client.get(imagem).json()["foto"] != anterior
    assert client.put(recurso, json={**dados, "foto": None}).json()["tem_foto"] is False
    assert client.get(imagem).status_code == 404
