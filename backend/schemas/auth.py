from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models.orm import PerfilUsuario
from services.email_identity import normalize_email


class OtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=255)
    condominio_id: int = Field(gt=0)

    @field_validator("email", mode="before")
    @classmethod
    def normalizar_email(cls, value: str) -> str:
        return normalize_email(value)


class OtpRequestResponse(BaseModel):
    detail: str
    codigo_mock: str | None = None


class OtpVerify(OtpRequest):
    codigo: str = Field(pattern=r"^[0-9]{6}$")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: int
    condominio_id: int
    nome: str
    telefone: str
    email: EmailStr | None = None
    perfil: PerfilUsuario
    ativo: bool
    unidade_id: int | None = None
    created_at: datetime