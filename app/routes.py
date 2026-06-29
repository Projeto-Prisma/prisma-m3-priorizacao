"""
routes.py — Endpoints HTTP do M3.

API de apoio: observabilidade, consulta da base própria e priorização avulsa.
O painel da gestão (M8) lê o agregado do M7; estes endpoints servem para demo e debug.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import repository
from .db import get_session
from .schemas import ContagemNivel, DenunciaPriorizada, PriorizacaoArmazenada
from .scoring import calcular

router = APIRouter()


@router.get("/health", tags=["infra"])
async def health(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    mensageria = getattr(request.app.state, "mensageria", None)
    broker_ok = bool(mensageria and mensageria.conectado)

    db_ok = False
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    if not db_ok:
        response.status_code = 503

    return {
        "status": "ok" if db_ok else "degradado",
        "db_ok": db_ok,
        "mensageria_conectada": broker_ok,
    }


@router.get("/info", tags=["infra"])
async def info():
    from .config import get_settings
    from .scoring import _URGENCIA, _URGENCIA_DEFAULT

    cfg = get_settings()
    return {
        "modulo": cfg.app_nome,
        "consome": [cfg.routing_classificada, cfg.routing_recorrencia],
        "publica": cfg.routing_out,
        "thresholds": {
            "CRITICO": cfg.limiar_critico,
            "ALTO": cfg.limiar_alto,
            "MEDIO": cfg.limiar_medio,
            "BAIXO": f"< {cfg.limiar_medio}",
        },
        "urgencia_por_area": {**_URGENCIA, "_default": _URGENCIA_DEFAULT},
    }


@router.post("/priorizar", response_model=DenunciaPriorizada, tags=["priorização"])
async def priorizar_avulso(
    area_responsavel: str = Query(...),
    certeza: str = Query("Média"),
    confianca: float = Query(0.5, ge=0, le=1),
    contagem_recorrencias: int = Query(0, ge=0),
):
    """Calcula prioridade avulsa (sem mensageria, sem persistência). Útil p/ testar."""
    from datetime import datetime, timezone

    resultado = calcular(area_responsavel, certeza, confianca, contagem_recorrencias)
    return DenunciaPriorizada(
        id="avulso",
        score=resultado.score,
        nivel=resultado.nivel,
        categoria=None,
        area_responsavel=area_responsavel,
        urgencia_categoria=resultado.urgencia_categoria,
        peso_confianca=resultado.peso_confianca,
        boost_recorrencia=resultado.boost_recorrencia,
        priorizado_em=datetime.now(timezone.utc),
    )


@router.get("/denuncias", response_model=list[PriorizacaoArmazenada], tags=["consulta"])
async def listar_denuncias(
    limite: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    nivel: str | None = Query(None, description="Filtra por nível: CRITICO|ALTO|MEDIO|BAIXO"),
    area: str | None = Query(None, description="Filtra por área responsável"),
    session: AsyncSession = Depends(get_session),
):
    return await repository.listar(session, limite, offset, nivel, area)


@router.get("/denuncias/{denuncia_id}", response_model=PriorizacaoArmazenada, tags=["consulta"])
async def obter_denuncia(denuncia_id: str, session: AsyncSession = Depends(get_session)):
    den = await repository.buscar_por_id(session, denuncia_id)
    if den is None:
        raise HTTPException(status_code=404, detail="Denúncia não encontrada")
    return den


@router.get("/stats", tags=["consulta"])
async def stats(session: AsyncSession = Depends(get_session)):
    total = await repository.contar_total(session)
    por_nivel = await repository.contagem_por_nivel(session)
    return {
        "total": total,
        "por_nivel": [ContagemNivel(nivel=n, total=c) for n, c in por_nivel],
    }
