from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from ai_core.api.router import api_router
from ai_core.config import settings
from ai_core.db import close_pool
from ai_core.middleware.auth import AuthMiddleware
from ai_core.middleware.license_check import LicenseCheckMiddleware
from ai_core.middleware.metrics import MetricsMiddleware, metrics_router
from ai_core.middleware.rate_limit import limiter
from ai_core.middleware.request_id import RequestIdMiddleware
from ai_core.middleware.security_headers import SecurityHeadersMiddleware

# Configure structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ai_core.startup", environment=settings.environment)
    yield
    logger.info("ai_core.shutdown")
    await close_pool()


app = FastAPI(
    title="SoulForge AI Core",
    description="Prompt Builder, RAG Engine, AI Pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware stack (order matters — outermost first)
# 1. Request ID (outermost — always applied, traces every request)
app.add_middleware(RequestIdMiddleware)

# 2. Metrics — record request count, latency, errors
app.add_middleware(MetricsMiddleware)

# 3. Security headers
app.add_middleware(SecurityHeadersMiddleware)

# 4. CORS — configured from environment, not wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Service-Token", "X-Brand-Id", "X-Request-ID"],
)

# 5-6. Auth + License — Starlette wraps middleware in reverse order,
# so the LAST added middleware runs FIRST. We want Auth to run before
# LicenseCheck, so LicenseCheck must be added BEFORE Auth.
app.add_middleware(LicenseCheckMiddleware)  # runs second (needs auth context)
app.add_middleware(AuthMiddleware)          # runs first (sets request.state.auth)

app.include_router(api_router)
app.include_router(metrics_router)
