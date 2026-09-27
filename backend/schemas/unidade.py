from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UnidadeBase(BaseModel):
    bloco: str = Field(min_length=1, max_length=150, examples=["Rua das Palmeiras"])
    numero: str = Field(min_length=1, max_length=30, examples=["Casa 12"])
    andar: int | None = Field(default=None, ge=0, le=999)
    tipo_residencia: Literal["casa", "apartamento"] = "apartamento"
    ativa: bool = True

    @field_validator("bloco", "numero")
    @classmethod
    def remover_espacos_externos(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O campo não pode ficar vazio.")
        return value

    @model_validator(mode="after")
    def casa_sem_andar(self):
        if self.tipo_residencia == "casa":
            self.andar = None
        return self


class UnidadeCreate(UnidadeBase):
    """Dados necessários para cadastrar uma unidade."""


class UnidadeUpdate(UnidadeBase):
    """Dados completos para atualizar uma unidade."""


class UnidadeRead(UnidadeBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
