"""
config.py — Configuração do M3 lida de variáveis de ambiente (ou de um .env).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="M3_", extra="ignore")

    app_nome: str = "M3 - Priorização"
    log_level: str = "INFO"

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"
    exchange: str = "denuncias"
    fila: str = "m3.priorizacao"
    routing_classificada: str = "denuncia.classificada"   # consome do M2
    routing_recorrencia: str = "padrao.recorrencia"       # consome do M4
    routing_out: str = "denuncia.priorizada"              # publica p/ M5, M6, M7
    prefetch: int = 8

    # PostgreSQL (banco PRÓPRIO do M3 — database-per-service)
    database_url: str = "postgresql+asyncpg://m3:m3@db-m3:5432/priorizacao"
    criar_tabelas_no_startup: bool = True

    # Thresholds de nível de prioridade (score 0-100)
    limiar_critico: float = 75.0
    limiar_alto: float = 55.0
    limiar_medio: float = 35.0

    # Intervalo do relay do outbox (segundos)
    relay_intervalo: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
