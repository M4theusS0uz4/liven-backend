from conftest import TestingSession
from models.orm import Condominio, PerfilUsuario, Unidade, Usuario
from security import create_access_token


def test_mapa_persiste_todos_os_elementos_e_isola_condominios(client):
    unidade = client.post("/api/v1/unidades", json={"bloco": "A", "numero": "12"}).json()
    posicao = {"unidade_id": unidade["id"], "x": 10, "y": 20, "largura": 5, "altura": 7, "rotacao": 15, "oculta": True}
    planta = {
        "nome": "Planta de visita", "tipo_condominio": "misto", "largura": 120, "altura": 80,
        "unidades": [posicao],
        "blocos": [{"id": 9100000000000, "nome": "Torre Ipê", "x": 20, "y": 30, "largura": 8, "altura": 9, "andares": 5, "rotacao": 45}],
        "ruas": [{"id": 42, "nome": "Via interna", "largura": 4, "pontos": [{"x": 0, "y": 0}, {"x": 20, "y": 0}, {"x": 20, "y": 30}]}],
        "areas_comuns": [{"nome": "Praça", "tipo": "jardim", "x": 30, "y": 40, "largura": 12, "altura": 9, "rotacao": 30}],
        "portarias": [{"nome": "Recepção", "x": 0, "y": 0, "rotacao": 90}],
    }
    rota = "/api/v1/condominio/mapa"
    gravado = client.put(rota, json=planta)
    assert gravado.status_code == 200, gravado.text
    mapa = gravado.json()
    assert mapa["unidades"][0]["oculta"] is True
    assert mapa["unidades"][0]["rotacao"] == 15
    assert mapa["ruas"][0]["pontos"] == planta["ruas"][0]["pontos"]
    assert mapa["blocos"][0]["rotacao"] == 45
    assert mapa["areas_comuns"][0]["rotacao"] == 30
    assert mapa["portarias"][0]["rotacao"] == 90
    assert client.get(rota).json() == mapa

    mapa["ruas"][0]["pontos"].append({"x": 30, "y": 30})
    assert client.put(rota, json=mapa).json() == mapa
    assert client.get(rota).json() == mapa

    with TestingSession.begin() as db:
        condominio = Condominio(nome="Condomínio externo")
        db.add(condominio)
        db.flush()
        usuario = Usuario(condominio_id=condominio.id, nome="Outro síndico", telefone="5511999999987", perfil=PerfilUsuario.SINDICO)
        db.add(usuario)
        db.flush()
        cabecalho = {"Authorization": f"Bearer {create_access_token(usuario)}"}

    assert client.get(rota, headers=cabecalho).status_code == 404
    assert client.put(rota, json=planta, headers=cabecalho).status_code == 422
    assert client.delete(f"{rota}/unidades/{mapa['unidades'][0]['id']}", headers=cabecalho).status_code == 404
    assert client.put(rota, json={"nome": "Planta própria", "largura": 100, "altura": 90}, headers=cabecalho).status_code == 200
    assert client.get(rota, headers=cabecalho).json()["nome"] == "Planta própria"
    assert client.get(rota).json() == mapa
