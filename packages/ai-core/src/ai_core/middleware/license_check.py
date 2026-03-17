"""License enforcement middleware — checks quota before processing requests."""

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


class LicenseCheckMiddleware(BaseHTTPMiddleware):
    """Check license quotas on conversation endpoints.

    Requires brand_id header or defaults to a free-tier check.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only check conversation endpoints
        if path not in CONVERSATION_PATHS:
            return await call_next(request)

        brand_id = request.headers.get("x-brand-id", "")
        if not brand_id:
            # No brand context — skip quota check (direct API usage)
            return await call_next(request)

        # Get current usage
        current = await usage_meter.get_count(brand_id, "conversation")

        # Get brand tier (for now, default to FREE)
        # In production, fetch from DB via cached lookup
        tier = "FREE"
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
