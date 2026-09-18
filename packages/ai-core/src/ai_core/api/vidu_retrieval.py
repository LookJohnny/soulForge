"""External retrieval callbacks for Vidu S2-Avatar realtime sessions.

In the realtime edition Vidu runs ASR / LLM / TTS and renders the character, but
``memory_retrieval.provider = "self"`` lets its model call back into SoulForge for
memory instead of using Vidu's own long-term store. That is what keeps the
companion's memory single-sourced: the unified cognition layer stays the only
place a fact about the user lives.

Two things this module has to get right:

1. **Identity.** Vidu's protocol sends only ``live_id`` — no end-user id. The
   binding travels in the ``Authorization`` header, which is configured per
   session at CreateLive time; see :mod:`ai_core.services.vidu_session_token`.

2. **The disclosure boundary.** ``retrieve_memory_pack`` splits results into
   memories the character may mention out loud (``DIRECT_SURFACE``) and ones that
   may only shade its behaviour without being quoted. Vidu's protocol has no such
   distinction — everything returned lands in the model's context as a tool
   result. Handing both kinds over unmarked would let the avatar read a private
   inference aloud, so the marked ``prompt_text`` is what goes on the wire, and
   :data:`MEMORY_TOOL_INSTRUCTION` teaches the model what the markers mean.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ai_core.dependencies import get_memory_service
from ai_core.services.vidu_session_token import (
    ViduTokenError,
    parse_authorization_header,
    verify_session_token,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/vidu", tags=["vidu"])


# SoulForge memory layers → Vidu memory_types. compiled behaviour rules describe
# how the character should speak, which is Vidu's "style".
_LAYER_TO_VIDU_TYPE = {
    "PROFILE": "profile",
    "EPISODIC": "history",
    "SEMANTIC": "preference",
    "RELATIONAL": "relationship",
}
_COMPILED_RULE_TYPE = "style"

# Sent as memory_retrieval.tool_instruction when the session is created, so the
# model reads the markers below as rules rather than as part of the memory text.
MEMORY_TOOL_INSTRUCTION = (
    "检索结果中的每条记忆都带一个方括号标记，必须按标记使用：\n"
    "[可自然提及] —— 可以在对话里直接说出来。\n"
    "[隐性关系策略，不要直说来源] / [隐性长期画像，不要直说来源] / "
    "[隐性长期理解，不要直说来源] / [隐性事件碎片，只在非常相关时才用] —— "
    "只能影响你的态度、语气和选择，绝不能复述内容、引用原话或告诉用户你记得这件事。"
    "被问到时不要承认这条记忆的存在。\n"
    "[编译行为规则] —— 是对你说话方式的要求，照做但不要读出来。\n"
    "没有检索到记忆时照常自然对话，不要提起检索这件事。"
)


class ViduMemoryRequest(BaseModel):
    """Request body defined by Vidu's External Memory protocol."""

    live_id: str = ""
    query: str = ""
    reason: str = ""
    memory_types: list[str] = Field(default_factory=list)
    time_hint: str = ""
    max_results: int = Field(default=5, ge=1, le=10)


def _authenticate(authorization: str | None, live_id: str) -> dict:
    try:
        token = parse_authorization_header(authorization)
        return verify_session_token(token, live_id=live_id or None)
    except ViduTokenError as exc:
        logger.warning("vidu.retrieval.auth_failed", reason=str(exc), live_id=live_id)
        raise HTTPException(status_code=401, detail="invalid session token") from exc


def _to_vidu_memory(item: dict, vidu_type: str) -> dict:
    """Render one pack entry, keeping the disclosure marker in the visible text."""
    return {
        "id": str(item.get("id") or ""),
        # prompt_text, not content: the marker is the privacy contract.
        "summary": item.get("prompt_text") or item.get("content") or "",
        "type": vidu_type,
        "confidence": item.get("retrieval_score"),
        "source": "soulforge_companion_memory",
    }


@router.post("/memory/retrieve")
async def vidu_memory_retrieve(
    req: ViduMemoryRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    """External Memory callback for a Vidu S2-Avatar realtime session."""
    claims = _authenticate(authorization, req.live_id)
    end_user_id = claims["u"]
    character_id = claims.get("c")

    wanted = {t.strip().lower() for t in req.memory_types if t and t.strip()}

    try:
        svc = await get_memory_service()
        pack = await svc.retrieve_memory_pack(
            end_user_id=end_user_id,
            character_id=character_id,
            query=req.query,
            context={"channel": "vidu_live", "live_id": req.live_id, "reason": req.reason},
            limit=req.max_results,
        )
    except Exception as exc:  # noqa: BLE001 - never break the live session
        logger.warning("vidu.memory.retrieve_failed", error=str(exc), live_id=req.live_id)
        # 200 with an empty array: a non-2xx turns into an error tool result and
        # makes the character stumble mid-sentence.
        return {"memories": [], "error": "retrieval_unavailable"}

    memories: list[dict] = []
    for item in pack.get("direct", []):
        vidu_type = _LAYER_TO_VIDU_TYPE.get(item.get("memory_layer", ""), "other")
        if wanted and vidu_type not in wanted:
            continue
        memories.append(_to_vidu_memory(item, vidu_type))
    for item in pack.get("implicit", []):
        vidu_type = _LAYER_TO_VIDU_TYPE.get(item.get("memory_layer", ""), "other")
        if wanted and vidu_type not in wanted:
            continue
        memories.append(_to_vidu_memory(item, vidu_type))
    for item in pack.get("compiled_rules", []):
        if wanted and _COMPILED_RULE_TYPE not in wanted:
            continue
        memories.append(_to_vidu_memory(item, _COMPILED_RULE_TYPE))

    memories = memories[: req.max_results]

    logger.info(
        "vidu.memory.retrieved",
        live_id=req.live_id,
        end_user_id=end_user_id,
        returned=len(memories),
        direct=len(pack.get("direct", [])),
        implicit=len(pack.get("implicit", [])),
        blocked=pack.get("blocked_count", 0),
    )
    return {"memories": memories}
