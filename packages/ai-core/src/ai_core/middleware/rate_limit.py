"""Rate limiting middleware using slowapi with Redis backend."""

import structlog
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

from ai_core.config import settings

logger = structlog.get_logger()


def _get_rate_limit_key(request: Request) -> str:
    """Extract rate limit key from request.

    Priority:
    1. Authenticated user/brand from auth middleware (per-user limiting)
    2. X-Forwarded-For header (real client IP behind proxy)
    3. Client IP (fallback)
    """
    # Per-user/brand limiting if authenticated
    auth = getattr(request.state, "auth", None)
    if auth:
        if auth.user_id:
            return f"user:{auth.user_id}"
        if auth.brand_id:
            return f"brand:{auth.brand_id}"

    # Real IP from proxy headers
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # Direct client IP
    if request.client:
        return request.client.host
    return "unknown"


# Use Redis as storage backend for distributed rate limiting
_storage_uri = settings.redis_url if settings.redis_url else None

limiter = Limiter(
    key_func=_get_rate_limit_key,
    storage_uri=_storage_uri,
    strategy="fixed-window",
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": str(exc.detail),
        },
    )
