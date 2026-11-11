"""Senhas globais, cadastro pendente e limitação persistida; sem alterar vínculos."""
from alembic import op
import sqlalchemy as sa

revision = "20261111_0010"
down_revision = "20261111_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('contas_globais', sa.Column('password_hash', sa.String(255), nullable=True))
    op.add_column('otp_cadastro', sa.Column('password_hash', sa.String(255), nullable=True))
    op.create_table('otp_definicao_senha',
        sa.Column('email', sa.String(255), primary_key=True),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('code_hash', sa.String(128), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')))
    op.create_table('limites_login',
        sa.Column('key', sa.String(80), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')))


def downgrade():
    raise RuntimeError('Downgrade exige plano manual para preservar hashes e cadastros pendentes.')
