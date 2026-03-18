"""Full chat pipeline: (ASR) -> Filter -> Prompt(emotion+memory+relationship) -> LLM -> Filter -> (TTS).

Integrates: emotion tracking, conversation memory, relationship evolution,
personality drift, and proactive triggers.
"""

import asyncio
import base64
import json
import time

import structlog
from fastapi import APIRouter, HTTPException, Request

from ai_core.dependencies import (
    get_asr_client, get_llm_client, get_prompt_builder, get_tts_client,
    get_emotion_engine, get_memory_service, get_cache,
    get_relationship_engine, get_personality_drift, get_proactive_trigger,
)
from ai_core.middleware.rate_limit import limiter
from ai_core.models.schemas import ChatRequest, ChatResponse
from ai_core.services.content_filter import ContentFilter

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = structlog.get_logger()
content_filter = ContentFilter()

MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(req: ChatRequest, request: Request):
    start = time.monotonic()

    # 1. Determine user text input
    user_text = req.text_input
    if not user_text and req.audio_data:
        audio_bytes = base64.b64decode(req.audio_data)
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=422, detail="Audio data exceeds 10MB limit")
        asr = await get_asr_client()
        user_text = await asr.recognize(audio_bytes)

    if not user_text:
        raise HTTPException(status_code=400, detail="No input provided (text or audio)")

    # 2. Content safety check
    is_safe, reason = content_filter.check_input(user_text)
    if not is_safe:
        logger.warning("content_filter.blocked_input", reason=reason)
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    # 3. Retrieve emotion state
    emotion_engine = get_emotion_engine()
    emotion_state = await emotion_engine.get_emotion(req.session_id)

    # 4. Retrieve memories
    memory_service = await get_memory_service()
    memories = []
    if req.end_user_id:
        memories = await memory_service.retrieve_memories(req.end_user_id, req.character_id)

    # 5. Retrieve relationship state
    rel_engine = await get_relationship_engine()
    rel_state = {"stage": "STRANGER", "affinity": 0}
    if req.end_user_id:
        rel_state = await rel_engine.get_state(req.end_user_id, req.character_id)
        # Limit memories by relationship depth
        depth = rel_engine.get_memory_depth(rel_state["stage"])
        memories = memories[:depth]

    # 6. Proactive trigger (first message of session)
    proactive_line = None
    if req.end_user_id:
        trigger_svc = get_proactive_trigger()
        proactive_line = await trigger_svc.maybe_generate_trigger(
            end_user_id=req.end_user_id,
            character_id=req.character_id,
            session_id=req.session_id,
            relationship_stage=rel_state["stage"],
            memories=memories,
        )

    # 7. Build prompt (personality with drift + emotion + memories + relationship + trigger)
    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            end_user_id=req.end_user_id,
            user_input=user_text,
            emotion_state=emotion_state,
            memories=memories,
            relationship_stage=rel_state["stage"],
            proactive_trigger=proactive_line,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 8. LLM inference
    llm = await get_llm_client()
    ai_text = await llm.chat(
        system_prompt=prompt_result["system_prompt"],
        user_input=user_text,
    )

    # 9. Content safety filter on output
    ai_text = content_filter.filter_output(ai_text)

    # 10. Detect emotion and store
    new_emotion = emotion_engine.detect_emotion(ai_text, previous=emotion_state)
    await emotion_engine.set_emotion(req.session_id, new_emotion)

    # 11. TTS with emotion-adjusted parameters
    audio_b64 = None
    if prompt_result.get("voice_id"):
        ssml_pitch = prompt_result.get("ssml_pitch", 1.0)
        ssml_rate = prompt_result.get("ssml_rate", 1.0)
        ssml_pitch, ssml_rate = emotion_engine.apply_tts_offsets(new_emotion, ssml_pitch, ssml_rate)

        tts = await get_tts_client()
        audio_bytes = await tts.synthesize(
            text=ai_text,
            voice=prompt_result["voice_id"],
            speed=prompt_result.get("voice_speed", 1.0),
            pitch_rate=prompt_result.get("pitch_rate", 0),
            speech_rate=prompt_result.get("speech_rate", 0),
            ssml_pitch=ssml_pitch,
            ssml_rate=ssml_rate,
            ssml_effect=prompt_result.get("ssml_effect", ""),
        )
        audio_b64 = base64.b64encode(audio_bytes).decode()

    # 12. Async post-processing (memory + relationship + drift)
    if req.end_user_id:
        asyncio.create_task(
            memory_service.extract_and_store(
                end_user_id=req.end_user_id,
                character_id=req.character_id,
                session_id=req.session_id,
                user_input=user_text,
                ai_response=ai_text,
            )
        )
        asyncio.create_task(
            _post_turn_processing(
                end_user_id=req.end_user_id,
                character_id=req.character_id,
                session_id=req.session_id,
                new_emotion=new_emotion,
            )
        )

    latency = int((time.monotonic() - start) * 1000)
    logger.info(
        "pipeline.chat",
        latency_ms=latency,
        character_id=req.character_id,
        emotion=new_emotion,
        stage=rel_state["stage"],
    )

    return ChatResponse(
        text=ai_text,
        audio_data=audio_b64,
        emotion=new_emotion,
        relationship_stage=rel_state["stage"],
        affinity=rel_state.get("affinity", 0),
        latency_ms=latency,
    )


async def _post_turn_processing(
    end_user_id: str,
    character_id: str,
    session_id: str,
    new_emotion: str,
) -> None:
    """Async post-turn: relationship scoring + personality drift."""
    try:
        # Relationship scoring
        rel_engine = await get_relationship_engine()
        memory_svc = await get_memory_service()
        memories = await memory_svc.retrieve_memories(end_user_id, character_id, limit=5)
        recent_types = [m["type"] for m in memories[:3]]

        await rel_engine.award_points(
            end_user_id=end_user_id,
            character_id=character_id,
            memory_types=recent_types,
        )

        # Personality drift
        cache = get_cache()
        emotion_key = f"emotion_history:{session_id}"
        raw = await cache.get(emotion_key)
        emotion_list = json.loads(raw) if raw else []
        emotion_list.append(new_emotion)
        await cache.set(emotion_key, json.dumps(emotion_list), ttl=1800)

        drift_svc = await get_personality_drift()
        await drift_svc.compute_and_apply_drift(
            end_user_id=end_user_id,
            character_id=character_id,
            emotion_history=emotion_list,
            memory_types=recent_types,
        )
    except Exception:
        logger.exception("post_turn_processing.error")
