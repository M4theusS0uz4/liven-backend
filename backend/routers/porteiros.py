from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import PerfilUsuario, Porteiro, Usuario
from schemas.plataforma import PorteiroCreate, PorteiroRead, PorteiroUpdate, StatusPorteiroUpdate
from security import normalize_phone, require_profiles

router = APIRouter(prefix="/api/v1/porteiros", tags=["Porteiros"])
DbSession = Annotated[Session, Depends(get_db)]
Staff = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.SINDICO, PerfilUsuario.PORTARIA))]
Sindico = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.SINDICO))]


def _read(porteiro: Porteiro) -> PorteiroRead:
    return PorteiroRead(
        id=porteiro.id,
        usuario_id=porteiro.usuario_id,
        nome=porteiro.usuario.nome,
        telefone=porteiro.usuario.telefone,
        ativo=porteiro.ativo and porteiro.usuario.ativo,
        created_at=porteiro.created_at,
    )


@router.get("", response_model=list[PorteiroRead])
def listar_porteiros(db: DbSession, _user: Staff) -> list[PorteiroRead]:
    porteiros = db.scalars(select(Porteiro).join(Porteiro.usuario).where(Usuario.condominio_id == _user.condominio_id).order_by(Porteiro.id)).all()
    return [_read(item) for item in porteiros]


@router.post("", response_model=PorteiroRead, status_code=status.HTTP_201_CREATED)
def criar_porteiro(dados: PorteiroCreate, db: DbSession, user: Sindico) -> PorteiroRead:
    try:
        telefone = normalize_phone(dados.telefone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Dados inválidos.") from exc
    usuario = Usuario(condominio_id=user.condominio_id, telefone=telefone, nome=dados.nome.strip(), perfil=PerfilUsuario.PORTARIA)
    db.add(usuario)
    db.flush()
    porteiro = Porteiro(usuario_id=usuario.id)
    db.add(porteiro)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Não foi possível cadastrar o porteiro.") from exc
    db.refresh(porteiro)
    return _read(porteiro)


@router.get("/{porteiro_id}", response_model=PorteiroRead)
def consultar_porteiro(porteiro_id: int, db: DbSession, _user: Staff) -> PorteiroRead:
    porteiro = db.scalar(select(Porteiro).join(Porteiro.usuario).where(Porteiro.id == porteiro_id, Usuario.condominio_id == _user.condominio_id))
    if porteiro is None:
        raise HTTPException(status_code=404, detail="Porteiro não encontrado.")
    return _read(porteiro)


@router.put("/{porteiro_id}", response_model=PorteiroRead)
def atualizar_porteiro(porteiro_id: int, dados: PorteiroUpdate, db: DbSession, user: Sindico) -> PorteiroRead:
    porteiro = db.scalar(select(Porteiro).join(Porteiro.usuario).where(Porteiro.id == porteiro_id, Usuario.condominio_id == user.condominio_id))
    if porteiro is None:
        raise HTTPException(status_code=404, detail="Porteiro não encontrado.")
    if dados.nome is not None:
        porteiro.usuario.nome = dados.nome.strip()
    if dados.telefone is not None:
        try:
            porteiro.usuario.telefone = normalize_phone(dados.telefone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Dados inválidos.") from exc
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Não foi possível atualizar o porteiro.") from exc
    db.refresh(porteiro)
    return _read(porteiro)


@router.patch("/{porteiro_id}/status", response_model=PorteiroRead)
def atualizar_status(porteiro_id: int, dados: StatusPorteiroUpdate, db: DbSession, user: Sindico) -> PorteiroRead:
    porteiro = db.scalar(select(Porteiro).join(Porteiro.usuario).where(Porteiro.id == porteiro_id, Usuario.condominio_id == user.condominio_id))
    if porteiro is None:
        raise HTTPException(status_code=404, detail="Porteiro não encontrado.")
    porteiro.ativo = dados.ativo
    porteiro.usuario.ativo = dados.ativo
    db.commit()
    db.refresh(porteiro)
    return _read(porteiro)