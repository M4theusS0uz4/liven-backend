"""extend condominium and access contracts

Revision ID: 20260927_0005
Revises: 20260923_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260927_0005"
down_revision = "20260923_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("unidades", "bloco", existing_type=sa.String(length=30), type_=sa.String(length=150), existing_nullable=False)
    op.alter_column("unidades", "numero", existing_type=sa.String(length=20), type_=sa.String(length=30), existing_nullable=False)
    op.add_column("unidades", sa.Column("tipo_residencia", sa.String(length=20), nullable=False, server_default="apartamento"))

    op.add_column("mapas", sa.Column("tipo_condominio", sa.String(length=20), nullable=False, server_default="vertical"))
    op.alter_column("mapas", "largura", existing_type=sa.Float(), server_default="100")
    op.alter_column("mapas", "altura", existing_type=sa.Float(), server_default="100")
    op.execute("UPDATE mapas SET largura = largura * 100, altura = altura * 100")
    op.execute("UPDATE mapa_unidades SET x = x * 100, y = y * 100, largura = largura * 100, altura = altura * 100")
    op.execute("UPDATE mapa_blocos SET x = x * 100, y = y * 100, largura = largura * 100, altura = altura * 100")
    op.execute("UPDATE mapa_ruas SET largura = largura * 100")
    op.execute("UPDATE mapa_ruas_pontos SET x = x * 100, y = y * 100")
    op.execute("UPDATE mapa_areas_comuns SET x = x * 100, y = y * 100, largura = largura * 100, altura = altura * 100")
    op.execute("UPDATE mapa_portarias SET x = x * 100, y = y * 100")

    op.add_column("veiculos", sa.Column("marca", sa.String(length=80), nullable=True))
    op.add_column("veiculos", sa.Column("vaga", sa.String(length=30), nullable=True))
    op.add_column("porteiros", sa.Column("turno", sa.String(length=40), nullable=False, server_default="Manhã"))
    op.add_column("visitantes", sa.Column("placa", sa.String(length=16), nullable=True))
    op.add_column("qr_codes", sa.Column("codigo", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_qr_codes_codigo", "qr_codes", ["codigo"])

    op.add_column("autorizacoes_acesso", sa.Column("metodo_visita", sa.String(length=20), nullable=False, server_default="qr"))
    op.add_column("autorizacoes_acesso", sa.Column("estado_visita", sa.String(length=20), nullable=False, server_default="authorized"))
    op.create_index("ix_autorizacoes_acesso_estado_visita", "autorizacoes_acesso", ["estado_visita"])
    op.add_column("registros_acesso", sa.Column("evento", sa.String(length=24), nullable=False, server_default="entrada"))
    op.add_column("registros_acesso", sa.Column("registrado_por_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_registros_acesso_registrado_por", "registros_acesso", "usuarios", ["registrado_por_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_registros_acesso_registrado_por_id", "registros_acesso", ["registrado_por_id"])


def downgrade() -> None:
    op.drop_index("ix_registros_acesso_registrado_por_id", table_name="registros_acesso")
    op.drop_constraint("fk_registros_acesso_registrado_por", "registros_acesso", type_="foreignkey")
    op.drop_column("registros_acesso", "registrado_por_id")
    op.drop_column("registros_acesso", "evento")
    op.drop_index("ix_autorizacoes_acesso_estado_visita", table_name="autorizacoes_acesso")
    op.drop_column("autorizacoes_acesso", "estado_visita")
    op.drop_column("autorizacoes_acesso", "metodo_visita")
    op.drop_constraint("uq_qr_codes_codigo", "qr_codes", type_="unique")
    op.drop_column("qr_codes", "codigo")
    op.drop_column("visitantes", "placa")
    op.drop_column("porteiros", "turno")
    op.drop_column("veiculos", "vaga")
    op.drop_column("veiculos", "marca")
    op.alter_column("mapas", "altura", existing_type=sa.Float(), server_default="1")
    op.alter_column("mapas", "largura", existing_type=sa.Float(), server_default="1")
    op.drop_column("mapas", "tipo_condominio")
    op.drop_column("unidades", "tipo_residencia")
    op.alter_column("unidades", "numero", existing_type=sa.String(length=30), type_=sa.String(length=20), existing_nullable=False)
    op.alter_column("unidades", "bloco", existing_type=sa.String(length=150), type_=sa.String(length=30), existing_nullable=False)