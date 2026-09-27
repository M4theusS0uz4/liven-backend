from datetime import datetime, time, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.database import get_db
from models.orm import Acesso, Comunicado, Entrega, Morador, Ocorrencia, PerfilUsuario, Porteiro, StatusEntrega, StatusOcorrencia, Usuario, Unidade
from schemas.plataforma import DashboardRead
from security import require_profiles

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])
DbSession = Annotated[Session, Depends(get_db)]
Sindico = Annotated[Usuario, Depends(require_profiles(PerfilUsuario.SINDICO))]


@router.get("/sindico", response_model=DashboardRead)
def dashboard_sindico(db: DbSession, user: Sindico) -> DashboardRead:
    inicio_dia = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    condominio = user.condominio_id
    return DashboardRead(
        total_unidades=db.scalar(select(func.count(Unidade.id)).where(Unidade.condominio_id == condominio)) or 0,
        unidades_ocupadas=db.scalar(select(func.count(func.distinct(Morador.unidade_id))).join(Unidade, Morador.unidade_id == Unidade.id).where(Unidade.condominio_id == condominio, Morador.ativo.is_(True))) or 0,
        moradores_ativos=db.scalar(select(func.count(Morador.id)).join(Unidade, Morador.unidade_id == Unidade.id).where(Unidade.condominio_id == condominio, Morador.ativo.is_(True))) or 0,
        porteiros_ativos=db.scalar(select(func.count(Porteiro.id)).join(Usuario, Porteiro.usuario_id == Usuario.id).where(Usuario.condominio_id == condominio, Porteiro.ativo.is_(True), Usuario.ativo.is_(True))) or 0,
        entregas_pendentes=db.scalar(select(func.count(Entrega.id)).join(Morador, Entrega.morador_id == Morador.id).join(Unidade, Morador.unidade_id == Unidade.id).where(Unidade.condominio_id == condominio, Entrega.status.in_([StatusEntrega.RECEBIDA, StatusEntrega.NOTIFICADA]))) or 0,
        ocorrencias_abertas=db.scalar(select(func.count(Ocorrencia.id)).where(Ocorrencia.condominio_id == condominio, Ocorrencia.status == StatusOcorrencia.ABERTA)) or 0,
        ocorrencias_em_analise=db.scalar(select(func.count(Ocorrencia.id)).where(Ocorrencia.condominio_id == condominio, Ocorrencia.status == StatusOcorrencia.EM_ANALISE)) or 0,
        ocorrencias_resolvidas=db.scalar(select(func.count(Ocorrencia.id)).where(Ocorrencia.condominio_id == condominio, Ocorrencia.status == StatusOcorrencia.RESOLVIDA)) or 0,
        comunicados_ativos=db.scalar(select(func.count(Comunicado.id)).where(Comunicado.condominio_id == condominio, Comunicado.publicado.is_(True), Comunicado.arquivado.is_(False))) or 0,
        acessos_hoje=db.scalar(select(func.count(Acesso.id)).where(Acesso.condominio_id == condominio, Acesso.ocorrido_em >= inicio_dia)) or 0,
    )