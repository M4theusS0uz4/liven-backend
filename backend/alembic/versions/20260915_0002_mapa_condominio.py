"""estrutura persistida para planta do condominio

Revision ID: 20260915_0002
Revises: 20260826_0001
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = "20260915_0002"
down_revision = "20260826_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("largura", sa.Float(), nullable=False, server_default="1"),
        sa.Column("altura", sa.Float(), nullable=False, server_default="1"),
    )
    op.create_table(
        "mapa_unidades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapa_id", sa.Integer(), sa.ForeignKey("mapas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unidade_id", sa.Integer(), sa.ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("largura", sa.Float(), nullable=False),
        sa.Column("altura", sa.Float(), nullable=False),
        sa.Column("rotacao", sa.Float(), nullable=False, server_default="0"),
        sa.UniqueConstraint("mapa_id", "unidade_id", name="uq_mapa_unidades_mapa_unidade"),
    )
    op.create_index("ix_mapa_unidades_mapa_id", "mapa_unidades", ["mapa_id"])
    op.create_index("ix_mapa_unidades_unidade_id", "mapa_unidades", ["unidade_id"])
    op.create_table(
        "mapa_blocos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapa_id", sa.Integer(), sa.ForeignKey("mapas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(100), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("largura", sa.Float(), nullable=False),
        sa.Column("altura", sa.Float(), nullable=False),
        sa.Column("andares", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_mapa_blocos_mapa_id", "mapa_blocos", ["mapa_id"])
    op.create_table(
        "mapa_ruas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapa_id", sa.Integer(), sa.ForeignKey("mapas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("largura", sa.Float(), nullable=False),
    )
    op.create_index("ix_mapa_ruas_mapa_id", "mapa_ruas", ["mapa_id"])
    op.create_table(
        "mapa_ruas_pontos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rua_id", sa.Integer(), sa.ForeignKey("mapa_ruas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
    )
    op.create_index("ix_mapa_ruas_pontos_rua_id", "mapa_ruas_pontos", ["rua_id"])
    op.create_table(
        "mapa_areas_comuns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapa_id", sa.Integer(), sa.ForeignKey("mapas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("tipo", sa.String(80), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("largura", sa.Float(), nullable=False),
        sa.Column("altura", sa.Float(), nullable=False),
    )
    op.create_index("ix_mapa_areas_comuns_mapa_id", "mapa_areas_comuns", ["mapa_id"])
    op.create_table(
        "mapa_portarias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapa_id", sa.Integer(), sa.ForeignKey("mapas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
    )
    op.create_index("ix_mapa_portarias_mapa_id", "mapa_portarias", ["mapa_id"])
    op.bulk_insert(sa.table("mapas", sa.column("nome", sa.String), sa.column("largura", sa.Float), sa.column("altura", sa.Float)), [{"nome": "Planta principal", "largura": 1.0, "altura": 1.0}])


def downgrade() -> None:
    op.drop_table("mapa_portarias")
    op.drop_table("mapa_areas_comuns")
    op.drop_table("mapa_ruas_pontos")
    op.drop_table("mapa_ruas")
    op.drop_table("mapa_blocos")
    op.drop_table("mapa_unidades")
    op.drop_table("mapas")
