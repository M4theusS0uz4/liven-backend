from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config.database import get_db
from models.orm import Condominio, Mapa, MapaAreaComum, MapaBloco, MapaPortaria, MapaRua, MapaRuaPonto, MapaUnidade, Morador, PerfilUsuario, Unidade, Usuario
from schemas.mapa import MapaRead, MapaUnidadeCreate, MapaUnidadeRead, MapaUnidadeUpdate, MapaUpdate
from security import require_profiles

router = APIRouter(prefix="/api/v1/condominio", tags=["Mapa"])
DbSession = Annotated[Session, Depends(get_db)]
Staff = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.PORTARIA, PerfilUsuario.SINDICO))]


def buscar_mapa(db: Session, condominio_id: int, *, escrever: bool = False) -> Mapa:
    if escrever:
        # One lock covers concurrent changes to this map, including its first save.
        db.scalar(select(Condominio.id).where(Condominio.id == condominio_id).with_for_update())
    mapa = db.scalar(
        select(Mapa)
        .where(Mapa.condominio_id == condominio_id)
        .options(
            selectinload(Mapa.unidades).selectinload(MapaUnidade.unidade),
            selectinload(Mapa.blocos),
            selectinload(Mapa.ruas).selectinload(MapaRua.pontos),
            selectinload(Mapa.areas_comuns),
            selectinload(Mapa.portarias),
        )
    )
    if mapa is None and escrever:
        mapa = Mapa(condominio_id=condominio_id, nome="Mapa do condomínio")
        db.add(mapa)
    if mapa is None:
        raise HTTPException(status_code=404, detail="Mapa do condomínio não encontrado.")
    return mapa


def ocupadas(db: Session, unidade_ids: list[int]) -> set[int]:
    if not unidade_ids:
        return set()
    return set(db.scalars(select(Morador.unidade_id).where(
        Morador.unidade_id.in_(unidade_ids), Morador.ativo.is_(True),
    )).all())


def serializar_unidade(item: MapaUnidade, ativos: set[int]) -> MapaUnidadeRead:
    return MapaUnidadeRead(
        id=item.id, unidade_id=item.unidade_id, bloco=item.unidade.bloco, numero=item.unidade.numero,
        tipo_residencia=item.unidade.tipo_residencia, x=item.x, y=item.y, largura=item.largura,
        altura=item.altura, rotacao=item.rotacao, oculta=item.oculta,
        status="ocupada" if item.unidade_id in ativos else "vazia",
    )


def serializar_mapa(mapa: Mapa, db: Session) -> MapaRead:
    unidades = [item for item in mapa.unidades if item.unidade.condominio_id == mapa.condominio_id]
    ativos = ocupadas(db, [item.unidade_id for item in unidades])
    return MapaRead(
        id=mapa.id, nome=mapa.nome, tipo_condominio=mapa.tipo_condominio, largura=mapa.largura, altura=mapa.altura,
        unidades=[serializar_unidade(item, ativos) for item in unidades],
        blocos=mapa.blocos, ruas=mapa.ruas, areas_comuns=mapa.areas_comuns, portarias=mapa.portarias,
    )


def reconciliar(atuais, entradas, modelo):
    por_id = {item.id: item for item in atuais}
    ids = [entrada.id for entrada in entradas if entrada.id is not None]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="A planta contém elementos duplicados.")
    resultado = []
    for entrada in entradas:
        item = por_id.get(entrada.id) or modelo()
        for campo, valor in entrada.model_dump(exclude={"id", "pontos"}).items():
            setattr(item, campo, valor)
        if isinstance(item, MapaRua):
            item.pontos = [MapaRuaPonto(ordem=ordem, **ponto.model_dump()) for ordem, ponto in enumerate(entrada.pontos)]
        resultado.append(item)
    return resultado


@router.get("/mapa", response_model=MapaRead)
def consultar_mapa(db: DbSession, user: Staff) -> MapaRead:
    return serializar_mapa(buscar_mapa(db, user.condominio_id), db)


@router.put("/mapa", response_model=MapaRead)
def salvar_mapa(dados: MapaUpdate, db: DbSession, user: Staff) -> MapaRead:
    unidade_ids = {item.unidade_id for item in dados.unidades}
    if len(unidade_ids) != len(dados.unidades):
        raise HTTPException(status_code=422, detail="A planta contém residências duplicadas.")
    unidades = {item.id: item for item in db.scalars(select(Unidade).where(
        Unidade.condominio_id == user.condominio_id, Unidade.id.in_(unidade_ids),
    ))} if unidade_ids else {}
    if set(unidades) != unidade_ids:
        raise HTTPException(status_code=422, detail="Uma residência não pertence ao condomínio.")
    mapa = buscar_mapa(db, user.condominio_id, escrever=True)
    for campo in ("nome", "tipo_condominio", "largura", "altura"):
        setattr(mapa, campo, getattr(dados, campo))
    por_unidade = {item.unidade_id: item for item in mapa.unidades}
    posicoes = []
    for entrada in dados.unidades:
        item = por_unidade.get(entrada.unidade_id) or MapaUnidade(unidade=unidades[entrada.unidade_id])
        for campo, valor in entrada.model_dump().items():
            setattr(item, campo, valor)
        posicoes.append(item)
    mapa.unidades = posicoes
    mapa.blocos = reconciliar(mapa.blocos, dados.blocos, MapaBloco)
    mapa.ruas = reconciliar(mapa.ruas, dados.ruas, MapaRua)
    mapa.areas_comuns = reconciliar(mapa.areas_comuns, dados.areas_comuns, MapaAreaComum)
    mapa.portarias = reconciliar(mapa.portarias, dados.portarias, MapaPortaria)
    db.flush()
    resposta = serializar_mapa(mapa, db)
    db.commit()
    return resposta


@router.post("/mapa/unidades", response_model=MapaUnidadeRead, status_code=status.HTTP_201_CREATED)
def cadastrar_posicao(dados: MapaUnidadeCreate, db: DbSession, user: Staff) -> MapaUnidadeRead:
    mapa = buscar_mapa(db, user.condominio_id, escrever=True)
    unidade = db.get(Unidade, dados.unidade_id)
    if unidade is None or unidade.condominio_id != user.condominio_id:
        raise HTTPException(status_code=422, detail="A unidade informada não existe.")
    if any(item.unidade_id == dados.unidade_id for item in mapa.unidades):
        raise HTTPException(status_code=409, detail="A unidade já possui uma posição no mapa.")
    item = MapaUnidade(unidade=unidade, **dados.model_dump())
    mapa.unidades.append(item)
    db.flush()
    resposta = serializar_unidade(item, ocupadas(db, [item.unidade_id]))
    db.commit()
    return resposta


def buscar_posicao(posicao_id: int, db: Session, condominio_id: int) -> MapaUnidade:
    mapa = buscar_mapa(db, condominio_id, escrever=True)
    item = next((item for item in mapa.unidades if item.id == posicao_id and item.unidade.condominio_id == condominio_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Posição de unidade não encontrada.")
    return item


@router.put("/mapa/unidades/{posicao_id}", response_model=MapaUnidadeRead)
@router.patch("/mapa/unidades/{posicao_id}", response_model=MapaUnidadeRead)
def atualizar_posicao(posicao_id: int, dados: MapaUnidadeUpdate, db: DbSession, user: Staff) -> MapaUnidadeRead:
    item = buscar_posicao(posicao_id, db, user.condominio_id)
    for campo, valor in dados.model_dump().items():
        setattr(item, campo, valor)
    resposta = serializar_unidade(item, ocupadas(db, [item.unidade_id]))
    db.commit()
    return resposta


@router.delete("/mapa/unidades/{posicao_id}", status_code=204)
def excluir_posicao(posicao_id: int, db: DbSession, user: Staff) -> Response:
    db.delete(buscar_posicao(posicao_id, db, user.condominio_id))
    db.commit()
    return Response(status_code=204)
