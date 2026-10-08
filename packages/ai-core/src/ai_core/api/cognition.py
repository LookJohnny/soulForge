"""Internal runtime bridge to the authoritative AI Core personality loop."""

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from soulforge_harness.runtime.identity import RuntimeIdentity
from soulforge_harness.runtime.models import EventKind

from ai_core.db import get_pool
from ai_core.dependencies import (
    get_cache,
    get_emotion_engine,
    get_llm_client,
    get_memory_service,
    get_prompt_builder,
    get_relationship_engine,
    get_tone_reader,
)
from ai_core.middleware.rate_limit import limiter
from ai_core.services.character_projection import validate_runtime_identity
from ai_core.services.cognition import (
    CognitionInputRejected,
    CognitionPreempted,
    CognitionService,
    CognitionUnavailable,
)

router = APIRouter(prefix="/cognition", tags=["cognition"])
logger = structlog.get_logger()


class CognitionIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    character_id: UUID
    agent_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    body_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)


class CognitionEvent(BaseModel):
    kind: EventKind
    source: str = Field(default="runtime", max_length=100)
    text: str = Field(default="", max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)
    t_min: float = Field(default=0, allow_inf_nan=False)
    target_agent: str | None = Field(default=None, max_length=100)

    @field_validator("payload")
    @classmethod
    def bounded_payload(cls, value):
        if len(json.dumps(value, ensure_ascii=False)) > 24000:
            raise ValueError("event payload exceeds 24000 characters")
        return value


class CognitionRequest(BaseModel):
    identity: CognitionIdentity
    persona: dict[str, Any] = Field(default_factory=dict)
    world: dict[str, Any] = Field(default_factory=dict)
    event: CognitionEvent
    current_template: str = Field(default="idle", max_length=100)
    current_interruptible: bool = True
    available_actions: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("persona", "world")
    @classmethod
    def bounded_context(cls, value):
        if len(json.dumps(value, ensure_ascii=False)) > 24000:
            raise ValueError("context exceeds 24000 characters")
        return value

    @field_validator("available_actions")
    @classmethod
    def bounded_actions(cls, value):
        if any(not action or len(action) > 64 for action in value):
            raise ValueError("action names must contain 1-64 characters")
        return value


def _brand_and_identity(req: CognitionRequest, request: Request) -> tuple[str, dict]:
    auth = getattr(request.state, "auth", None)
    if not auth or auth.source != "service" or not auth.brand_id:
        raise HTTPException(status_code=403, detail="Internal service authentication required")
    try:
        brand_id = str(UUID(auth.brand_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=403, detail="Valid brand context required") from None
    identity = req.identity.model_dump(mode="json")
    if req.event.target_agent not in (None, identity["agent_id"]):
        raise HTTPException(status_code=422, detail="Event targets a different agent")
    return brand_id, identity


async def _service(brand_id: str, identity: dict) -> CognitionService:
    pool = await get_pool()
    await validate_runtime_identity(pool, brand_id, RuntimeIdentity(**identity))
    builder, memory, relationships, llm = await asyncio.gather(
        get_prompt_builder(), get_memory_service(), get_relationship_engine(), get_llm_client()
    )
    return CognitionService(
        builder=builder,
        memory=memory,
        relationships=relationships,
        llm=llm,
        emotion=get_emotion_engine(),
        cache=get_cache(),
        tone_reader=get_tone_reader(),
    )


def _decide_args(req: CognitionRequest, brand_id: str, identity: dict) -> dict:
    return {
        "identity": identity,
        "brand_id": brand_id,
        "persona": req.persona,
        "world": req.world,
        "event": req.event.model_dump(mode="json"),
        "current_template": req.current_template,
        "current_interruptible": req.current_interruptible,
        "available_actions": req.available_actions,
    }


def _http_error(exc: Exception) -> HTTPException:
    """The one mapping from a failed decision to a status (shared by both endpoints)."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail="Runtime identity is not authorized")
    if isinstance(exc, CognitionPreempted):
        return HTTPException(status_code=409, detail={"code": "preempted"})
    if isinstance(exc, CognitionInputRejected):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, CognitionUnavailable):
        # The reason is our own validation message (or a JSON parser position),
        # never user input: it tells which contract rule a model keeps missing.
        logger.warning(
            "cognition.invalid_decision",
            error_type=type(exc.__cause__).__name__,
            reason=str(exc.__cause__)[:160],
        )
        return HTTPException(
            status_code=503,
            detail={
                "code": "invalid_behavior_decision",
                "message": "Model output failed behavior validation",
            },
        )
    # No mock speech, provider URL, credential, or user content in errors.
    logger.warning("cognition.unavailable", error_type=type(exc).__name__)
    return HTTPException(status_code=503, detail="Cognition is temporarily unavailable")


@router.post("/decide")
@limiter.limit("60/minute")
async def decide(req: CognitionRequest, request: Request):
    brand_id, identity = _brand_and_identity(req, request)
    try:
        service = await _service(brand_id, identity)
        return await service.decide(**_decide_args(req, brand_id, identity))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/decide/stream")
@limiter.limit("60/minute")
async def decide_stream(req: CognitionRequest, request: Request):
    """The same decision, streamed as NDJSON so speech starts before it is complete.

    {"type": "line", "line": {agent, text, emotion, tone_readout?}}
        each dialogue line, as soon as it is complete
    {"type": "result", ...}
        the /decide response; its dialogue is exactly the streamed lines
    {"type": "error", "status": int, "detail": ...}
        failure (after any lines, which were already spoken)
    Authentication and identity errors are ordinary HTTP errors before the stream starts."""
    brand_id, identity = _brand_and_identity(req, request)
    try:
        service = await _service(brand_id, identity)
    except Exception as exc:
        raise _http_error(exc) from exc
    queue: asyncio.Queue = asyncio.Queue()

    async def on_line(line: dict) -> None:
        await queue.put({"type": "line", "line": line})

    async def run() -> None:
        try:
            result = await service.decide(**_decide_args(req, brand_id, identity), on_line=on_line)
            await queue.put({"type": "result", **result})
        except Exception as exc:
            error = _http_error(exc)
            await queue.put({"type": "error", "status": error.status_code, "detail": error.detail})
        finally:
            await queue.put(None)

    async def body():
        task = asyncio.create_task(run())
        try:
            while (item := await queue.get()) is not None:
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            if not task.done():
                task.cancel()  # the runtime hung up: stop generating

    return StreamingResponse(
        body(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no"}
    )
