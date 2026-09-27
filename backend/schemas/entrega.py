from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models.orm import StatusEntrega


class EntregaCreate(BaseModel):
    morador_id: int = Field(gt=0)
    codigo_retirada: str = Field(min_length=1, max_length=32)
    transportadora: str | None = Field(default=None, max_length=100)
    remetente: str | None = Field(default=None, max_length=150)
    descricao: str | None = None
    recebido_por: str | None = Field(default=None, max_length=150)


class EntregaStatusUpdate(BaseModel):
    status: StatusEntrega


class EntregaRead(EntregaCreate):
    id: int
    status: StatusEntrega
    recebida_em: datetime
    retirada_em: datetime | None

    model_config = ConfigDict(from_attributes=True)
