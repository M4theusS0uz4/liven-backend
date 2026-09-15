"""modelo inicial de acesso e entregas

Revision ID: 20260826_0001
Revises:
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa

revision = "20260826_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("unidades", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("bloco", sa.String(30), nullable=False), sa.Column("numero", sa.String(20), nullable=False), sa.Column("andar", sa.Integer()), sa.Column("ativa", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.UniqueConstraint("bloco", "numero", name="uq_unidades_bloco_numero"))
    op.create_index("ix_unidades_bloco", "unidades", ["bloco"])
    op.create_table("moradores", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("unidade_id", sa.Integer(), sa.ForeignKey("unidades.id", ondelete="RESTRICT"), nullable=False), sa.Column("nome", sa.String(150), nullable=False), sa.Column("cpf", sa.String(14), unique=True), sa.Column("email", sa.String(255), unique=True), sa.Column("telefone", sa.String(25)), sa.Column("foto_facial_path", sa.String(500)), sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_index("ix_moradores_unidade_id", "moradores", ["unidade_id"])
    op.create_table("entregas", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("morador_id", sa.Integer(), sa.ForeignKey("moradores.id", ondelete="RESTRICT"), nullable=False), sa.Column("codigo_retirada", sa.String(32), nullable=False, unique=True), sa.Column("transportadora", sa.String(100)), sa.Column("remetente", sa.String(150)), sa.Column("descricao", sa.Text()), sa.Column("status", sa.Enum("recebida", "notificada", "retirada", "devolvida", name="status_entrega"), nullable=False, server_default="recebida"), sa.Column("recebida_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("retirada_em", sa.DateTime(timezone=True)), sa.Column("recebido_por", sa.String(150)))
    op.create_index("ix_entregas_codigo_retirada", "entregas", ["codigo_retirada"])
    op.create_index("ix_entregas_morador_id", "entregas", ["morador_id"])
    op.create_table("registros_acesso", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("morador_id", sa.Integer(), sa.ForeignKey("moradores.id", ondelete="SET NULL")), sa.Column("unidade_id", sa.Integer(), sa.ForeignKey("unidades.id", ondelete="SET NULL")), sa.Column("visitante_nome", sa.String(150)), sa.Column("metodo", sa.Enum("facial", "qr_code", "manual", name="metodo_acesso"), nullable=False), sa.Column("permitido", sa.Boolean(), nullable=False), sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("observacao", sa.Text()))
    op.create_index("ix_registros_acesso_morador_id", "registros_acesso", ["morador_id"])
    op.create_index("ix_registros_acesso_unidade_id", "registros_acesso", ["unidade_id"])
    op.create_index("ix_registros_acesso_ocorrido_em", "registros_acesso", ["ocorrido_em"])


def downgrade() -> None:
    op.drop_table("registros_acesso")
    op.drop_table("entregas")
    op.drop_table("moradores")
    op.drop_table("unidades")
    op.execute("DROP TYPE IF EXISTS metodo_acesso")
    op.execute("DROP TYPE IF EXISTS status_entrega")
