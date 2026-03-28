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


# ─── Xiaozhi OTA compatibility endpoint ────────────────
# Xiaozhi firmware calls /ota/ on boot to get server config.
# We return the SoulForge gateway's WebSocket URL so the device connects here.
@app.post("/ota/")
@app.get("/ota/")
async def xiaozhi_ota(request: Request):
    """Xiaozhi OTA compatibility — return SoulForge WebSocket config."""
    import time as _time
    body = await request.body()
    logger.info(
        "ota.request",
        method=request.method,
        device_id=request.headers.get("device-id", ""),
        body_len=len(body),
    )
    host = request.headers.get("host", "192.168.1.172:8080")
    response = {
        "websocket": {
            "url": f"ws://{host}/ws",
        },
        "firmware": {
            "version": "0.0.0",
        },
        "server_time": {
            "timestamp": int(_time.time()),
            "timezone_offset": 480,
        },
    }
    logger.info("ota.response", ws_url=response["websocket"]["url"])
    return response


@app.post("/ota/{path:path}")
@app.get("/ota/{path:path}")
async def xiaozhi_ota_subpath(path: str, request: Request):
    """Catch all OTA sub-paths (e.g. /ota/activate)."""
    import time as _time
    body = await request.body()
    logger.info("ota.subpath", path=path, body_len=len(body))
    return {
        "server_time": {
            "timestamp": int(_time.time()),
            "timezone_offset": 480,
        },
        "activation": {
            "code": "",
            "message": "already activated",
        },
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_server.handle_connection(ws)
