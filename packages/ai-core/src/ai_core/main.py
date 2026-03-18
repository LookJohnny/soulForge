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
from ai_core.middleware.rate_limit import limiter
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
# 1. Security headers (outermost — always applied)
app.add_middleware(SecurityHeadersMiddleware)

# 2. CORS — configured from environment, not wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Service-Token", "X-Brand-Id"],
)

# 3. Auth — JWT / API Key / Service Token verification
app.add_middleware(AuthMiddleware)

# 4. License check — quota enforcement (runs after auth, has brand_id from auth)
app.add_middleware(LicenseCheckMiddleware)

app.include_router(api_router)
