"""Liveness is independent; readiness reports unavailable dependencies safely."""

import asyncio
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis
from app.core.config import settings
from app.core.database import async_session_maker
from app.models.compliance import CanonicalProvision
from app.schemas.compliance import HealthResponse, ReadinessComponent, ReadinessResponse
from fastapi import APIRouter, Response
from sqlalchemy import func, select
from worker.heartbeat import WORKER_HEARTBEAT_KEY

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="ok", service="workplace-compliance-api", timestamp=datetime.now(timezone.utc)
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(response: Response):
    components = {}
    corpus_ready = False
    try:
        # Allow a cold TLS connection plus the schema/content round trip.
        # A warm check on the configured remote database can already take ~4s.
        async with asyncio.timeout(10):
            async with async_session_maker() as db:
                count = (
                    await db.execute(select(func.count(CanonicalProvision.provision_id)))
                ).scalar() or 0
            components["database"] = ReadinessComponent(
                status=True, details="Neon PostgreSQL responsive"
            )
            corpus_ready = count > 0
            components["corpus"] = ReadinessComponent(
                status=corpus_ready, details=f"{count} canonical provisions"
            )
    except Exception:
        corpus_ready = False
        components["database"] = ReadinessComponent(
            status=False, details="Database configuration, connection, or schema unavailable"
        )
        components["corpus"] = ReadinessComponent(
            status=False, details="Canonical corpus unavailable"
        )
    r = redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
    try:
        await r.ping()
        components["redis"] = ReadinessComponent(status=True, details="Queue broker responsive")
        alive = bool(await r.get(WORKER_HEARTBEAT_KEY))
        components["worker"] = ReadinessComponent(
            status=alive,
            details="Processing worker responsive" if alive else "Processing worker unavailable",
        )
    except Exception:
        components["redis"] = ReadinessComponent(status=False, details="Queue broker unavailable")
        components["worker"] = ReadinessComponent(
            status=False, details="Worker presence unavailable"
        )
    finally:
        await r.aclose()
    if settings.RETRIEVAL_MODE == "lexical":
        components["chroma"] = ReadinessComponent(
            status=True, details="Lexical retrieval enabled; vector service optional"
        )
    else:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                result = await client.get(
                    f"http://{settings.CHROMA_HOST}:{settings.CHROMA_PORT}/api/v1/heartbeat"
                )
                result.raise_for_status()
            components["chroma"] = ReadinessComponent(
                status=True, details="Vector service responsive"
            )
        except Exception:
            components["chroma"] = ReadinessComponent(
                status=False, details="Vector service unavailable"
            )
    components["authentication"] = ReadinessComponent(
        status=bool(settings.AUTH_CLIENT_TOKENS),
        details="Client tokens configured"
        if settings.AUTH_CLIENT_TOKENS
        else "Client tokens missing",
    )
    infra_ok = all(
        components[name].status
        for name in ("database", "redis", "worker", "chroma", "authentication")
    )
    if not infra_ok:
        response.status_code = 503
    return ReadinessResponse(
        status="ready" if infra_ok else "not_ready",
        infrastructure_ready=infra_ok,
        corpus_ready=corpus_ready,
        components=components,
        timestamp=datetime.now(timezone.utc),
    )
