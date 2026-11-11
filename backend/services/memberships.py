"""Recupera autorizações existentes; não cria Usuario, perfil ou associação."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.orm import ContaGlobal, Condominio, PerfilUsuario, Usuario
from schemas.auth import MeResponse
from schemas.registration import VinculoRead


def valid_membership(user: Usuario | None, email: str) -> bool:
    if user is None or not user.ativo or not user.condominio.ativo or user.email != email:
        return False
    if user.perfil not in {item.value for item in PerfilUsuario}:
        return False
    # Preserva Usuario como autorização original. Se há perfil operacional associado,
    # sua revogação/inconsistência não pode ser contornada pela conta global.
    if user.perfil == PerfilUsuario.MORADOR and user.morador is not None:
        resident = user.morador
        if not resident.ativo or not resident.unidade.ativa or resident.unidade.condominio_id != user.condominio_id:
            return False
    if user.perfil == PerfilUsuario.PORTARIA and user.porteiro is not None and not user.porteiro.ativo:
        return False
    return True


def authorized_users(account: ContaGlobal, db: Session) -> list[Usuario]:
    if not account.ativo or account.email_verificado_em is None:
        return []
    candidates = db.scalars(select(Usuario).join(Usuario.condominio).where(
        Usuario.email == account.email, Usuario.ativo.is_(True), Condominio.ativo.is_(True)
    ).order_by(Usuario.condominio_id, Usuario.id)).all()
    return [user for user in candidates if valid_membership(user, account.email)]


def membership_read(user: Usuario) -> VinculoRead:
    return VinculoRead(usuario_id=user.id, condominio_id=user.condominio_id,
                      condominio_nome=user.condominio.nome, perfil=user.perfil)


def user_read(user: Usuario) -> MeResponse:
    return MeResponse(id=user.id, condominio_id=user.condominio_id, nome=user.nome,
                      telefone=user.telefone, email=user.email, perfil=user.perfil,
                      ativo=user.ativo, unidade_id=user.morador.unidade_id if user.morador else None,
                      created_at=user.created_at)
