"""Vincula novos desafios OTP ao usuário e, por consequência, ao condomínio.

Desafios legados permanecem sem vínculo e não são aceitos pela autenticação.
Nenhum usuário, tabela ou desafio existente é removido no upgrade.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261104_0007"
down_revision = "20260928_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("otp_challenges", sa.Column("usuario_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_otp_challenges_usuario", "otp_challenges", "usuarios",
        ["usuario_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_otp_challenges_usuario_id", "otp_challenges", ["usuario_id"])


def downgrade() -> None:
    op.drop_index("ix_otp_challenges_usuario_id", table_name="otp_challenges")
    op.drop_constraint("fk_otp_challenges_usuario", "otp_challenges", type_="foreignkey")
    op.drop_column("otp_challenges", "usuario_id")
