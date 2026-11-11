"""Identidade OTP por e-mail, preservando contas e desafios legados.

Não copia e-mails de moradores: o vínculo de identidade exige revisão administrativa.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261110_0008"
down_revision = "20261104_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("email", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_usuarios_condominio_email", "usuarios", ["condominio_id", "email"])
    op.create_check_constraint("ck_usuarios_email_normalizado", "usuarios", "email IS NULL OR email = lower(trim(email))")
    op.add_column("otp_challenges", sa.Column("email", sa.String(255), nullable=True))
    op.alter_column("otp_challenges", "telefone", existing_type=sa.String(25), nullable=True)


def downgrade() -> None:
    # Falhar explicitamente evita excluir dados ou inventar telefones para novos OTPs.
    raise RuntimeError("Downgrade exige plano manual: preservação dos desafios OTP por e-mail.")
