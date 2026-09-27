from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.orm import CategoriaOcorrencia, PerfilUsuario, PrioridadeOcorrencia, PublicoComunicado, StatusAutorizacao, StatusOcorrencia


class PorteiroCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=150)
    telefone: str = Field(min_length=8, max_length=25)


class PorteiroUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=150)
    telefone: str | None = Field(default=None, min_length=8, max_length=25)


class PorteiroRead(BaseModel):
    id: int
    usuario_id: int
    nome: str
    telefone: str
    ativo: bool
    created_at: datetime


class StatusPorteiroUpdate(BaseModel):
    ativo: bool


class VisitanteCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=150)
    telefone: str | None = Field(default=None, max_length=25)
    documento: str | None = Field(default=None, max_length=32)

    @field_validator("nome")
    @classmethod
    def limpar_nome(cls, value: str) -> str:
        return value.strip()


class VisitanteUpdate(VisitanteCreate):
    ativo: bool = True


class VisitanteRead(VisitanteCreate):
    id: int
    condominio_id: int
    ativo: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AcessoCreate(BaseModel):
    visitante_id: int = Field(gt=0)
    morador_id: int | None = Field(default=None, gt=0)
    inicio: datetime
    fim: datetime
    limite_usos: int = Field(default=1, ge=1, le=100)


class AcessoRead(BaseModel):
    id: int
    visitante_id: int
    morador_id: int
    unidade_id: int
    inicio: datetime
    fim: datetime
    status: StatusAutorizacao
    limite_usos: int
    usos: int
    revogada_em: datetime | None
    created_at: datetime
    qr_token: str | None = None


class QrValidation(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class FacialValidation(BaseModel):
    referencia: str = Field(min_length=1, max_length=500)


class AcessoHistoricoRead(BaseModel):
    id: int
    visitante_nome: str | None
    unidade_id: int | None
    metodo: str
    permitido: bool
    ocorrido_em: datetime
    observacao: str | None


class ComunicadoCreate(BaseModel):
    titulo: str = Field(min_length=2, max_length=180)
    mensagem: str = Field(min_length=1, max_length=20_000)
    publico: PublicoComunicado = PublicoComunicado.TODOS
    bloco: str | None = Field(default=None, max_length=30)
    unidade_id: int | None = Field(default=None, gt=0)
    perfil: PerfilUsuario | None = None


class ComunicadoRead(ComunicadoCreate):
    id: int
    autor_id: int
    condominio_id: int
    publicado: bool
    arquivado: bool
    created_at: datetime
    lido_em: datetime | None = None


class OcorrenciaCreate(BaseModel):
    titulo: str = Field(min_length=2, max_length=180)
    descricao: str = Field(min_length=1, max_length=20_000)
    categoria: CategoriaOcorrencia
    prioridade: PrioridadeOcorrencia = PrioridadeOcorrencia.NORMAL
    unidade_id: int | None = Field(default=None, gt=0)


class OcorrenciaUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=2, max_length=180)
    descricao: str | None = Field(default=None, min_length=1, max_length=20_000)
    prioridade: PrioridadeOcorrencia | None = None


class OcorrenciaStatusUpdate(BaseModel):
    status: StatusOcorrencia
    comentario: str | None = Field(default=None, max_length=5_000)


class OcorrenciaRead(OcorrenciaCreate):
    id: int
    condominio_id: int
    autor_id: int
    status: StatusOcorrencia
    created_at: datetime
    updated_at: datetime


class OcorrenciaHistoricoRead(BaseModel):
    id: int
    usuario_id: int
    status_anterior: str | None
    status_novo: str
    comentario: str | None
    created_at: datetime


class DashboardRead(BaseModel):
    total_unidades: int
    unidades_ocupadas: int
    moradores_ativos: int
    porteiros_ativos: int
    entregas_pendentes: int
    ocorrencias_abertas: int
    ocorrencias_em_analise: int
    ocorrencias_resolvidas: int
    comunicados_ativos: int
    acessos_hoje: int