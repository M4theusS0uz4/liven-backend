import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base


class StatusEntrega(str, enum.Enum):
    RECEBIDA = "recebida"
    NOTIFICADA = "notificada"
    RETIRADA = "retirada"
    DEVOLVIDA = "devolvida"


class MetodoAcesso(str, enum.Enum):
    FACIAL = "facial"
    QR_CODE = "qr_code"
    MANUAL = "manual"


class PerfilUsuario(str, enum.Enum):
    MORADOR = "morador"
    PORTARIA = "portaria"
    SINDICO = "sindico"


class StatusAutorizacao(str, enum.Enum):
    ATIVA = "ativa"
    REVOGADA = "revogada"
    EXPIRADA = "expirada"


class StatusOcorrencia(str, enum.Enum):
    ABERTA = "aberta"
    EM_ANALISE = "em_analise"
    RESOLVIDA = "resolvida"


class CategoriaOcorrencia(str, enum.Enum):
    MANUTENCAO = "manutencao"
    SEGURANCA = "seguranca"
    LIMPEZA = "limpeza"
    BARULHO = "barulho"
    OUTRO = "outro"


class PrioridadeOcorrencia(str, enum.Enum):
    NORMAL = "normal"
    ALTA = "alta"
    URGENTE = "urgente"


class PublicoComunicado(str, enum.Enum):
    TODOS = "todos"
    BLOCO = "bloco"
    UNIDADE = "unidade"
    PERFIL = "perfil"


class Condominio(Base):
    __tablename__ = "condominios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unidades: Mapped[list["Unidade"]] = relationship(back_populates="condominio")
    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="condominio")


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("condominio_id", "telefone", name="uq_usuarios_condominio_telefone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    telefone: Mapped[str] = mapped_column(String(25))
    nome: Mapped[str] = mapped_column(String(150))
    perfil: Mapped[PerfilUsuario] = mapped_column(String(20), default=PerfilUsuario.MORADOR)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    condominio: Mapped[Condominio] = relationship(back_populates="usuarios")
    morador: Mapped["Morador | None"] = relationship(back_populates="usuario", uselist=False)
    porteiro: Mapped["Porteiro | None"] = relationship(back_populates="usuario", uselist=False)


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    telefone: Mapped[str] = mapped_column(String(25), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    requested_ip: Mapped[str | None] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    acao: Mapped[str] = mapped_column(String(100))
    recurso: Mapped[str] = mapped_column(String(100))
    recurso_id: Mapped[int | None] = mapped_column(Integer)
    endereco_ip: Mapped[str | None] = mapped_column(String(64))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Unidade(Base):
    __tablename__ = "unidades"
    __table_args__ = (UniqueConstraint("bloco", "numero", name="uq_unidades_bloco_numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    bloco: Mapped[str] = mapped_column(String(150), index=True)
    numero: Mapped[str] = mapped_column(String(30))
    andar: Mapped[int | None] = mapped_column(Integer)
    tipo_residencia: Mapped[str] = mapped_column(String(20), default="apartamento", server_default="apartamento")
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    condominio: Mapped[Condominio] = relationship(back_populates="unidades")
    moradores: Mapped[list["Morador"]] = relationship(back_populates="unidade")


class Morador(Base):
    __tablename__ = "moradores"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), unique=True, index=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), index=True)
    nome: Mapped[str] = mapped_column(String(150))
    cpf: Mapped[str | None] = mapped_column(String(14), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    telefone: Mapped[str | None] = mapped_column(String(25))
    foto_facial_path: Mapped[str | None] = mapped_column(String(500))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unidade: Mapped["Unidade"] = relationship(back_populates="moradores")
    usuario: Mapped["Usuario | None"] = relationship(back_populates="morador")
    entregas: Mapped[list["Entrega"]] = relationship(back_populates="morador")


class Entrega(Base):
    __tablename__ = "entregas"

    id: Mapped[int] = mapped_column(primary_key=True)
    morador_id: Mapped[int] = mapped_column(ForeignKey("moradores.id", ondelete="RESTRICT"), index=True)
    codigo_retirada: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    transportadora: Mapped[str | None] = mapped_column(String(100))
    remetente: Mapped[str | None] = mapped_column(String(150))
    descricao: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StatusEntrega] = mapped_column(
        Enum(StatusEntrega, name="status_entrega", values_callable=lambda valores: [valor.value for valor in valores]),
        default=StatusEntrega.RECEBIDA,
    )
    recebida_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retirada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recebido_por: Mapped[str | None] = mapped_column(String(150))
    morador: Mapped["Morador"] = relationship(back_populates="entregas")


class Acesso(Base):
    __tablename__ = "registros_acesso"

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int | None] = mapped_column(ForeignKey("condominios.id", ondelete="SET NULL"), index=True)
    visitante_id: Mapped[int | None] = mapped_column(ForeignKey("visitantes.id", ondelete="SET NULL"), index=True)
    autorizacao_id: Mapped[int | None] = mapped_column(ForeignKey("autorizacoes_acesso.id", ondelete="SET NULL"), index=True)
    morador_id: Mapped[int | None] = mapped_column(ForeignKey("moradores.id", ondelete="SET NULL"), index=True)
    unidade_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id", ondelete="SET NULL"), index=True)
    visitante_nome: Mapped[str | None] = mapped_column(String(150))
    evento: Mapped[str] = mapped_column(String(24), default="entrada", server_default="entrada")
    registrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    metodo: Mapped[MetodoAcesso] = mapped_column(
        Enum(MetodoAcesso, name="metodo_acesso", values_callable=lambda valores: [valor.value for valor in valores])
    )
    permitido: Mapped[bool] = mapped_column(Boolean)
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    observacao: Mapped[str | None] = mapped_column(Text)


class Porteiro(Base):
    __tablename__ = "porteiros"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), unique=True, index=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    turno: Mapped[str] = mapped_column(String(40), default="Manhã", server_default="Manhã")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    usuario: Mapped[Usuario] = relationship(back_populates="porteiro")


class Visitante(Base):
    __tablename__ = "visitantes"

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(150))
    telefone: Mapped[str | None] = mapped_column(String(25))
    placa: Mapped[str | None] = mapped_column(String(16))
    documento: Mapped[str | None] = mapped_column(String(32))
    criado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Veiculo(Base):
    __tablename__ = "veiculos"
    __table_args__ = (UniqueConstraint("condominio_id", "placa", name="uq_veiculos_condominio_placa"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    morador_id: Mapped[int | None] = mapped_column(ForeignKey("moradores.id", ondelete="SET NULL"), index=True)
    placa: Mapped[str] = mapped_column(String(10))
    marca: Mapped[str | None] = mapped_column(String(80))
    modelo: Mapped[str] = mapped_column(String(100))
    cor: Mapped[str | None] = mapped_column(String(50))
    vaga: Mapped[str | None] = mapped_column(String(30))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    morador: Mapped["Morador | None"] = relationship()


class AutorizacaoAcesso(Base):
    __tablename__ = "autorizacoes_acesso"

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    visitante_id: Mapped[int] = mapped_column(ForeignKey("visitantes.id", ondelete="CASCADE"), index=True)
    morador_id: Mapped[int] = mapped_column(ForeignKey("moradores.id", ondelete="CASCADE"), index=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), index=True)
    criado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[StatusAutorizacao] = mapped_column(String(20), default=StatusAutorizacao.ATIVA)
    metodo_visita: Mapped[str] = mapped_column(String(20), default="qr", server_default="qr")
    estado_visita: Mapped[str] = mapped_column(String(20), default="authorized", server_default="authorized", index=True)
    limite_usos: Mapped[int] = mapped_column(Integer, default=1)
    usos: Mapped[int] = mapped_column(Integer, default=0)
    revogada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QrCode(Base):
    __tablename__ = "qr_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    autorizacao_id: Mapped[int] = mapped_column(ForeignKey("autorizacoes_acesso.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    codigo: Mapped[str | None] = mapped_column(String(128), unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    limite_usos: Mapped[int] = mapped_column(Integer, default=1)
    usos: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegistroFacial(Base):
    __tablename__ = "registros_faciais"

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    visitante_id: Mapped[int] = mapped_column(ForeignKey("visitantes.id", ondelete="CASCADE"), index=True)
    autorizacao_id: Mapped[int] = mapped_column(ForeignKey("autorizacoes_acesso.id", ondelete="CASCADE"), index=True)
    referencia_hash: Mapped[str] = mapped_column(String(128))
    consentimento_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comunicado(Base):
    __tablename__ = "comunicados"

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    autor_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    titulo: Mapped[str] = mapped_column(String(180))
    mensagem: Mapped[str] = mapped_column(Text)
    publico: Mapped[PublicoComunicado] = mapped_column(String(20), default=PublicoComunicado.TODOS)
    bloco: Mapped[str | None] = mapped_column(String(30))
    unidade_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id", ondelete="CASCADE"), index=True)
    perfil: Mapped[PerfilUsuario | None] = mapped_column(String(20))
    publicado: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    arquivado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComunicadoLeitura(Base):
    __tablename__ = "comunicado_leituras"
    __table_args__ = (UniqueConstraint("comunicado_id", "usuario_id", name="uq_comunicado_leitura"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comunicado_id: Mapped[int] = mapped_column(ForeignKey("comunicados.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    lido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ocorrencia(Base):
    __tablename__ = "ocorrencias"

    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominios.id", ondelete="CASCADE"), index=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), index=True)
    autor_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"), index=True)
    titulo: Mapped[str] = mapped_column(String(180))
    descricao: Mapped[str] = mapped_column(Text)
    categoria: Mapped[CategoriaOcorrencia] = mapped_column(String(20))
    prioridade: Mapped[PrioridadeOcorrencia] = mapped_column(String(20), default=PrioridadeOcorrencia.NORMAL)
    status: Mapped[StatusOcorrencia] = mapped_column(String(20), default=StatusOcorrencia.ABERTA, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OcorrenciaHistorico(Base):
    __tablename__ = "ocorrencias_historico"

    id: Mapped[int] = mapped_column(primary_key=True)
    ocorrencia_id: Mapped[int] = mapped_column(ForeignKey("ocorrencias.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    status_anterior: Mapped[str | None] = mapped_column(String(20))
    status_novo: Mapped[str] = mapped_column(String(20))
    comentario: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OcorrenciaComentario(Base):
    __tablename__ = "ocorrencias_comentarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    ocorrencia_id: Mapped[int] = mapped_column(ForeignKey("ocorrencias.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    texto: Mapped[str] = mapped_column(Text)
    interno: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Mapa(Base):
    __tablename__ = "mapas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150))
    tipo_condominio: Mapped[str] = mapped_column(String(20), default="vertical", server_default="vertical")
    largura: Mapped[float] = mapped_column(Float, default=100.0, server_default="100")
    altura: Mapped[float] = mapped_column(Float, default=100.0, server_default="100")
    unidades: Mapped[list["MapaUnidade"]] = relationship(back_populates="mapa", cascade="all, delete-orphan")
    blocos: Mapped[list["MapaBloco"]] = relationship(back_populates="mapa", cascade="all, delete-orphan")
    ruas: Mapped[list["MapaRua"]] = relationship(back_populates="mapa", cascade="all, delete-orphan")
    areas_comuns: Mapped[list["MapaAreaComum"]] = relationship(back_populates="mapa", cascade="all, delete-orphan")
    portarias: Mapped[list["MapaPortaria"]] = relationship(back_populates="mapa", cascade="all, delete-orphan")


class MapaUnidade(Base):
    __tablename__ = "mapa_unidades"
    __table_args__ = (UniqueConstraint("mapa_id", "unidade_id", name="uq_mapa_unidades_mapa_unidade"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mapa_id: Mapped[int] = mapped_column(ForeignKey("mapas.id", ondelete="CASCADE"), index=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="CASCADE"), index=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    largura: Mapped[float] = mapped_column(Float)
    altura: Mapped[float] = mapped_column(Float)
    rotacao: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    mapa: Mapped[Mapa] = relationship(back_populates="unidades")
    unidade: Mapped[Unidade] = relationship()


class MapaBloco(Base):
    __tablename__ = "mapa_blocos"

    id: Mapped[int] = mapped_column(primary_key=True)
    mapa_id: Mapped[int] = mapped_column(ForeignKey("mapas.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(100))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    largura: Mapped[float] = mapped_column(Float)
    altura: Mapped[float] = mapped_column(Float)
    andares: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    mapa: Mapped[Mapa] = relationship(back_populates="blocos")


class MapaRua(Base):
    __tablename__ = "mapa_ruas"

    id: Mapped[int] = mapped_column(primary_key=True)
    mapa_id: Mapped[int] = mapped_column(ForeignKey("mapas.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(150))
    largura: Mapped[float] = mapped_column(Float)
    pontos: Mapped[list["MapaRuaPonto"]] = relationship(back_populates="rua", cascade="all, delete-orphan", order_by="MapaRuaPonto.ordem")
    mapa: Mapped[Mapa] = relationship(back_populates="ruas")


class MapaRuaPonto(Base):
    __tablename__ = "mapa_ruas_pontos"

    id: Mapped[int] = mapped_column(primary_key=True)
    rua_id: Mapped[int] = mapped_column(ForeignKey("mapa_ruas.id", ondelete="CASCADE"), index=True)
    ordem: Mapped[int] = mapped_column(Integer)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    rua: Mapped[MapaRua] = relationship(back_populates="pontos")


class MapaAreaComum(Base):
    __tablename__ = "mapa_areas_comuns"

    id: Mapped[int] = mapped_column(primary_key=True)
    mapa_id: Mapped[int] = mapped_column(ForeignKey("mapas.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(150))
    tipo: Mapped[str] = mapped_column(String(80))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    largura: Mapped[float] = mapped_column(Float)
    altura: Mapped[float] = mapped_column(Float)
    mapa: Mapped[Mapa] = relationship(back_populates="areas_comuns")


class MapaPortaria(Base):
    __tablename__ = "mapa_portarias"

    id: Mapped[int] = mapped_column(primary_key=True)
    mapa_id: Mapped[int] = mapped_column(ForeignKey("mapas.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(150))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    mapa: Mapped[Mapa] = relationship(back_populates="portarias")
