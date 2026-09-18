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
   may only shade its behaviour without ever being quoted. Vidu's protocol has no
   such distinction: everything returned lands in the model's context as a tool
   result that it is free to read out.

   Marking the implicit ones and instructing the model to keep them to itself was
   tried first, and a live session disproved it. Seeded with an implicit-only
   "用户最近在服用抗焦虑药物舍曲林" and asked "我最近在吃什么药吗？", the
   character answered "记得你最近在吃舍曲林，是抗焦虑的药" — the marker and the
   tool instruction were both ignored. A privacy boundary a third-party model can
   choose to ignore is not a boundary.

   So implicit memories no longer leave this process. What ships in their place
   is the behaviour they imply — "语气放轻、不要追问" — derived by the memory
   service's own hint builder, which carries no trace of the underlying fact. The
   worst case becomes a character that is oddly gentle, not one that reads your
   prescription aloud.
"""

from __future__ import annotations

import time

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

# Sent as memory_retrieval.tool_instruction when the session is created.
#
# Deliberately short. An earlier version tried to police disclosure from here and
# the model ignored it, so nothing private is entrusted to these words any more —
# everything this endpoint returns is already safe to say out loud. What is left
# is guidance that only costs naturalness if disobeyed.
MEMORY_TOOL_INSTRUCTION = (
    "检索结果里的 type=style 是对你说话方式的要求，照做，但不要读出来、"
    "也不要解释你为什么这样说。其余条目是关于用户的事实，可以自然地提及。\n"
    "没有检索到任何记忆时，就说你记不清了，不要编造用户的日程、经历或偏好。\n"
    "不要提起你在检索记忆这件事。"
)

# Non-disclosing behaviour directives derived from implicit-only memories. The
# key is a robot_behavior_hints speech_policy; the value never names the fact
# that produced it.
_SPEECH_POLICY_DIRECTIVES = {
    "low_disturbance": ("对方近期状态可能比较脆弱：语气放轻、节奏放慢，少追问，允许沉默和留白。"),
    "direct": "对方偏好直接：先说结论，少铺垫，不要绕。",
}


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


def _confidence(item: dict) -> float | None:
    """Vidu's ``confidence`` means trustworthiness, on the 0..1 scale its docs show.

    That is ``confidence_score``, not ``retrieval_score`` — the latter is
    unbounded relevance for one query and routinely exceeds 1.0, which would read
    as an out-of-range value to the model.
    """
    raw = item.get("confidence_score")
    if raw is None:
        return None
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return None


def _behaviour_directives(pack: dict) -> list[dict]:
    """Turn implicit-only memories into directives that do not name their cause.

    ``robot_behavior_hints`` is already built from the implicit and compiled
    entries by the memory service, and holds only a policy label — never the
    sentence behind it. That label is the most we can safely hand to a model we
    do not control.
    """
    hints = pack.get("robot_behavior_hints") or {}
    policy = hints.get("speech_policy")
    text = _SPEECH_POLICY_DIRECTIVES.get(policy)
    if not text:
        return []
    return [
        {
            "id": f"behaviour:{policy}",
            "summary": text,
            "type": _COMPILED_RULE_TYPE,
            "confidence": None,
            "source": "soulforge_behaviour_hint",
        }
    ]


def _to_vidu_memory(item: dict, vidu_type: str) -> dict:
    """Render one pack entry that is already cleared for disclosure.

    Only ever called for ``direct`` and ``compiled_rules``; implicit entries never
    reach it. ``prompt_text`` is still preferred over raw ``content`` because its
    ``[可自然提及]`` / ``[编译行为规则]`` prefix tells the model which of the two
    it is holding, but nothing private depends on that prefix being honoured.
    """
    return {
        "id": str(item.get("id") or ""),
        "summary": item.get("prompt_text") or item.get("content") or "",
        "type": vidu_type,
        "confidence": _confidence(item),
        "source": "soulforge_companion_memory",
    }


@router.post("/memory/retrieve")
async def vidu_memory_retrieve(
    req: ViduMemoryRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    """External Memory callback for a Vidu S2-Avatar realtime session."""
    started = time.perf_counter()
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

    # Only DIRECT_SURFACE memories travel as themselves. Their content is, by the
    # policy layer's own decision, something the character may say.
    for item in pack.get("direct", []):
        vidu_type = _LAYER_TO_VIDU_TYPE.get(item.get("memory_layer", ""), "other")
        if wanted and vidu_type not in wanted:
            continue
        memories.append(_to_vidu_memory(item, vidu_type))

    # Compiled rules describe how to speak, not facts about the user, so the worst
    # case if one is read aloud is awkwardness rather than disclosure.
    for item in pack.get("compiled_rules", []):
        if wanted and _COMPILED_RULE_TYPE not in wanted:
            continue
        memories.append(_to_vidu_memory(item, _COMPILED_RULE_TYPE))

    # Implicit-only memories stop here. Their behavioural shadow goes instead.
    implicit = pack.get("implicit", [])
    for directive in _behaviour_directives(pack):
        if wanted and _COMPILED_RULE_TYPE not in wanted:
            continue
        memories.append(directive)

    memories = memories[: req.max_results]

    logger.info(
        "vidu.memory.retrieved",
        live_id=req.live_id,
        end_user_id=end_user_id,
        returned=len(memories),
        direct=len(pack.get("direct", [])),
        # Withheld, not returned: implicit memories are represented only by the
        # behaviour directive, if any.
        implicit_withheld=len(implicit),
        blocked=pack.get("blocked_count", 0),
        # The model's own words for what it went looking for, and how long we
        # took: Vidu abandons the tool call past memory_retrieval.timeout_ms and
        # the character then answers from nothing, so slow is the same as absent.
        query=req.query,
        reason=req.reason,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )
    return {"memories": memories}
