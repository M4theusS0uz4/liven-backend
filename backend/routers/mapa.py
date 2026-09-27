from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config.database import get_db
from models.orm import Mapa, MapaRua, MapaUnidade, Morador, PerfilUsuario, Unidade
from schemas.mapa import MapaRead, MapaUnidadeCreate, MapaUnidadeRead, MapaUnidadeUpdate
from security import get_current_user, require_profiles

router = APIRouter(prefix="/api/v1/condominio", tags=["Mapa"], dependencies=[Depends(require_profiles(PerfilUsuario.PORTARIA, PerfilUsuario.SINDICO))])
DbSession = Annotated[Session, Depends(get_db)]


def buscar_mapa(db: Session) -> Mapa:
    mapa = db.scalar(
        select(Mapa)
        .options(
            selectinload(Mapa.unidades).selectinload(MapaUnidade.unidade),
            selectinload(Mapa.blocos),
            selectinload(Mapa.ruas).selectinload(MapaRua.pontos),
            selectinload(Mapa.areas_comuns),
            selectinload(Mapa.portarias),
        )
        .order_by(Mapa.id)
    )
    if mapa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapa do condomínio não encontrado.")
    return mapa


def serializar_mapa(mapa: Mapa, db: Session) -> dict:
    unidade_ids = [item.unidade_id for item in mapa.unidades]
    ativos = set(
        db.scalars(select(Morador.unidade_id).where(Morador.unidade_id.in_(unidade_ids), Morador.ativo.is_(True))).all()
    ) if unidade_ids else set()
    return {
        "id": mapa.id,
        "nome": mapa.nome,
        "largura": mapa.largura,
        "altura": mapa.altura,
        "unidades": [
            {
                "id": item.id,
                "unidade_id": item.unidade_id,
                "bloco": item.unidade.bloco,
                "numero": item.unidade.numero,
                "x": item.x,
                "y": item.y,
                "largura": item.largura,
                "altura": item.altura,
                "rotacao": item.rotacao,
                "status": "ocupada" if item.unidade_id in ativos else "vazia",
            }
            for item in mapa.unidades
        ],
        "blocos": [{"id": item.id, "nome": item.nome, "x": item.x, "y": item.y, "largura": item.largura, "altura": item.altura, "andares": item.andares} for item in mapa.blocos],
        "ruas": [{"id": item.id, "nome": item.nome, "largura": item.largura, "pontos": [{"x": ponto.x, "y": ponto.y} for ponto in item.pontos]} for item in mapa.ruas],
        "areas_comuns": [{"id": item.id, "nome": item.nome, "tipo": item.tipo, "x": item.x, "y": item.y, "largura": item.largura, "altura": item.altura} for item in mapa.areas_comuns],
        "portarias": [{"id": item.id, "nome": item.nome, "x": item.x, "y": item.y} for item in mapa.portarias],
    }


@router.get("/mapa", response_model=MapaRead)
def consultar_mapa(db: DbSession) -> dict:
    return serializar_mapa(buscar_mapa(db), db)


@router.post("/mapa/unidades", response_model=MapaUnidadeRead, status_code=status.HTTP_201_CREATED)
def cadastrar_posicao(dados: MapaUnidadeCreate, db: DbSession) -> dict:
    mapa = buscar_mapa(db)
    if db.get(Unidade, dados.unidade_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A unidade informada não existe.")
    if any(item.unidade_id == dados.unidade_id for item in mapa.unidades):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A unidade já possui uma posição no mapa.")
    item = MapaUnidade(mapa_id=mapa.id, **dados.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    item.unidade = db.get(Unidade, item.unidade_id)
    return {
        **dados.model_dump(),
        "id": item.id,
        "bloco": item.unidade.bloco,
        "numero": item.unidade.numero,
        "status": "vazia",
    }


@router.put("/mapa/unidades/{posicao_id}", response_model=MapaUnidadeRead)
@router.patch("/mapa/unidades/{posicao_id}", response_model=MapaUnidadeRead)
def atualizar_posicao(posicao_id: int, dados: MapaUnidadeUpdate, db: DbSession) -> dict:
    item = db.get(MapaUnidade, posicao_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Posição de unidade não encontrada.")
    for campo, valor in dados.model_dump().items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    unidade = db.get(Unidade, item.unidade_id)
    ocupado = db.scalar(select(Morador.id).where(Morador.unidade_id == item.unidade_id, Morador.ativo.is_(True)).limit(1)) is not None
    return {**dados.model_dump(), "id": item.id, "unidade_id": item.unidade_id, "bloco": unidade.bloco, "numero": unidade.numero, "status": "ocupada" if ocupado else "vazia"}


@router.delete("/mapa/unidades/{posicao_id}", status_code=204)
def excluir_posicao(posicao_id: int, db: DbSession) -> Response:
    item = db.get(MapaUnidade, posicao_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Posição de unidade não encontrada.")
    db.delete(item)
    db.commit()
    return Response(status_code=204)
