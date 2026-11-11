"""Provisionamento administrativo local. Simula por padrão; não envia e-mail."""
import argparse

from sqlalchemy import select, update

from config.database import SessionLocal
from models.orm import Condominio, Morador, OtpChallenge, PerfilUsuario, RefreshToken, Usuario
from security import normalize_phone, utcnow
from services.email_identity import normalize_email


def provision(*, condominio_id: int, email: str, usuario_id: int | None = None,
              morador_id: int | None = None, criar_conta: bool = False, apply: bool = False):
    email = normalize_email(email)
    if (usuario_id is None) == (morador_id is None):
        raise ValueError("Informe exatamente um usuário ou morador.")
    if criar_conta and morador_id is None:
        raise ValueError("Criação explícita é permitida somente para um morador cadastrado.")
    with SessionLocal.begin() as db:
        condo = db.scalar(select(Condominio).where(Condominio.id == condominio_id, Condominio.ativo.is_(True)).with_for_update())
        if condo is None:
            raise ValueError("Condomínio inválido.")
        resident = None
        if morador_id is not None:
            resident = db.scalar(select(Morador).where(Morador.id == morador_id).with_for_update())
            if resident is None or not resident.ativo or resident.unidade.condominio_id != condo.id:
                raise ValueError("Morador inválido para o condomínio.")
            usuario_id = resident.usuario_id
        user = db.scalar(select(Usuario).where(Usuario.id == usuario_id).with_for_update()) if usuario_id else None
        if user is None:
            if not resident or not criar_conta:
                raise ValueError("Conta inexistente. Revise o cadastro; criação exige --criar-conta com --morador-id.")
            if not resident.telefone:
                raise ValueError("Cadastre o telefone de contato antes de criar a conta.")
            phone = normalize_phone(resident.telefone)
            if db.scalar(select(Usuario.id).where(Usuario.condominio_id == condo.id, Usuario.telefone == phone)):
                raise ValueError("Já existe uma conta com esse telefone; revise o vínculo manualmente.")
        elif user.condominio_id != condo.id or not user.ativo or (resident and user.perfil != PerfilUsuario.MORADOR):
            raise ValueError("Conta inválida, inativa ou com perfil incompatível. Nenhum perfil será alterado.")
        owner = db.scalar(select(Usuario.id).where(Usuario.condominio_id == condo.id, Usuario.email == email))
        if owner is not None and (user is None or owner != user.id):
            raise ValueError("E-mail já vinculado neste condomínio.")
        if not apply:
            print("SIMULAÇÃO: atribuir e-mail de autenticação à conta selecionada; criar/vincular morador somente se explicitamente autorizado. Nenhuma alteração.")
            return
        if user is None:
            user = Usuario(condominio_id=condo.id, nome=resident.nome, telefone=phone,
                           email=email, perfil=PerfilUsuario.MORADOR)
            db.add(user)
            db.flush()
            resident.usuario_id = user.id
        elif user.email != email:
            user.email = email
            # Não permite que OTPs ou refresh antigos sobrevivam à troca da identidade.
            db.execute(update(OtpChallenge).where(OtpChallenge.usuario_id == user.id, OtpChallenge.used_at.is_(None)).values(used_at=utcnow()))
            db.execute(update(RefreshToken).where(RefreshToken.usuario_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
        print("Provisionamento concluído; perfil e estado ativo preservados. Nenhum e-mail enviado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condominio-id", type=int, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--usuario-id", type=int)
    target.add_argument("--morador-id", type=int)
    parser.add_argument("--email", required=True)
    parser.add_argument("--criar-conta", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        provision(**vars(args))
    except ValueError as error:
        parser.exit(2, f"{error}\n")
