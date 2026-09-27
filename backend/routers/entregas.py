from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Entrega, Morador, StatusEntrega, Unidade, Usuario
from schemas.entrega import EntregaCreate, EntregaRead, EntregaStatusUpdate
from security import get_current_user

router = APIRouter(prefix="/api/v1/entregas", tags=["Entregas"], dependencies=[Depends(get_current_user)])
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Usuario, Depends(get_current_user)]


def buscar_entrega_ou_404(entrega_id: int, db: Session, condominio_id: int | None = None) -> Entrega:
    consulta = select(Entrega).where(Entrega.id == entrega_id)
    if condominio_id is not None:
        consulta = consulta.join(Entrega.morador).join(Morador.unidade).where(Unidade.condominio_id == condominio_id)
    entrega = db.scalar(consulta)
    if entrega is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrega não encontrada.")
    return entrega


@router.get("", response_model=list[EntregaRead])
def listar_entregas(db: DbSession, user: CurrentUser, status_entrega: StatusEntrega | None = None) -> list[Entrega]:
    consulta = select(Entrega).join(Entrega.morador).join(Morador.unidade).where(Unidade.condominio_id == user.condominio_id).order_by(Entrega.recebida_em.desc())
    if status_entrega is not None:
        consulta = consulta.where(Entrega.status == status_entrega)
    return list(db.scalars(consulta).all())


@router.post("", response_model=EntregaRead, status_code=status.HTTP_201_CREATED)
def criar_entrega(dados: EntregaCreate, db: DbSession, user: CurrentUser) -> Entrega:
    if db.scalar(select(Morador).join(Morador.unidade).where(Morador.id == dados.morador_id, Unidade.condominio_id == user.condominio_id)) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O morador informado não existe.")
    entrega = Entrega(**dados.model_dump())
    db.add(entrega)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O código de retirada já está em uso.") from exc
    db.refresh(entrega)
    return entrega


@router.patch("/{entrega_id}/status", response_model=EntregaRead)
def atualizar_status(entrega_id: int, dados: EntregaStatusUpdate, db: DbSession, user: CurrentUser) -> Entrega:
    entrega = buscar_entrega_ou_404(entrega_id, db, user.condominio_id)
    entrega.status = dados.status
    if dados.status == StatusEntrega.RETIRADA:
        entrega.retirada_em = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entrega)
    return entrega
