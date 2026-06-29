"""
messaging.py — Transporte RabbitMQ do M3 (consumidor + produtor), via aio-pika.

Topologia:
    exchange `denuncias` (topic, durável)
      ├─ fila `m3.priorizacao`  (bind: denuncia.classificada)   <- do M2
      │                         (bind: padrao.recorrencia)       <- do M4
      │     x-dead-letter-exchange -> `denuncias.dlx`
      └─ (publica com routing key `denuncia.priorizada`)         -> M5, M6, M7

A fila única com dois bindings permite que ambos os tipos de evento entrem
na mesma fila. O dispatcher lê o routing key da mensagem e chama o handler certo.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from .config import Settings

logger = logging.getLogger("m3.messaging")

Handler = Callable[[bytes], Awaitable[None]]
# dispatcher: recebe (routing_key, body) e decide qual handler chamar
Dispatcher = Callable[[str, bytes], Awaitable[None]]


class Mensageria:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._conn: aio_pika.RobustConnection | None = None
        self._canal: aio_pika.abc.AbstractRobustChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._fila: aio_pika.abc.AbstractQueue | None = None

    async def conectar(self) -> None:
        self._conn = await aio_pika.connect_robust(self.cfg.rabbitmq_url)
        self._canal = await self._conn.channel()
        await self._canal.set_qos(prefetch_count=self.cfg.prefetch)

        self._exchange = await self._canal.declare_exchange(
            self.cfg.exchange, aio_pika.ExchangeType.TOPIC, durable=True
        )

        # Dead-letter
        dlx_nome = f"{self.cfg.exchange}.dlx"
        dlq_nome = f"{self.cfg.fila}.dlq"
        dlx = await self._canal.declare_exchange(
            dlx_nome, aio_pika.ExchangeType.TOPIC, durable=True
        )
        dlq = await self._canal.declare_queue(dlq_nome, durable=True)
        await dlq.bind(dlx, routing_key="#")

        # Fila única com dois bindings (denuncia.classificada e padrao.recorrencia)
        self._fila = await self._canal.declare_queue(
            self.cfg.fila,
            durable=True,
            arguments={"x-dead-letter-exchange": dlx_nome},
        )
        await self._fila.bind(self._exchange, routing_key=self.cfg.routing_classificada)
        await self._fila.bind(self._exchange, routing_key=self.cfg.routing_recorrencia)

        logger.info(
            "Mensageria pronta: fila=%s <- [%s, %s] | publica %s | prefetch=%d",
            self.cfg.fila,
            self.cfg.routing_classificada,
            self.cfg.routing_recorrencia,
            self.cfg.routing_out,
            self.cfg.prefetch,
        )

    async def consumir(self, dispatcher: Dispatcher) -> None:
        """Inicia o consumo. Passa (routing_key, body) ao dispatcher."""
        assert self._fila is not None, "chame conectar() antes de consumir()"

        async def _on_message(message: AbstractIncomingMessage) -> None:
            async with message.process(requeue=False):
                await dispatcher(message.routing_key or "", message.body)

        await self._fila.consume(_on_message)

    async def publicar(self, payload: dict, routing_key: str | None = None) -> None:
        assert self._exchange is not None, "chame conectar() antes de publicar()"
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await self._exchange.publish(
            aio_pika.Message(
                body=corpo,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key or self.cfg.routing_out,
        )

    async def fechar(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            logger.info("Conexão com o RabbitMQ fechada.")

    @property
    def conectado(self) -> bool:
        return self._conn is not None and not self._conn.is_closed
