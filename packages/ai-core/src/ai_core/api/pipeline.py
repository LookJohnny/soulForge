"""Full chat pipeline: (ASR) -> Content Filter -> Prompt Build -> LLM -> Content Filter -> (TTS).

Integrates emotion tracking and conversation memory.
"""

import asyncio
import base64
import time

import structlog
from fastapi import APIRouter, HTTPException, Request

from ai_core.dependencies import (
    get_asr_client, get_llm_client, get_prompt_builder, get_tts_client,
    get_emotion_engine, get_memory_service,
)
from ai_core.middleware.rate_limit import limiter
from ai_core.models.schemas import ChatRequest, ChatResponse
from ai_core.services.content_filter import ContentFilter

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = structlog.get_logger()
content_filter = ContentFilter()

# 10 MB max for decoded audio
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

    # 2. Content safety check on input
    is_safe, reason = content_filter.check_input(user_text)
    if not is_safe:
        logger.warning("content_filter.blocked_input", reason=reason)
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    # 3. Retrieve emotion state and memories
    emotion_engine = get_emotion_engine()
    emotion_state = await emotion_engine.get_emotion(req.session_id)

    memories = []
    memory_service = await get_memory_service()
    if req.end_user_id:
        memories = await memory_service.retrieve_memories(req.end_user_id, req.character_id)

    # 4. Build prompt (with emotion + memories)
    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            end_user_id=req.end_user_id,
            user_input=user_text,
            emotion_state=emotion_state,
            memories=memories,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 5. LLM inference
    llm = await get_llm_client()
    ai_text = await llm.chat(
        system_prompt=prompt_result["system_prompt"],
        user_input=user_text,
    )

    # 6. Content safety filter on output (PII + blocked content)
    ai_text = content_filter.filter_output(ai_text)

    # 7. Detect emotion from response and store
    new_emotion = emotion_engine.detect_emotion(ai_text, previous=emotion_state)
    await emotion_engine.set_emotion(req.session_id, new_emotion)

    # 8. TTS synthesis with emotion-adjusted parameters
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

    # 9. Async memory extraction (fire-and-forget, non-blocking)
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

    latency = int((time.monotonic() - start) * 1000)
    logger.info(
        "pipeline.chat",
        latency_ms=latency,
        character_id=req.character_id,
        emotion=new_emotion,
    )

    return ChatResponse(
        text=ai_text,
        audio_data=audio_b64,
        emotion=new_emotion,
        latency_ms=latency,
    )
