"""Full chat pipeline: (ASR) -> Content Filter -> Prompt Build -> LLM -> Content Filter -> (TTS)."""

import base64
import time

import structlog
from fastapi import APIRouter, HTTPException, Request

from ai_core.dependencies import get_asr_client, get_llm_client, get_prompt_builder, get_tts_client
from ai_core.middleware.rate_limit import limiter
from ai_core.models.schemas import ChatRequest, ChatResponse
from ai_core.services.content_filter import ContentFilter

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = structlog.get_logger()
content_filter = ContentFilter()


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(req: ChatRequest, request: Request):
    start = time.monotonic()

    # 1. Determine user text input
    user_text = req.text_input
    if not user_text and req.audio_data:
        asr = await get_asr_client()
        audio_bytes = base64.b64decode(req.audio_data)
        user_text = await asr.recognize(audio_bytes)

    if not user_text:
        raise HTTPException(status_code=400, detail="No input provided (text or audio)")

    # 2. Content safety check on input
    is_safe, reason = content_filter.check_input(user_text)
    if not is_safe:
        logger.warning("content_filter.blocked_input", reason=reason)
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    # 3. Build prompt
    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            end_user_id=req.end_user_id,
            user_input=user_text,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 4. LLM inference
    llm = await get_llm_client()
    ai_text = await llm.chat(
        system_prompt=prompt_result["system_prompt"],
        user_input=user_text,
    )

    # 5. Content safety filter on output (PII redaction)
    ai_text = content_filter.filter_output(ai_text)

    # 6. TTS synthesis (optional, if voice configured)
    audio_b64 = None
    if prompt_result.get("voice_id"):
        tts = await get_tts_client()
        audio_bytes = await tts.synthesize(
            text=ai_text,
            voice=prompt_result["voice_id"],
            speed=prompt_result.get("voice_speed", 1.0),
        )
        audio_b64 = base64.b64encode(audio_bytes).decode()

    latency = int((time.monotonic() - start) * 1000)
    logger.info("pipeline.chat", latency_ms=latency, character_id=req.character_id)

    return ChatResponse(
        text=ai_text,
        audio_data=audio_b64,
        latency_ms=latency,
    )
