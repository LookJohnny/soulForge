import asyncio
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from gateway.config import settings
from gateway.http_auth import require_gateway_token
from gateway.media_api import MediaSessions, build_router as build_media_router
from gateway.plugins import load_plugins
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
media_sessions = MediaSessions(ws_server.orchestrator)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("gateway.startup")
    load_plugins()
    await ws_server.startup()
    media_gc = asyncio.create_task(media_sessions.housekeeping())
    try:
        yield
    finally:
        logger.info("gateway.shutdown")
        media_gc.cancel()
        with suppress(asyncio.CancelledError):
            await media_gc
        await media_sessions.close_all()
        await ws_server.shutdown()


app = FastAPI(
    title="SoulForge Gateway",
    description="WebSocket gateway with pluggable protocol adapters",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(build_media_router(media_sessions))


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


@app.post("/v1/chat/completions", dependencies=[Depends(require_gateway_token)])
async def openai_compat_chat(request: Request):
    """OpenAI-compatible shim over the Character Runtime brain (SSE).

    Lets any renderer that speaks "custom LLM" (Tavus CVI, etc.) borrow our
    soul: persona, memory, PAD and decisions all run in the 8765 brain — the
    external service is just a face."""
    import json as _json
    import uuid as _uuid

    from starlette.responses import StreamingResponse

    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        raise HTTPException(status_code=400, detail="messages must be an array")
    user_text = ""
    for message in reversed(body.get("messages", [])):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, list):  # multimodal envelope
            content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        user_text = str(content).strip()
        if user_text:
            break

    if not user_text or len(user_text) > 4000:
        raise HTTPException(
            status_code=400, detail="A user message of 1-4000 characters is required"
        )
    if not settings.character_runtime_url:
        raise HTTPException(status_code=503, detail="Character Runtime is not configured")
    # This is only a conversation label. The authenticated deployment owns user
    # identity; a caller cannot choose another end_user_id using OpenAI's `user`.
    session_label = body.get("user") or request.headers.get("X-Conversation-Id") or "local"
    if not isinstance(session_label, str) or len(session_label) > 128:
        raise HTTPException(status_code=400, detail="Invalid conversation label")
    try:
        decision = await ws_server.orchestrator.process_external_utterance(
            user_text,
            body_id="tavus-face",
            session_id=session_label,
        )
    except Exception:
        logger.exception("openai_compat.brain_error")
        raise HTTPException(status_code=502, detail="Character Runtime request failed") from None
    reply = str(decision.get("text") or "").strip()
    if not reply:
        raise HTTPException(status_code=502, detail="Character Runtime returned no dialogue")
    # Delivery of text is not proof that the external face played audio. The
    # orchestrator owns external delivery receipts; this route never marks spoken.

    completion_id = "chatcmpl-" + _uuid.uuid4().hex[:24]
    model_name = body.get("model", "soulforge-brain")

    if not body.get("stream", False):
        return {
            "id": completion_id,
            "object": "chat.completion",
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
        }

    def _chunk(delta, finish=None):
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "model": model_name,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return "data: " + _json.dumps(payload, ensure_ascii=False) + "\n\n"

    async def generate():
        # Compatibility framing of a completed decision, not token-streaming LLM output.
        yield _chunk({"role": "assistant"})
        for start in range(0, len(reply), 24):
            yield _chunk({"content": reply[start : start + 24]})
        yield _chunk({}, finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/admin/runtime-agent", dependencies=[Depends(require_gateway_token)])
async def switch_runtime_agent(payload: dict):
    """Hot-swap which Character-Runtime agent this gateway voices (Lane B).

    The soul-swap demo installs a new persona into the running brain and then
    points the voice body at it — no process restarts, memory intact."""
    agent_id = str(payload.get("agent_id") or "").strip()
    if not agent_id:
        return {"ok": False, "error": "agent_id required"}
    orchestrator = ws_server.orchestrator
    if settings.soulforge_brand_id:
        try:
            await orchestrator._resolve_runtime_identity("admin", "switch", agent_id)
        except Exception:
            raise HTTPException(
                status_code=422, detail="Character must be projected before switching"
            ) from None
    await orchestrator.reset_runtime_bridges()
    settings.character_runtime_agent = agent_id
    from gateway.pipeline.orchestrator import PipelineOrchestrator

    PipelineOrchestrator._runtime_voice_cache = None  # re-read voice binding
    logger.info("gateway.runtime_agent_switched", agent_id=agent_id)
    return {"ok": True, "agent_id": agent_id}


@app.get("/metrics/latency")
async def latency_metrics():
    """Voice-turn latency: speech-end → first Opus frame, plus ai-core stage breakdown."""
    from gateway.latency import latency_tracker

    return latency_tracker.snapshot()


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
    fallback = settings.ota_fallback_host or f"localhost:{settings.gateway_port}"
    host = request.headers.get("host", fallback)
    response = {
        "websocket": {
            "url": f"ws://{host}/ws",
        },
        "firmware": {
            "version": "0.0.0",
        },
        "server_time": {
            "timestamp": int(_time.time()),
            "timezone_offset": settings.ota_timezone_offset_min,
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
