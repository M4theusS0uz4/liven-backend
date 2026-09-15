from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Unidade
from schemas.unidade import UnidadeCreate, UnidadeRead, UnidadeUpdate

router = APIRouter(prefix="/api/v1/unidades", tags=["Unidades"])
DbSession = Annotated[Session, Depends(get_db)]


def buscar_unidade_ou_404(unidade_id: int, db: Session) -> Unidade:
    unidade = db.get(Unidade, unidade_id)
    if unidade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unidade não encontrada.")
    return unidade


def confirmar_alteracao(db: Session, mensagem_conflito: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mensagem_conflito) from exc


@router.get("", response_model=list[UnidadeRead])
def listar_unidades(db: DbSession, somente_ativas: bool = False) -> list[Unidade]:
    consulta = select(Unidade).order_by(Unidade.bloco, Unidade.numero)
    if somente_ativas:
        consulta = consulta.where(Unidade.ativa.is_(True))
    return list(db.scalars(consulta).all())


@router.get("/{unidade_id}", response_model=UnidadeRead)
def consultar_unidade(unidade_id: int, db: DbSession) -> Unidade:
    return buscar_unidade_ou_404(unidade_id, db)


@router.post("", response_model=UnidadeRead, status_code=status.HTTP_201_CREATED)
def criar_unidade(dados: UnidadeCreate, db: DbSession) -> Unidade:
    unidade = Unidade(**dados.model_dump())
    db.add(unidade)
    confirmar_alteracao(db, "Já existe uma unidade com este bloco e número.")
    db.refresh(unidade)
    return unidade


@router.put("/{unidade_id}", response_model=UnidadeRead)
def atualizar_unidade(unidade_id: int, dados: UnidadeUpdate, db: DbSession) -> Unidade:
    unidade = buscar_unidade_ou_404(unidade_id, db)
    for campo, valor in dados.model_dump().items():
        setattr(unidade, campo, valor)
    confirmar_alteracao(db, "Já existe uma unidade com este bloco e número.")
    db.refresh(unidade)
    return unidade


@router.delete("/{unidade_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_unidade(unidade_id: int, db: DbSession) -> Response:
    unidade = buscar_unidade_ou_404(unidade_id, db)
    db.delete(unidade)
    confirmar_alteracao(db, "Não é possível excluir uma unidade vinculada a moradores ou registros.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
