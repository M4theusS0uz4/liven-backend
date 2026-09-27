from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from models.orm import PerfilUsuario
from security import normalize_phone


class OtpRequest(BaseModel):
    telefone: str = Field(min_length=8, max_length=25)
    condominio_id: int = Field(gt=0)

    @field_validator("telefone")
    @classmethod
    def normalizar_telefone(cls, value: str) -> str:
        return normalize_phone(value)


class DemoLoginRequest(BaseModel):
    telefone: str = Field(min_length=8, max_length=25)
    perfil: PerfilUsuario
    codigo: str = Field(pattern=r"^\d{6}$")

    @field_validator("telefone")
    @classmethod
    def normalizar_telefone(cls, value: str) -> str:
        return normalize_phone(value)


class DemoUserResponse(BaseModel):
    telefone: str
    nome: str
    perfil: PerfilUsuario


class DemoLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: DemoUserResponse


class OtpVerify(BaseModel):
    telefone: str = Field(min_length=8, max_length=25)
    condominio_id: int = Field(gt=0)
    codigo: str = Field(pattern=r"^\d{6}$")

    @field_validator("telefone")
    @classmethod
    def normalizar_telefone(cls, value: str) -> str:
        return normalize_phone(value)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    codigo_mock: str | None = None


class MeResponse(BaseModel):
    id: int
    condominio_id: int
    nome: str
    telefone: str
    perfil: PerfilUsuario
    ativo: bool
    unidade_id: int | None = None
    created_at: datetime