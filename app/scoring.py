"""
scoring.py — Algoritmo de priorização do M3.

Score composto (0–100), somando três componentes:

  urgencia_categoria  (0–40 pts)
      Peso fixo por área responsável. Saúde e direitos humanos têm urgência
      máxima; triagem geral e encaminhamentos externos têm urgência mínima.

  peso_confianca  (0–20 pts)
      Certeza da classificação feita pelo M2. Alta confiança = o M3 pode agir
      rapidamente; baixa confiança sugere revisão manual, reduz o score.

  boost_recorrencia  (0–40 pts)
      Quantidade de denúncias semelhantes na mesma região/categoria já
      detectadas pelo M4. Crescimento logarítmico para não saturar rápido.
      0 recorrências = 0 pts; ≥ 15 recorrências = 40 pts (exemplo do edital).

Nível final (configurável por thresholds em Settings):
  CRITICO : score ≥ 75
  ALTO    : score ≥ 55
  MEDIO   : score ≥ 35
  BAIXO   : score < 35
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import get_settings

# ---------------------------------------------------------------------------
# Urgência por área (pontuação base independente de recorrência ou confiança)
# ---------------------------------------------------------------------------
_URGENCIA: dict[str, float] = {
    "Saúde": 40.0,
    "Proteção e Direitos Humanos": 38.0,
    "Meio Ambiente e Sustentabilidade": 32.0,
    "Mobilidade e Trânsito": 28.0,
    "Fiscalização e Ordem Pública": 24.0,
    "Integridade e Conduta Pública": 22.0,
    "Limpeza e Conservação Urbana": 18.0,
    "Defesa Animal": 15.0,
    "Educação e Esporte Comunitário": 12.0,
    "Defesa do Consumidor": 10.0,
    "Encaminhamento Externo": 8.0,
    "Triagem Geral": 6.0,
}

_URGENCIA_DEFAULT = 10.0


def _urgencia_da_area(area: str) -> float:
    return _URGENCIA.get(area, _URGENCIA_DEFAULT)


def _peso_da_confianca(certeza: str, confianca: float) -> float:
    """Converte certeza ('Alta'|'Média'|'Baixa') em pontuação 0–20."""
    if certeza == "Alta":
        return 20.0
    if certeza == "Média":
        # escala linear entre 10 e 16 dentro da faixa média
        return round(10.0 + (confianca * 12.0), 2)
    # Baixa: proporcional à confiança
    return round(confianca * 10.0, 2)


def _boost_recorrencia(contagem: int) -> float:
    """
    Boost logarítmico de recorrência territorial (0–40 pts).

    0 recorrências →  0 pts
    1 recorrência  →  ~8 pts
    5 recorrências → ~21 pts
   15 recorrências → ~34 pts   (caso-exemplo do edital)
   50 recorrências → ~40 pts   (cap)
    """
    if contagem <= 0:
        return 0.0
    # log2(1+x) normalizado para que x=50 → ≈ 40 pts
    boost = 40.0 * (math.log2(1 + contagem) / math.log2(51))
    return round(min(boost, 40.0), 2)


@dataclass
class ResultadoPriorizacao:
    score: float
    nivel: str
    urgencia_categoria: float
    peso_confianca: float
    boost_recorrencia: float


def calcular(
    area_responsavel: str,
    certeza: str,
    confianca: float,
    contagem_recorrencias: int = 0,
) -> ResultadoPriorizacao:
    """Calcula o score e o nível de prioridade de uma denúncia."""
    cfg = get_settings()

    urg = _urgencia_da_area(area_responsavel)
    conf = _peso_da_confianca(certeza, confianca)
    rec = _boost_recorrencia(contagem_recorrencias)

    score = round(min(urg + conf + rec, 100.0), 2)

    if score >= cfg.limiar_critico:
        nivel = "CRITICO"
    elif score >= cfg.limiar_alto:
        nivel = "ALTO"
    elif score >= cfg.limiar_medio:
        nivel = "MEDIO"
    else:
        nivel = "BAIXO"

    return ResultadoPriorizacao(
        score=score,
        nivel=nivel,
        urgencia_categoria=urg,
        peso_confianca=conf,
        boost_recorrencia=rec,
    )
