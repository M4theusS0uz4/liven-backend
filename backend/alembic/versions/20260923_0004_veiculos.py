"""veiculos do condominio

Revision ID: 20260923_0004
Revises: 20260916_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260923_0004"
down_revision = "20260916_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "veiculos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("morador_id", sa.Integer(), sa.ForeignKey("moradores.id", ondelete="SET NULL")),
        sa.Column("placa", sa.String(10), nullable=False),
        sa.Column("modelo", sa.String(100), nullable=False),
        sa.Column("cor", sa.String(50)),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("condominio_id", "placa", name="uq_veiculos_condominio_placa"),
    )
    op.create_index("ix_veiculos_condominio_id", "veiculos", ["condominio_id"])
    op.create_index("ix_veiculos_morador_id", "veiculos", ["morador_id"])


def downgrade() -> None:
    op.drop_table("veiculos")