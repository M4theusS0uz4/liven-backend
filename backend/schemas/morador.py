from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class MoradorBase(BaseModel):
    unidade_id: int = Field(gt=0, examples=[1])
    nome: str = Field(min_length=2, max_length=150, examples=["Ana Souza"])
    cpf: str | None = Field(default=None, min_length=11, max_length=14, examples=["123.456.789-09"])
    email: EmailStr | None = Field(default=None, examples=["ana@example.com"])
    telefone: str | None = Field(default=None, max_length=25, examples=["(11) 99999-9999"])
    foto_facial_path: str | None = Field(default=None, max_length=500)
    ativo: bool = True

    @field_validator("nome")
    @classmethod
    def validar_nome(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("O nome deve ter ao menos dois caracteres.")
        return value

    @field_validator("cpf")
    @classmethod
    def normalizar_cpf(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        digitos = "".join(caractere for caractere in value if caractere.isdigit())
        if len(digitos) != 11:
            raise ValueError("CPF deve conter 11 dígitos.")
        return digitos

    @field_validator("telefone", "foto_facial_path", mode="before")
    @classmethod
    def converter_vazio_em_nulo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class MoradorCreate(MoradorBase):
    """Dados necessários para cadastrar um morador."""


class MoradorUpdate(MoradorBase):
    """Dados completos para atualizar um morador."""


class MoradorRead(MoradorBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
