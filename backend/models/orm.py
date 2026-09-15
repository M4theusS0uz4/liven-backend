import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
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


class Unidade(Base):
    __tablename__ = "unidades"
    __table_args__ = (UniqueConstraint("bloco", "numero", name="uq_unidades_bloco_numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bloco: Mapped[str] = mapped_column(String(30), index=True)
    numero: Mapped[str] = mapped_column(String(20))
    andar: Mapped[int | None] = mapped_column(Integer)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    moradores: Mapped[list["Morador"]] = relationship(back_populates="unidade")


class Morador(Base):
    __tablename__ = "moradores"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id", ondelete="RESTRICT"), index=True)
    nome: Mapped[str] = mapped_column(String(150))
    cpf: Mapped[str | None] = mapped_column(String(14), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    telefone: Mapped[str | None] = mapped_column(String(25))
    foto_facial_path: Mapped[str | None] = mapped_column(String(500))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unidade: Mapped["Unidade"] = relationship(back_populates="moradores")
    entregas: Mapped[list["Entrega"]] = relationship(back_populates="morador")


class Entrega(Base):
    __tablename__ = "entregas"

    id: Mapped[int] = mapped_column(primary_key=True)
    morador_id: Mapped[int] = mapped_column(ForeignKey("moradores.id", ondelete="RESTRICT"), index=True)
    codigo_retirada: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    transportadora: Mapped[str | None] = mapped_column(String(100))
    remetente: Mapped[str | None] = mapped_column(String(150))
    descricao: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StatusEntrega] = mapped_column(Enum(StatusEntrega, name="status_entrega"), default=StatusEntrega.RECEBIDA)
    recebida_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retirada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recebido_por: Mapped[str | None] = mapped_column(String(150))
    morador: Mapped["Morador"] = relationship(back_populates="entregas")


class Acesso(Base):
    __tablename__ = "registros_acesso"

    id: Mapped[int] = mapped_column(primary_key=True)
    morador_id: Mapped[int | None] = mapped_column(ForeignKey("moradores.id", ondelete="SET NULL"), index=True)
    unidade_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id", ondelete="SET NULL"), index=True)
    visitante_nome: Mapped[str | None] = mapped_column(String(150))
    metodo: Mapped[MetodoAcesso] = mapped_column(Enum(MetodoAcesso, name="metodo_acesso"))
    permitido: Mapped[bool] = mapped_column(Boolean)
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    observacao: Mapped[str | None] = mapped_column(Text)
