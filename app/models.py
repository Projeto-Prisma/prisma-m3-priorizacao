"""
models.py — Modelos ORM (SQLAlchemy 2.0) do banco próprio do M3.

Duas tabelas:
  - denuncias_priorizadas : resultado de cada priorização (outbox p/ denuncia.priorizada)
  - padroes_recorrencia   : cópia local dos eventos padrao.recorrencia vindos do M4;
                            guardada aqui para que futuras denúncias na mesma categoria
                            já recebam o boost de recorrência na hora do cálculo do score.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DenunciaPriorizadaDB(Base):
    __tablename__ = "denuncias_priorizadas"

    # id vem do M1 (chave natural); UPSERT garante idempotência
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    categoria: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    area_responsavel: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    confianca: Mapped[float] = mapped_column(Float, nullable=False)
    certeza: Mapped[str] = mapped_column(String(10), nullable=False)
    revisar: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Score composto e seus componentes (transparência da decisão)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    nivel: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    urgencia_categoria: Mapped[float] = mapped_column(Float, nullable=False)
    peso_confianca: Mapped[float] = mapped_column(Float, nullable=False)
    boost_recorrencia: Mapped[float] = mapped_column(Float, nullable=False)

    classificado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priorizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Outbox: se o publish falhar, o relay republica quando o broker voltar
    publicado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )


class PadraoRecorrenciaDB(Base):
    """Cópia local dos padrões de recorrência detectados pelo M4."""

    __tablename__ = "padroes_recorrencia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    categoria: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # Texto livre identificando a região (bairro, logradouro, hash, etc.)
    regiao: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    contagem: Mapped[int] = mapped_column(Integer, nullable=False)
    janela_tempo: Mapped[str] = mapped_column(String(30), nullable=False)

    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
