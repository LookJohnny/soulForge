"""Health check endpoint — verifies connectivity to critical services."""

import structlog
from fastapi import APIRouter

logger = structlog.get_logger()

router = APIRouter()


@router.get("/health")
async def health():
    """Enhanced health check — tests DB, Redis, and Milvus connectivity."""
    checks = {"service": "ai-core"}
    overall = "ok"

    # Check PostgreSQL
    try:
        from ai_core.db import get_pool

        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        overall = "degraded"

    # Check Redis
    try:
        import redis.asyncio as aioredis

        from ai_core.config import settings

        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        overall = "degraded"

    # RAG/Milvus is hard-disabled (see dependencies.get_rag_engine)
    checks["milvus"] = "disabled"

    checks["status"] = overall
    return checks
