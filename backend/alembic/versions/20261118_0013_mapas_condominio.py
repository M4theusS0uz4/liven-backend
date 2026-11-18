"""Persiste a planta e vincula mapas a um condomínio."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0013"
down_revision = "20261118_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mapas", sa.Column("condominio_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_mapas_condominio", "mapas", "condominios", ["condominio_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_mapas_condominio", "mapas", ["condominio_id"])
    # The legacy API served the first map globally. Preserve that map only when
    # there is one possible owner. Keep ambiguous legacy rows outside tenant reads.
    op.execute("""
        UPDATE mapas
        SET condominio_id = (SELECT min(id) FROM condominios)
        WHERE id = (SELECT min(id) FROM mapas)
          AND (SELECT count(*) FROM condominios) = 1
    """)
    for tabela in ("mapa_blocos", "mapa_areas_comuns", "mapa_portarias"):
        op.add_column(tabela, sa.Column("rotacao", sa.Float(), server_default="0", nullable=False))
    op.add_column("mapa_unidades", sa.Column("oculta", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    raise RuntimeError("Downgrade exige plano manual para preservar as plantas por condomínio.")
