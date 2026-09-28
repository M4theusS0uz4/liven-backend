"""auditoria com hash encadeado"""
import sqlalchemy as sa
from alembic import op

revision = "20260928_0006"
down_revision = "20260927_0005"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("auditoria", sa.Column("detalhes", sa.Text(), nullable=True))
    op.add_column("auditoria", sa.Column("hash_anterior", sa.String(length=64), nullable=True))
    op.add_column("auditoria", sa.Column("hash_atual", sa.String(length=64), nullable=True))

def downgrade() -> None:
    op.drop_column("auditoria", "hash_atual")
    op.drop_column("auditoria", "hash_anterior")
    op.drop_column("auditoria", "detalhes")