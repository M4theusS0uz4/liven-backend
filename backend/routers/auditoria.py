from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Auditoria, PerfilUsuario, Usuario
from security import require_profiles
from services.audit_service import verificar_integridade

router = APIRouter(prefix="/api/v1/auditoria", tags=["Auditoria"])
Sindico = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.SINDICO))]


@router.get("")
def listar(user: Sindico, db: Session = Depends(get_db), limite: int = Query(50, ge=1, le=200)) -> list[dict]:
    registros = db.scalars(
        select(Auditoria)
        .where(Auditoria.condominio_id == user.condominio_id)
        .order_by(Auditoria.id.desc())
        .limit(limite)
    )
    return [
        {"id": r.id, "criado_em": r.criado_em, "usuario_id": r.usuario_id, "acao": r.acao,
         "recurso": r.recurso, "recurso_id": r.recurso_id, "detalhes": r.detalhes,
         "hash_atual": r.hash_atual}
        for r in registros
    ]


@router.get("/verificar")
def verificar(user: Sindico, db: Session = Depends(get_db)) -> dict:
    integro, violado = verificar_integridade(db, user.condominio_id)
    return {"integro": integro, "primeiro_registro_violado": violado}