"""Fotos opcionais dos cadastros do condomínio."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0012"
down_revision = "20261111_0011"
branch_labels = None
depends_on = None

tabelas = ("moradores", "porteiros", "veiculos", "visitantes")


def upgrade():
    for tabela in tabelas:
        op.add_column(tabela, sa.Column("foto_jpeg", sa.LargeBinary(), nullable=True))


def downgrade():
    for tabela in reversed(tabelas):
        op.drop_column(tabela, "foto_jpeg")
