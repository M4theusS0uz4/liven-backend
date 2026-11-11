"""Contas globais e OTPs separados; nenhuma alteração em Usuario ou seus vínculos."""
from alembic import op
import sqlalchemy as sa

revision = "20261111_0009"
down_revision = "20261110_0008"
branch_labels = None
depends_on = None


def _otp_table(name):
    op.create_table(
        name,
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("code_hash", sa.String(128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def upgrade() -> None:
    op.create_table(
        "contas_globais",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email_verificado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_contas_globais_email"),
        sa.CheckConstraint("email = lower(trim(email))", name="ck_contas_globais_email_normalizado"),
    )
    _otp_table("otp_cadastro")
    _otp_table("otp_login_global")
    op.create_table(
        "sessoes_globais",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conta_id", sa.Integer(), sa.ForeignKey("contas_globais.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sessoes_globais_conta_id", "sessoes_globais", ["conta_id"])
    op.create_index("ix_sessoes_globais_token_hash", "sessoes_globais", ["token_hash"], unique=True)
    op.create_index("ix_sessoes_globais_expires_at", "sessoes_globais", ["expires_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrade exige plano manual para preservar contas e sessões globais.")
