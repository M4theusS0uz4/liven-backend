from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Morador, PerfilUsuario, Unidade, Usuario
from schemas.morador import MoradorCreate, MoradorRead, MoradorUpdate
from security import get_current_user, require_profiles

router = APIRouter(prefix="/api/v1/moradores", tags=["Moradores"], dependencies=[Depends(require_profiles(PerfilUsuario.PORTARIA, PerfilUsuario.SINDICO))])
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Usuario, Depends(get_current_user)]


def buscar_morador_ou_404(morador_id: int, db: Session, condominio_id: int | None = None) -> Morador:
    consulta = select(Morador).where(Morador.id == morador_id)
    if condominio_id is not None:
        consulta = consulta.join(Morador.unidade).where(Unidade.condominio_id == condominio_id)
    morador = db.scalar(consulta)
    if morador is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Morador não encontrado.")
    return morador


def garantir_unidade_existente(unidade_id: int, db: Session, condominio_id: int | None = None) -> None:
    consulta = select(Unidade).where(Unidade.id == unidade_id)
    if condominio_id is not None:
        consulta = consulta.where(Unidade.condominio_id == condominio_id)
    if db.scalar(consulta) is None:
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
def listar_moradores(db: DbSession, user: CurrentUser, unidade_id: int | None = None, somente_ativos: bool = False) -> list[Morador]:
    consulta = select(Morador).join(Morador.unidade).where(Unidade.condominio_id == user.condominio_id).order_by(Morador.nome)
    if unidade_id is not None:
        consulta = consulta.where(Morador.unidade_id == unidade_id)
    if somente_ativos:
        consulta = consulta.where(Morador.ativo.is_(True))
    return list(db.scalars(consulta).all())


@router.get("/{morador_id}", response_model=MoradorRead)
def consultar_morador(morador_id: int, db: DbSession, user: CurrentUser) -> Morador:
    return buscar_morador_ou_404(morador_id, db, user.condominio_id)


@router.post("", response_model=MoradorRead, status_code=status.HTTP_201_CREATED)
def criar_morador(dados: MoradorCreate, db: DbSession, user: CurrentUser) -> Morador:
    garantir_unidade_existente(dados.unidade_id, db, user.condominio_id)
    morador = Morador(**dados.model_dump())
    db.add(morador)
    confirmar_alteracao(db)
    db.refresh(morador)
    return morador


@router.put("/{morador_id}", response_model=MoradorRead)
def atualizar_morador(morador_id: int, dados: MoradorUpdate, db: DbSession, user: CurrentUser) -> Morador:
    morador = buscar_morador_ou_404(morador_id, db, user.condominio_id)
    garantir_unidade_existente(dados.unidade_id, db, user.condominio_id)
    for campo, valor in dados.model_dump().items():
        setattr(morador, campo, valor)
    confirmar_alteracao(db)
    db.refresh(morador)
    return morador


@router.delete("/{morador_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_morador(morador_id: int, db: DbSession, user: CurrentUser) -> Response:
    morador = buscar_morador_ou_404(morador_id, db, user.condominio_id)
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
