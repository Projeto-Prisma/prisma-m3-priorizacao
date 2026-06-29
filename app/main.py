"""
main.py — Ciclo de vida do serviço M3.

Startup:
  1. Cria tabelas no banco próprio (priorizacao)
  2. Conecta ao RabbitMQ e começa a consumir denuncia.classificada + padrao.recorrencia
  3. Inicia o relay do outbox (republica denuncia.priorizada que ficou pendente)

Rodar local:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import repository
from .config import get_settings
from .db import SessionLocal, criar_tabelas, engine
from .messaging import Mensageria
from .processing import fazer_dispatcher
from .routes import router
from .schemas import DenunciaPriorizada

cfg = get_settings()
logging.basicConfig(
    level=cfg.log_level,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("m3")


async def _relay_pendentes(mensageria: Mensageria) -> None:
    """Republica eventos denuncia.priorizada que ficaram com publicado=False."""
    async with SessionLocal() as session:
        pendentes = await repository.listar_nao_publicados(session)

    if not pendentes:
        return

    logger.info("Relay: %d evento(s) pendente(s).", len(pendentes))
    for den in pendentes:
        try:
            payload = DenunciaPriorizada(
                id=den.id,
                score=den.score,
                nivel=den.nivel,
                categoria=den.categoria,
                area_responsavel=den.area_responsavel,
                urgencia_categoria=den.urgencia_categoria,
                peso_confianca=den.peso_confianca,
                boost_recorrencia=den.boost_recorrencia,
                priorizado_em=den.priorizado_em,
            )
            await mensageria.publicar(payload.model_dump(mode="json"))
            async with SessionLocal() as session:
                await repository.marcar_publicado(session, den.id)
            logger.info("Relay: %s republicado.", den.id)
        except Exception as e:
            logger.error("Relay: falha ao republicar %s: %s", den.id, e)


async def _loop_relay(mensageria: Mensageria) -> None:
    while True:
        if mensageria.conectado:
            try:
                await _relay_pendentes(mensageria)
            except Exception as e:
                logger.error("Relay: erro inesperado: %s", e)
        await asyncio.sleep(cfg.relay_intervalo)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) banco
    if cfg.criar_tabelas_no_startup:
        await criar_tabelas()
        logger.info("Tabelas verificadas/criadas no PostgreSQL.")

    # 2) mensageria + consumidor + relay
    mensageria = Mensageria(cfg)
    app.state.mensageria = mensageria
    task_relay: asyncio.Task | None = None
    await mensageria.conectar()
    await mensageria.consumir(fazer_dispatcher(mensageria))
    task_relay = asyncio.create_task(_loop_relay(mensageria))
    logger.info(
        "Consumindo [%s, %s] — M3 no ar.",
        cfg.routing_classificada, cfg.routing_recorrencia,
    )

    yield

    if task_relay is not None:
        task_relay.cancel()
        try:
            await task_relay
        except asyncio.CancelledError:
            pass
    await mensageria.fechar()
    await engine.dispose()
    logger.info("M3 finalizado.")


app = FastAPI(title=cfg.app_nome, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/", tags=["infra"])
async def raiz():
    return {"modulo": cfg.app_nome, "docs": "/docs", "health": "/health"}
