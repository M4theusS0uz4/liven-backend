"""Contexto autorizado na sessão por senha; preserva usuários e perfis existentes."""
from alembic import op
import sqlalchemy as sa

revision = "20261111_0011"
down_revision = "20261111_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessoes_globais', sa.Column('usuario_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_sessoes_globais_usuario', 'sessoes_globais', 'usuarios', ['usuario_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_sessoes_globais_usuario_id', 'sessoes_globais', ['usuario_id'])


def downgrade():
    raise RuntimeError('Downgrade exige plano manual para preservar os contextos das sessões.')
