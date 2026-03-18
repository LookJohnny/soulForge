"""License enforcement middleware — checks quota before processing requests."""

import time
from datetime import date

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ai_core.services import usage_meter

logger = structlog.get_logger()

# Tier limits: {tier: {resource: limit}}
TIER_LIMITS = {
    "FREE": {"max_characters": 3, "max_devices": 10, "max_daily_convos": 100},
    "TRIAL": {"max_characters": 10, "max_devices": 50, "max_daily_convos": 500},
    "PRO": {"max_characters": 999999, "max_devices": 500, "max_daily_convos": 999999},
    "ENTERPRISE": {"max_characters": 999999, "max_devices": 999999, "max_daily_convos": 999999},
}

# Paths that consume conversation quota
CONVERSATION_PATHS = {"/pipeline/chat", "/chat/preview"}

# In-memory tier cache: {brand_id: (tier, expiry_timestamp)}
_tier_cache: dict[str, tuple[str, float]] = {}
_TIER_CACHE_TTL = 3600  # 1 hour


async def _get_brand_tier(brand_id: str) -> str:
    """Get brand tier from DB with in-memory cache (TTL 1h)."""
    now = time.time()

    # Check cache
    cached = _tier_cache.get(brand_id)
    if cached and cached[1] > now:
        return cached[0]

    # Query DB
    try:
        from ai_core.db import get_pool

        pool = await get_pool()
        row = await pool.fetchrow(
            """SELECT tier FROM licenses
               WHERE brand_id = $1
                 AND (expires_at IS NULL OR expires_at > now())
               ORDER BY created_at DESC
               LIMIT 1""",
            brand_id,
        )
        tier = row["tier"] if row else "FREE"
    except Exception as e:
        logger.warning("license.db_lookup_failed", brand_id=brand_id, error=str(e))
        tier = "FREE"

    # Cache result
    _tier_cache[brand_id] = (tier, now + _TIER_CACHE_TTL)
    return tier


class LicenseCheckMiddleware(BaseHTTPMiddleware):
    """Check license quotas on conversation endpoints.

    Uses brand_id from auth context (request.state.auth) instead of trusting headers.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only check conversation endpoints
        if path not in CONVERSATION_PATHS:
            return await call_next(request)

        # Get brand_id from auth context (set by AuthMiddleware)
        auth = getattr(request.state, "auth", None)
        brand_id = auth.brand_id if auth else ""
        if not brand_id:
            return await call_next(request)

        # Get current usage
        current = await usage_meter.get_count(brand_id, "conversation")

        # Get brand tier from DB (cached)
        tier = await _get_brand_tier(brand_id)
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["FREE"])

        if current >= limits["max_daily_convos"]:
            logger.warning(
                "license.quota_exceeded",
                brand_id=brand_id,
                tier=tier,
                current=current,
                limit=limits["max_daily_convos"],
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Daily conversation quota exceeded",
                    "tier": tier,
                    "current": current,
                    "limit": limits["max_daily_convos"],
                },
            )

        response = await call_next(request)

        # Increment usage after successful response
        if response.status_code < 400:
            await usage_meter.increment(brand_id, "conversation")

        return response
