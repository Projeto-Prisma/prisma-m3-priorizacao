"""
processing.py — Regra de negócio do M3 para cada tipo de evento recebido.

Dois fluxos:

1) denuncia.classificada (do M2)
   → consulta recorrência local → calcula score → grava (outbox) → publica denuncia.priorizada

2) padrao.recorrencia (do M4)
   → atualiza cópia local dos padrões; não publica nada
   (o boost de recorrência será aplicado às PRÓXIMAS denúncias classificadas)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from . import repository
from .db import SessionLocal
from .messaging import Mensageria
from .schemas import DenunciaClassificada, DenunciaPriorizada, PadraoRecorrencia
from .scoring import calcular

logger = logging.getLogger("m3.processing")


async def _handle_classificada(corpo: bytes, mensageria: Mensageria) -> None:
    """Processa um evento denuncia.classificada."""
    try:
        denuncia = DenunciaClassificada.model_validate_json(corpo)
    except ValidationError as e:
        logger.error("denuncia.classificada inválida, enviando p/ DLQ: %s", e)
        raise

    # Consulta recorrência local para a categoria desta denúncia
    async with SessionLocal() as session:
        contagem_rec = await repository.maior_contagem_por_categoria(
            session, denuncia.categoria or ""
        )

    resultado = calcular(
        area_responsavel=denuncia.area_responsavel,
        certeza=denuncia.certeza,
        confianca=denuncia.confianca,
        contagem_recorrencias=contagem_rec,
    )

    agora = datetime.now(timezone.utc)
    evento = DenunciaPriorizada(
        id=denuncia.id,
        score=resultado.score,
        nivel=resultado.nivel,
        categoria=denuncia.categoria,
        area_responsavel=denuncia.area_responsavel,
        localizacao=denuncia.localizacao,
        urgencia_categoria=resultado.urgencia_categoria,
        peso_confianca=resultado.peso_confianca,
        boost_recorrencia=resultado.boost_recorrencia,
        priorizado_em=agora,
    )

    # Grava no banco (outbox: publicado=False)
    async with SessionLocal() as session:
        await repository.upsert_priorizacao(
            session,
            {
                "id": evento.id,
                "categoria": evento.categoria,
                "area_responsavel": evento.area_responsavel,
                "confianca": denuncia.confianca,
                "certeza": denuncia.certeza,
                "revisar": denuncia.revisar,
                "score": evento.score,
                "nivel": evento.nivel,
                "urgencia_categoria": evento.urgencia_categoria,
                "peso_confianca": evento.peso_confianca,
                "boost_recorrencia": evento.boost_recorrencia,
                "classificado_em": denuncia.classificado_em,
                "priorizado_em": agora,
                "publicado": False,
            },
        )

    # Publica denuncia.priorizada
    try:
        await mensageria.publicar(evento.model_dump(mode="json"))
        async with SessionLocal() as session:
            await repository.marcar_publicado(session, evento.id)
    except Exception as e:
        logger.error(
            "Falha ao publicar denuncia %s (relay vai retentar): %s", evento.id, e
        )

    logger.info(
        "denuncia %s -> score=%.1f nivel=%s area=%s (rec=%d)",
        evento.id, evento.score, evento.nivel, evento.area_responsavel, contagem_rec,
    )


async def _handle_recorrencia(corpo: bytes) -> None:
    """Processa um evento padrao.recorrencia: salva cópia local para uso futuro."""
    try:
        padrao = PadraoRecorrencia.model_validate_json(corpo)
    except ValidationError as e:
        logger.error("padrao.recorrencia inválido, enviando p/ DLQ: %s", e)
        raise

    async with SessionLocal() as session:
        await repository._upsert_padrao_manual(
            session,
            {
                "categoria": padrao.categoria,
                "regiao": padrao.regiao,
                "contagem": padrao.contagem,
                "janela_tempo": padrao.janela_tempo,
            },
        )

    logger.info(
        "padrao.recorrencia atualizado: categoria=%s regiao=%s contagem=%d janela=%s",
        padrao.categoria, padrao.regiao, padrao.contagem, padrao.janela_tempo,
    )


def fazer_dispatcher(mensageria: Mensageria):
    """Cria o dispatcher que roteia cada mensagem para o handler correto."""
    from .config import get_settings
    cfg = get_settings()

    async def dispatcher(routing_key: str, corpo: bytes) -> None:
        if routing_key == cfg.routing_classificada:
            await _handle_classificada(corpo, mensageria)
        elif routing_key == cfg.routing_recorrencia:
            await _handle_recorrencia(corpo)
        else:
            logger.warning("Routing key desconhecida ignorada: %s", routing_key)

    return dispatcher
