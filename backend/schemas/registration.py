from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from schemas.auth import AuthResponse, MeResponse
from models.orm import PerfilUsuario
from services.email_identity import normalize_email


class GlobalOtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=255)

    @field_validator("email", mode="before")
    @classmethod
    def normalizar_email(cls, value: str) -> str:
        return normalize_email(value)


class GlobalOtpVerify(GlobalOtpRequest):
    codigo: str = Field(pattern=r"^[0-9]{6}$")


class PasswordRegistrationRequest(GlobalOtpRequest):
    senha: SecretStr = Field(min_length=8, max_length=128)


class PasswordRegistrationVerify(PasswordRegistrationRequest):
    codigo: str = Field(pattern=r"^[0-9]{6}$")


class PasswordLoginRequest(GlobalOtpRequest):
    senha: SecretStr = Field(min_length=1, max_length=128)


class ContaGlobalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    ativo: bool
    email_verificado_em: datetime
    created_at: datetime


class VinculoRead(BaseModel):
    usuario_id: int
    condominio_id: int
    condominio_nome: str
    perfil: PerfilUsuario


class SelecionarCondominio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usuario_id: int = Field(gt=0)


class GlobalAuthResponse(AuthResponse):
    conta: ContaGlobalRead
    scope: Literal["global", "condominio"] = "global"
    usuario: MeResponse | None = None
    vinculos: list[VinculoRead] = Field(default_factory=list)
