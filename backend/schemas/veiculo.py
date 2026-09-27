from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VeiculoCreate(BaseModel):
    placa: str = Field(min_length=5, max_length=10)
    modelo: str = Field(min_length=2, max_length=100)
    cor: str | None = Field(default=None, max_length=50)
    morador_id: int | None = Field(default=None, gt=0)

    @field_validator("placa")
    @classmethod
    def normalizar_placa(cls, value: str) -> str:
        return value.strip().upper().replace("-", "")


class VeiculoRead(VeiculoCreate):
    id: int
    condominio_id: int
    ativo: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)