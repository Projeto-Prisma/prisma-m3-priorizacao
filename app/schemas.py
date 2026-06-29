"""
schemas.py — Contratos de dados (Pydantic) do M3.

Eventos consumidos:
  - DenunciaClassificada  : vem do M2 (denuncia.classificada)
  - PadraoRecorrencia     : vem do M4 (padrao.recorrencia)

Evento publicado:
  - DenunciaPriorizada    : vai para M5, M6, M7 (denuncia.priorizada)
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
class Top3Item(BaseModel):
    categoria: str
    confianca: float = Field(ge=0, le=1)


# ---------------------------------------------------------------------------
# Eventos consumidos
# ---------------------------------------------------------------------------
class DenunciaClassificada(BaseModel):
    """Payload do evento denuncia.classificada, produzido pelo M2."""

    id: str
    assunto_usuario: str | None = None
    categoria: str | None
    categoria_sugerida: str | None = None
    divergencia: bool = False
    area_responsavel: str
    confianca: float = Field(ge=0, le=1)
    certeza: str
    revisar: bool
    top3: list[Top3Item] = []
    localizacao: dict | None = None
    modelo_embeddings: str = ""
    recebido_em: datetime | None = None
    classificado_em: datetime


class PadraoRecorrencia(BaseModel):
    """Payload do evento padrao.recorrencia, produzido pelo M4."""

    categoria: str
    regiao: str                # identificação da região (bairro, hash geográfico, etc.)
    contagem: int = Field(ge=1)
    janela_tempo: str          # ex.: "30d", "7d"
    timestamp: datetime | None = None


# ---------------------------------------------------------------------------
# Evento publicado
# ---------------------------------------------------------------------------
class DenunciaPriorizada(BaseModel):
    """Payload do evento denuncia.priorizada, publicado pelo M3."""

    id: str
    score: float = Field(ge=0, le=100)
    nivel: str                  # CRITICO | ALTO | MEDIO | BAIXO
    categoria: str | None
    area_responsavel: str
    localizacao: dict | None = None
    # Componentes do score (transparência)
    urgencia_categoria: float
    peso_confianca: float
    boost_recorrencia: float
    priorizado_em: datetime


# ---------------------------------------------------------------------------
# API HTTP
# ---------------------------------------------------------------------------
class PriorizacaoArmazenada(BaseModel):
    """Representação de uma denúncia priorizada armazenada no banco do M3."""

    id: str
    categoria: str | None
    area_responsavel: str
    confianca: float
    certeza: str
    revisar: bool
    score: float
    nivel: str
    urgencia_categoria: float
    peso_confianca: float
    boost_recorrencia: float
    classificado_em: datetime | None
    priorizado_em: datetime

    model_config = {"from_attributes": True}


class ContagemNivel(BaseModel):
    nivel: str
    total: int
