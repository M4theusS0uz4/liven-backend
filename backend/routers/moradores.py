from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Morador, Unidade
from schemas.morador import MoradorCreate, MoradorRead, MoradorUpdate

router = APIRouter(prefix="/api/v1/moradores", tags=["Moradores"])
DbSession = Annotated[Session, Depends(get_db)]


def buscar_morador_ou_404(morador_id: int, db: Session) -> Morador:
    morador = db.get(Morador, morador_id)
    if morador is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Morador não encontrado.")
    return morador


def garantir_unidade_existente(unidade_id: int, db: Session) -> None:
    if db.get(Unidade, unidade_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A unidade informada não existe.")


def confirmar_alteracao(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CPF ou e-mail já está vinculado a outro morador.",
        ) from exc


@router.get("", response_model=list[MoradorRead])
def listar_moradores(db: DbSession, unidade_id: int | None = None, somente_ativos: bool = False) -> list[Morador]:
    consulta = select(Morador).order_by(Morador.nome)
    if unidade_id is not None:
        consulta = consulta.where(Morador.unidade_id == unidade_id)
    if somente_ativos:
        consulta = consulta.where(Morador.ativo.is_(True))
    return list(db.scalars(consulta).all())


@router.get("/{morador_id}", response_model=MoradorRead)
def consultar_morador(morador_id: int, db: DbSession) -> Morador:
    return buscar_morador_ou_404(morador_id, db)


@router.post("", response_model=MoradorRead, status_code=status.HTTP_201_CREATED)
def criar_morador(dados: MoradorCreate, db: DbSession) -> Morador:
    garantir_unidade_existente(dados.unidade_id, db)
    morador = Morador(**dados.model_dump())
    db.add(morador)
    confirmar_alteracao(db)
    db.refresh(morador)
    return morador


@router.put("/{morador_id}", response_model=MoradorRead)
def atualizar_morador(morador_id: int, dados: MoradorUpdate, db: DbSession) -> Morador:
    morador = buscar_morador_ou_404(morador_id, db)
    garantir_unidade_existente(dados.unidade_id, db)
    for campo, valor in dados.model_dump().items():
        setattr(morador, campo, valor)
    confirmar_alteracao(db)
    db.refresh(morador)
    return morador


@router.delete("/{morador_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_morador(morador_id: int, db: DbSession) -> Response:
    morador = buscar_morador_ou_404(morador_id, db)
    db.delete(morador)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível excluir um morador vinculado a entregas.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
