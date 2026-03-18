from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from gateway.config import settings
from gateway.protocols.registry import registry
from gateway.protocols.xiaozhi import XiaozhiAdapter
from gateway.protocols.web_audio import WebAudioAdapter
from gateway.protocols.generic_ws import GenericWSAdapter
from gateway.server import WebSocketServer

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

# Register protocol adapters
registry.register(XiaozhiAdapter())
registry.register(WebAudioAdapter())
registry.register(GenericWSAdapter())

# Create server
ws_server = WebSocketServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("gateway.startup")
    await ws_server.startup()
    yield
    logger.info("gateway.shutdown")
    await ws_server.shutdown()


app = FastAPI(
    title="SoulForge Gateway",
    description="WebSocket gateway with pluggable protocol adapters",
    version="0.1.0",
    lifespan=lifespan,
)


# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health():
    protocols = [a.name for a in registry.adapters]
    return {"status": "ok", "service": "gateway", "protocols": protocols}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_server.handle_connection(ws)
