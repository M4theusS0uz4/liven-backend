"""estrutura da plataforma liven

Revision ID: 20260916_0003
Revises: 20260915_0002
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260916_0003"
down_revision = "20260915_0002"
branch_labels = None
depends_on = None


def _created_at():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    op.create_table(
        "condominios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
    )
    op.execute("INSERT INTO condominios (nome, ativo) VALUES ('Condomínio principal', true)")

    op.add_column("unidades", sa.Column("condominio_id", sa.Integer(), nullable=True))
    op.create_index("ix_unidades_condominio_id", "unidades", ["condominio_id"])
    op.create_foreign_key("fk_unidades_condominio", "unidades", "condominios", ["condominio_id"], ["id"], ondelete="CASCADE")
    op.execute("UPDATE unidades SET condominio_id = (SELECT MIN(id) FROM condominios) WHERE condominio_id IS NULL")

    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telefone", sa.String(25), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("perfil", sa.String(20), nullable=False, server_default="morador"),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
        sa.UniqueConstraint("condominio_id", "telefone", name="uq_usuarios_condominio_telefone"),
    )
    op.create_index("ix_usuarios_condominio_id", "usuarios", ["condominio_id"])

    op.add_column("moradores", sa.Column("usuario_id", sa.Integer(), nullable=True))
    op.create_index("ix_moradores_usuario_id", "moradores", ["usuario_id"])
    op.create_foreign_key("fk_moradores_usuario", "moradores", "usuarios", ["usuario_id"], ["id"], ondelete="SET NULL")
    op.add_column("registros_acesso", sa.Column("condominio_id", sa.Integer(), nullable=True))
    op.add_column("registros_acesso", sa.Column("visitante_id", sa.Integer(), nullable=True))
    op.add_column("registros_acesso", sa.Column("autorizacao_id", sa.Integer(), nullable=True))
    op.create_index("ix_registros_acesso_condominio_id", "registros_acesso", ["condominio_id"])
    op.create_index("ix_registros_acesso_visitante_id", "registros_acesso", ["visitante_id"])
    op.create_index("ix_registros_acesso_autorizacao_id", "registros_acesso", ["autorizacao_id"])
    op.create_foreign_key("fk_registros_acesso_condominio", "registros_acesso", "condominios", ["condominio_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telefone", sa.String(25), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("requested_ip", sa.String(64)),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        _created_at(),
    )
    op.create_index("ix_otp_challenges_telefone", "otp_challenges", ["telefone"])
    op.create_index("ix_otp_challenges_expires_at", "otp_challenges", ["expires_at"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _created_at(),
    )
    op.create_index("ix_refresh_tokens_usuario_id", "refresh_tokens", ["usuario_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    op.create_table(
        "porteiros",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
    )
    op.create_index("ix_porteiros_usuario_id", "porteiros", ["usuario_id"])

    op.create_table(
        "visitantes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("telefone", sa.String(25)),
        sa.Column("documento", sa.String(32)),
        sa.Column("criado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
    )
    op.create_index("ix_visitantes_condominio_id", "visitantes", ["condominio_id"])

    op.create_table(
        "autorizacoes_acesso",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visitante_id", sa.Integer(), sa.ForeignKey("visitantes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("morador_id", sa.Integer(), sa.ForeignKey("moradores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unidade_id", sa.Integer(), sa.ForeignKey("unidades.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("criado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ativa"),
        sa.Column("limite_usos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("usos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revogada_em", sa.DateTime(timezone=True)),
        _created_at(),
    )
    op.create_index("ix_autorizacoes_acesso_visitante_id", "autorizacoes_acesso", ["visitante_id"])
    op.create_index("ix_autorizacoes_acesso_morador_id", "autorizacoes_acesso", ["morador_id"])
    op.create_foreign_key("fk_registros_acesso_visitante", "registros_acesso", "visitantes", ["visitante_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_registros_acesso_autorizacao", "registros_acesso", "autorizacoes_acesso", ["autorizacao_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "qr_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("autorizacao_id", sa.Integer(), sa.ForeignKey("autorizacoes_acesso.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limite_usos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("usos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
    )
    op.create_index("ix_qr_codes_autorizacao_id", "qr_codes", ["autorizacao_id"])
    op.create_index("ix_qr_codes_expira_em", "qr_codes", ["expira_em"])
    op.create_table(
        "registros_faciais",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visitante_id", sa.Integer(), sa.ForeignKey("visitantes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("autorizacao_id", sa.Integer(), sa.ForeignKey("autorizacoes_acesso.id", ondelete="CASCADE"), nullable=False),
        sa.Column("referencia_hash", sa.String(128), nullable=False),
        sa.Column("consentimento_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("excluido_em", sa.DateTime(timezone=True)),
        _created_at(),
    )
    op.create_index("ix_registros_faciais_condominio_id", "registros_faciais", ["condominio_id"])
    op.create_index("ix_registros_faciais_visitante_id", "registros_faciais", ["visitante_id"])

    op.create_table(
        "comunicados",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("titulo", sa.String(180), nullable=False),
        sa.Column("mensagem", sa.Text(), nullable=False),
        sa.Column("publico", sa.String(20), nullable=False, server_default="todos"),
        sa.Column("bloco", sa.String(30)),
        sa.Column("unidade_id", sa.Integer(), sa.ForeignKey("unidades.id", ondelete="CASCADE")),
        sa.Column("perfil", sa.String(20)),
        sa.Column("publicado", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("arquivado", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _created_at(),
    )
    op.create_index("ix_comunicados_condominio_id", "comunicados", ["condominio_id"])
    op.create_table(
        "comunicado_leituras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("comunicado_id", sa.Integer(), sa.ForeignKey("comunicados.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lido_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("comunicado_id", "usuario_id", name="uq_comunicado_leitura"),
    )

    op.create_table(
        "ocorrencias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unidade_id", sa.Integer(), sa.ForeignKey("unidades.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("titulo", sa.String(180), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("categoria", sa.String(20), nullable=False),
        sa.Column("prioridade", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="aberta"),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ocorrencias_condominio_id", "ocorrencias", ["condominio_id"])
    op.create_index("ix_ocorrencias_status", "ocorrencias", ["status"])
    op.create_table(
        "ocorrencias_historico",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ocorrencia_id", sa.Integer(), sa.ForeignKey("ocorrencias.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status_anterior", sa.String(20)),
        sa.Column("status_novo", sa.String(20), nullable=False),
        sa.Column("comentario", sa.Text()),
        _created_at(),
    )
    op.create_index("ix_ocorrencias_historico_ocorrencia_id", "ocorrencias_historico", ["ocorrencia_id"])
    op.create_table(
        "ocorrencias_comentarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ocorrencia_id", sa.Integer(), sa.ForeignKey("ocorrencias.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("interno", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _created_at(),
    )

    op.create_table(
        "auditoria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condominio_id", sa.Integer(), sa.ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL")),
        sa.Column("acao", sa.String(100), nullable=False),
        sa.Column("recurso", sa.String(100), nullable=False),
        sa.Column("recurso_id", sa.Integer()),
        sa.Column("endereco_ip", sa.String(64)),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_auditoria_condominio_id", "auditoria", ["condominio_id"])
    op.create_index("ix_auditoria_criado_em", "auditoria", ["criado_em"])


def downgrade() -> None:
    op.drop_table("auditoria")
    op.drop_table("registros_faciais")
    op.drop_table("ocorrencias_comentarios")
    op.drop_table("ocorrencias_historico")
    op.drop_table("ocorrencias")
    op.drop_table("comunicado_leituras")
    op.drop_table("comunicados")
    op.drop_table("qr_codes")
    op.drop_table("autorizacoes_acesso")
    op.drop_table("visitantes")
    op.drop_table("porteiros")
    op.drop_table("refresh_tokens")
    op.drop_table("otp_challenges")
    op.drop_constraint("fk_registros_acesso_condominio", "registros_acesso", type_="foreignkey")
    op.drop_constraint("fk_registros_acesso_autorizacao", "registros_acesso", type_="foreignkey")
    op.drop_constraint("fk_registros_acesso_visitante", "registros_acesso", type_="foreignkey")
    op.drop_index("ix_registros_acesso_autorizacao_id", table_name="registros_acesso")
    op.drop_index("ix_registros_acesso_visitante_id", table_name="registros_acesso")
    op.drop_index("ix_registros_acesso_condominio_id", table_name="registros_acesso")
    op.drop_column("registros_acesso", "autorizacao_id")
    op.drop_column("registros_acesso", "visitante_id")
    op.drop_column("registros_acesso", "condominio_id")
    op.drop_constraint("fk_moradores_usuario", "moradores", type_="foreignkey")
    op.drop_index("ix_moradores_usuario_id", table_name="moradores")
    op.drop_column("moradores", "usuario_id")
    op.drop_table("usuarios")
    op.drop_constraint("fk_unidades_condominio", "unidades", type_="foreignkey")
    op.drop_index("ix_unidades_condominio_id", table_name="unidades")
    op.drop_column("unidades", "condominio_id")
    op.drop_table("condominios")