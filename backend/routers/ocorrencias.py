from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Morador, Ocorrencia, OcorrenciaHistorico, PerfilUsuario, StatusOcorrencia, Usuario, Unidade
from schemas.plataforma import OcorrenciaCreate, OcorrenciaHistoricoRead, OcorrenciaRead, OcorrenciaStatusUpdate, OcorrenciaUpdate
from security import get_current_user, require_profiles, utcnow

router = APIRouter(prefix="/api/v1/ocorrencias", tags=["Ocorrências"])
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Usuario, Depends(get_current_user)]
Staff = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.PORTARIA, PerfilUsuario.SINDICO))]


def _unidade_do_usuario(db: Session, user: Usuario) -> Unidade | None:
    morador = db.scalar(select(Morador).where(Morador.usuario_id == user.id))
    return db.get(Unidade, morador.unidade_id) if morador else None


@router.get("", response_model=list[OcorrenciaRead])
def listar_ocorrencias(db: DbSession, user: CurrentUser) -> list[Ocorrencia]:
    query = select(Ocorrencia).where(Ocorrencia.condominio_id == user.condominio_id)
    if user.perfil == PerfilUsuario.MORADOR:
        query = query.where(Ocorrencia.autor_id == user.id)
    return list(db.scalars(query.order_by(desc(Ocorrencia.id))).all())


@router.post("", response_model=OcorrenciaRead, status_code=status.HTTP_201_CREATED)
def criar_ocorrencia(dados: OcorrenciaCreate, db: DbSession, user: CurrentUser) -> Ocorrencia:
    unidade = db.get(Unidade, dados.unidade_id) if dados.unidade_id else _unidade_do_usuario(db, user)
    if unidade is None or unidade.condominio_id != user.condominio_id:
        raise HTTPException(status_code=422, detail="Unidade inválida.")
    if user.perfil == PerfilUsuario.MORADOR and not db.scalar(select(Morador.id).where(Morador.usuario_id == user.id, Morador.unidade_id == unidade.id)):
        raise HTTPException(status_code=403, detail="Acesso não autorizado.")
    ocorrencia = Ocorrencia(condominio_id=user.condominio_id, unidade_id=unidade.id, autor_id=user.id, titulo=dados.titulo, descricao=dados.descricao, categoria=dados.categoria, prioridade=dados.prioridade)
    db.add(ocorrencia)
    db.flush()
    db.add(OcorrenciaHistorico(ocorrencia_id=ocorrencia.id, usuario_id=user.id, status_novo=StatusOcorrencia.ABERTA.value))
    db.commit()
    db.refresh(ocorrencia)
    return ocorrencia


def _buscar(ocorrencia_id: int, db: Session, user: Usuario) -> Ocorrencia:
    ocorrencia = db.scalar(select(Ocorrencia).where(Ocorrencia.id == ocorrencia_id, Ocorrencia.condominio_id == user.condominio_id))
    if ocorrencia is None or (user.perfil == PerfilUsuario.MORADOR and ocorrencia.autor_id != user.id):
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada.")
    return ocorrencia


@router.get("/{ocorrencia_id}", response_model=OcorrenciaRead)
def consultar_ocorrencia(ocorrencia_id: int, db: DbSession, user: CurrentUser) -> Ocorrencia:
    return _buscar(ocorrencia_id, db, user)


@router.put("/{ocorrencia_id}", response_model=OcorrenciaRead)
def atualizar_ocorrencia(ocorrencia_id: int, dados: OcorrenciaUpdate, db: DbSession, user: CurrentUser) -> Ocorrencia:
    ocorrencia = _buscar(ocorrencia_id, db, user)
    if user.perfil not in {PerfilUsuario.MORADOR, PerfilUsuario.SINDICO}:
        raise HTTPException(status_code=403, detail="Permissão insuficiente.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(ocorrencia, campo, valor)
    db.commit()
    db.refresh(ocorrencia)
    return ocorrencia


@router.patch("/{ocorrencia_id}/status", response_model=OcorrenciaRead)
def atualizar_status(ocorrencia_id: int, dados: OcorrenciaStatusUpdate, db: DbSession, user: Staff) -> Ocorrencia:
    ocorrencia = _buscar(ocorrencia_id, db, user)
    anterior = ocorrencia.status.value if isinstance(ocorrencia.status, StatusOcorrencia) else ocorrencia.status
    ocorrencia.status = dados.status
    db.add(OcorrenciaHistorico(ocorrencia_id=ocorrencia.id, usuario_id=user.id, status_anterior=anterior, status_novo=dados.status.value, comentario=dados.comentario))
    db.commit()
    db.refresh(ocorrencia)
    return ocorrencia


@router.get("/{ocorrencia_id}/historico", response_model=list[OcorrenciaHistoricoRead])
def historico(ocorrencia_id: int, db: DbSession, user: CurrentUser) -> list[OcorrenciaHistorico]:
    _buscar(ocorrencia_id, db, user)
    return list(db.scalars(select(OcorrenciaHistorico).where(OcorrenciaHistorico.ocorrencia_id == ocorrencia_id).order_by(OcorrenciaHistorico.id)).all())