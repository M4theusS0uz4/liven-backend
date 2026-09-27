from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Morador, PerfilUsuario, Usuario, Veiculo
from schemas.veiculo import VeiculoCreate, VeiculoRead
from security import get_current_user

router = APIRouter(prefix="/api/v1/veiculos", tags=["Veículos"])
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Usuario, Depends(get_current_user)]


def _query(user: Usuario):
    query = select(Veiculo).where(Veiculo.condominio_id == user.condominio_id)
    return query.where(Veiculo.morador.has(usuario_id=user.id)) if user.perfil == PerfilUsuario.MORADOR else query


@router.get("", response_model=list[VeiculoRead])
def listar_veiculos(db: DbSession, user: CurrentUser) -> list[Veiculo]:
    return list(db.scalars(_query(user).order_by(Veiculo.id)).all())


@router.post("", response_model=VeiculoRead, status_code=status.HTTP_201_CREATED)
def criar_veiculo(dados: VeiculoCreate, db: DbSession, user: CurrentUser) -> Veiculo:
    morador_id = dados.morador_id
    if user.perfil == PerfilUsuario.MORADOR:
        morador_id = db.scalar(select(Morador.id).where(Morador.usuario_id == user.id))
    if morador_id is not None and db.scalar(select(Morador.id).where(Morador.id == morador_id, Morador.unidade.has(condominio_id=user.condominio_id))) is None:
        raise HTTPException(status_code=403, detail="Acesso não autorizado.")
    veiculo = Veiculo(condominio_id=user.condominio_id, morador_id=morador_id, **dados.model_dump(exclude={"morador_id"}))
    db.add(veiculo)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A placa já está cadastrada.") from exc
    db.refresh(veiculo)
    return veiculo


@router.put("/{veiculo_id}", response_model=VeiculoRead)
def atualizar_veiculo(veiculo_id: int, dados: VeiculoCreate, db: DbSession, user: CurrentUser) -> Veiculo:
    veiculo = db.scalar(_query(user).where(Veiculo.id == veiculo_id))
    if veiculo is None:
        raise HTTPException(status_code=404, detail="Veículo não encontrado.")
    for campo, valor in dados.model_dump().items():
        setattr(veiculo, campo, valor)
    db.commit()
    db.refresh(veiculo)
    return veiculo


@router.delete("/{veiculo_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_veiculo(veiculo_id: int, db: DbSession, user: CurrentUser) -> None:
    veiculo = db.scalar(_query(user).where(Veiculo.id == veiculo_id))
    if veiculo is None:
        raise HTTPException(status_code=404, detail="Veículo não encontrado.")
    veiculo.ativo = False
    db.commit()