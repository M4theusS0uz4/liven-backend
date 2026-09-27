from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Comunicado, ComunicadoLeitura, PerfilUsuario, PublicoComunicado, Usuario, Unidade
from schemas.plataforma import ComunicadoCreate, ComunicadoRead
from security import get_current_user, require_profiles, utcnow

router = APIRouter(prefix="/api/v1/comunicados", tags=["Comunicados"])
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[Usuario, Depends(get_current_user)]
Sindico = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.SINDICO))]


def _read(item: Comunicado, lido_em=None) -> ComunicadoRead:
    return ComunicadoRead(
        id=item.id,
        autor_id=item.autor_id,
        condominio_id=item.condominio_id,
        titulo=item.titulo,
        mensagem=item.mensagem,
        publico=item.publico,
        bloco=item.bloco,
        unidade_id=item.unidade_id,
        perfil=item.perfil,
        publicado=item.publicado,
        arquivado=item.arquivado,
        created_at=item.created_at,
        lido_em=lido_em,
    )


def _aplicavel(item: Comunicado, user: Usuario, db: Session) -> bool:
    if item.publico == PublicoComunicado.TODOS:
        return True
    if item.publico == PublicoComunicado.PERFIL:
        return item.perfil == user.perfil
    unidade = db.scalar(select(Unidade).where(Unidade.condominio_id == user.condominio_id, Unidade.moradores.any(usuario_id=user.id)))
    return (item.publico == PublicoComunicado.BLOCO and unidade is not None and item.bloco == unidade.bloco) or (item.publico == PublicoComunicado.UNIDADE and unidade is not None and item.unidade_id == unidade.id)


@router.get("", response_model=list[ComunicadoRead])
def listar_comunicados(db: DbSession, user: CurrentUser) -> list[ComunicadoRead]:
    itens = db.scalars(select(Comunicado).where(Comunicado.condominio_id == user.condominio_id, Comunicado.publicado.is_(True), Comunicado.arquivado.is_(False)).order_by(desc(Comunicado.id))).all()
    return [_read(item, db.scalar(select(ComunicadoLeitura.lido_em).where(ComunicadoLeitura.comunicado_id == item.id, ComunicadoLeitura.usuario_id == user.id))) for item in itens if _aplicavel(item, user, db)]


@router.post("", response_model=ComunicadoRead, status_code=status.HTTP_201_CREATED)
def criar_comunicado(dados: ComunicadoCreate, db: DbSession, user: Sindico) -> ComunicadoRead:
    comunicado = Comunicado(condominio_id=user.condominio_id, autor_id=user.id, **dados.model_dump())
    db.add(comunicado)
    db.commit()
    db.refresh(comunicado)
    return _read(comunicado)


@router.put("/{comunicado_id}", response_model=ComunicadoRead)
def atualizar_comunicado(comunicado_id: int, dados: ComunicadoCreate, db: DbSession, user: Sindico) -> ComunicadoRead:
    comunicado = db.scalar(select(Comunicado).where(Comunicado.id == comunicado_id, Comunicado.condominio_id == user.condominio_id))
    if comunicado is None:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    for campo, valor in dados.model_dump().items():
        setattr(comunicado, campo, valor)
    db.commit()
    db.refresh(comunicado)
    return _read(comunicado)


@router.post("/{comunicado_id}/arquivar", response_model=ComunicadoRead)
def arquivar_comunicado(comunicado_id: int, db: DbSession, user: Sindico) -> ComunicadoRead:
    comunicado = db.scalar(select(Comunicado).where(Comunicado.id == comunicado_id, Comunicado.condominio_id == user.condominio_id))
    if comunicado is None:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    comunicado.arquivado = True
    db.commit()
    return _read(comunicado)


@router.post("/{comunicado_id}/ler", response_model=ComunicadoRead)
def ler_comunicado(comunicado_id: int, db: DbSession, user: CurrentUser) -> ComunicadoRead:
    comunicado = db.scalar(select(Comunicado).where(Comunicado.id == comunicado_id, Comunicado.condominio_id == user.condominio_id))
    if comunicado is None or not _aplicavel(comunicado, user, db):
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    leitura = db.scalar(select(ComunicadoLeitura).where(ComunicadoLeitura.comunicado_id == comunicado_id, ComunicadoLeitura.usuario_id == user.id))
    if leitura is None:
        leitura = ComunicadoLeitura(comunicado_id=comunicado_id, usuario_id=user.id)
        db.add(leitura)
        db.commit()
        db.refresh(leitura)
    return _read(comunicado, leitura.lido_em)