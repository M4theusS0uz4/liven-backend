from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UnidadeBase(BaseModel):
    bloco: str = Field(min_length=1, max_length=30, examples=["A"])
    numero: str = Field(min_length=1, max_length=20, examples=["101"])
    andar: int | None = Field(default=None, ge=0, le=999)
    ativa: bool = True

    @field_validator("bloco", "numero")
    @classmethod
    def remover_espacos_externos(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O campo não pode ficar vazio.")
        return value


class UnidadeCreate(UnidadeBase):
    """Dados necessários para cadastrar uma unidade."""


class UnidadeUpdate(UnidadeBase):
    """Dados completos para atualizar uma unidade."""


class UnidadeRead(UnidadeBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
