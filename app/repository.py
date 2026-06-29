"""
repository.py — Acesso ao banco do M3.

Duas entidades:
  - DenunciaPriorizadaDB  : inserção/upsert de priorização, marcação de publicado
  - PadraoRecorrenciaDB   : upsert de padrões de recorrência vindos do M4
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert  # usado em upsert_priorizacao
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DenunciaPriorizadaDB, PadraoRecorrenciaDB


# ---------------------------------------------------------------------------
# Denúncias priorizadas
# ---------------------------------------------------------------------------
async def upsert_priorizacao(session: AsyncSession, dados: dict) -> None:
    stmt = pg_insert(DenunciaPriorizadaDB).values(**dados)
    atualizaveis = {
        c: stmt.excluded[c]
        for c in (
            "categoria", "area_responsavel", "confianca", "certeza", "revisar",
            "score", "nivel", "urgencia_categoria", "peso_confianca",
            "boost_recorrencia", "classificado_em", "priorizado_em",
            # "publicado" ausente: não resetar se já foi publicado com sucesso
        )
    }
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=atualizaveis)
    await session.execute(stmt)
    await session.commit()


async def marcar_publicado(session: AsyncSession, denuncia_id: str) -> None:
    stmt = (
        update(DenunciaPriorizadaDB)
        .where(DenunciaPriorizadaDB.id == denuncia_id)
        .values(publicado=True)
    )
    await session.execute(stmt)
    await session.commit()


async def listar_nao_publicados(
    session: AsyncSession, limite: int = 100
) -> list[DenunciaPriorizadaDB]:
    q = (
        select(DenunciaPriorizadaDB)
        .where(DenunciaPriorizadaDB.publicado.is_(False))
        .order_by(DenunciaPriorizadaDB.priorizado_em.asc())
        .limit(limite)
    )
    return list((await session.execute(q)).scalars().all())


async def buscar_por_id(
    session: AsyncSession, denuncia_id: str
) -> DenunciaPriorizadaDB | None:
    return await session.get(DenunciaPriorizadaDB, denuncia_id)


async def listar(
    session: AsyncSession,
    limite: int = 50,
    offset: int = 0,
    nivel: str | None = None,
    area: str | None = None,
) -> list[DenunciaPriorizadaDB]:
    q = select(DenunciaPriorizadaDB).order_by(
        DenunciaPriorizadaDB.score.desc(),
        DenunciaPriorizadaDB.priorizado_em.desc(),
    )
    if nivel:
        q = q.where(DenunciaPriorizadaDB.nivel == nivel.upper())
    if area:
        q = q.where(DenunciaPriorizadaDB.area_responsavel == area)
    q = q.limit(limite).offset(offset)
    return list((await session.execute(q)).scalars().all())


async def contar_total(session: AsyncSession) -> int:
    return (
        await session.execute(select(func.count()).select_from(DenunciaPriorizadaDB))
    ).scalar_one()


async def contagem_por_nivel(session: AsyncSession) -> list[tuple[str, int]]:
    q = (
        select(DenunciaPriorizadaDB.nivel, func.count())
        .group_by(DenunciaPriorizadaDB.nivel)
        .order_by(func.count().desc())
    )
    return [(nivel, n) for nivel, n in (await session.execute(q)).all()]


# ---------------------------------------------------------------------------
# Padrões de recorrência (cópia local dos eventos do M4)
# ---------------------------------------------------------------------------
async def _upsert_padrao_manual(session: AsyncSession, dados: dict) -> None:
    """UPSERT manual por (categoria, regiao) — sem constraint composta no schema."""
    existente = await _buscar_padrao(session, dados["categoria"], dados["regiao"])
    if existente is None:
        session.add(PadraoRecorrenciaDB(**dados))
    else:
        existente.contagem = dados["contagem"]
        existente.janela_tempo = dados["janela_tempo"]
        # atualizado_em é tratado pelo onupdate do SQLAlchemy
    await session.commit()


async def _buscar_padrao(
    session: AsyncSession, categoria: str, regiao: str
) -> PadraoRecorrenciaDB | None:
    q = select(PadraoRecorrenciaDB).where(
        PadraoRecorrenciaDB.categoria == categoria,
        PadraoRecorrenciaDB.regiao == regiao,
    )
    return (await session.execute(q)).scalar_one_or_none()


async def maior_contagem_por_categoria(
    session: AsyncSession, categoria: str
) -> int:
    """Retorna a maior contagem de recorrência registrada para uma categoria."""
    q = select(func.max(PadraoRecorrenciaDB.contagem)).where(
        PadraoRecorrenciaDB.categoria == categoria
    )
    resultado = (await session.execute(q)).scalar_one_or_none()
    return resultado or 0
