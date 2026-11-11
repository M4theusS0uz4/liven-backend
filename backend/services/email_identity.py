"""Identidade de login: e-mail validado e canônico, sem remover pontos ou aliases."""
from pydantic import EmailStr, TypeAdapter

_EMAIL = TypeAdapter(EmailStr)


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("E-mail inválido.")
    email = str(_EMAIL.validate_python(value.strip())).lower()
    if len(email) > 255:
        raise ValueError("E-mail inválido.")
    return email
