"""Chat endpoint — supports history (multi-turn) and streaming."""

import base64
import json
import time

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ai_core.dependencies import get_llm_client, get_prompt_builder, get_tts_client
from ai_core.middleware.rate_limit import limiter

router = APIRouter(prefix="/chat", tags=["chat"])
logger = structlog.get_logger()


class HistoryMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatPreviewRequest(BaseModel):
    character_id: str
    text: str
    history: list[HistoryMessage] = []
    voice: str | None = None
    with_audio: bool = True


class ChatPreviewResponse(BaseModel):
    text: str
    audio_base64: str | None = None
    audio_format: str | None = None
    latency_ms: int = 0


@router.post("/preview", response_model=ChatPreviewResponse)
@limiter.limit("30/minute")
async def chat_preview(req: ChatPreviewRequest, request: Request):
    """Chat with a character (supports multi-turn history)."""
    start = time.monotonic()

    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            user_input=req.text,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Convert history to LLM format
    history = [{"role": m.role, "content": m.content} for m in req.history] if req.history else None

    llm = await get_llm_client()
    ai_text = await llm.chat(
        system_prompt=prompt_result["system_prompt"],
        user_input=req.text,
        history=history,
    )

    # TTS
    audio_b64 = None
    audio_fmt = None
    if req.with_audio:
        voice_id = req.voice or prompt_result.get("voice_id")
        tts = await get_tts_client()
        audio_data = await tts.synthesize_to_wav(
            text=ai_text,
            voice=voice_id,
            speed=prompt_result.get("voice_speed", 1.0),
            pitch_rate=prompt_result.get("pitch_rate", 0),
            speech_rate=prompt_result.get("speech_rate", 0),
            instruction=prompt_result.get("voice_instruction", ""),
        )
        audio_b64 = base64.b64encode(audio_data).decode()
        audio_fmt = "mp3" if audio_data[:3] == b"ID3" or (audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0) else "wav"

    latency = int((time.monotonic() - start) * 1000)

    return ChatPreviewResponse(
        text=ai_text,
        audio_base64=audio_b64,
        audio_format=audio_fmt,
        latency_ms=latency,
    )


@router.post("/preview/stream")
@limiter.limit("30/minute")
async def chat_preview_stream(req: ChatPreviewRequest, request: Request):
    """Streaming chat — returns SSE events with text chunks, then audio."""

    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            user_input=req.text,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    history = [{"role": m.role, "content": m.content} for m in req.history] if req.history else None

    async def event_stream():
        llm = await get_llm_client()
        full_text = ""

        # Stream text chunks
        async for chunk in llm.chat_stream(
            system_prompt=prompt_result["system_prompt"],
            user_input=req.text,
            history=history,
        ):
            full_text += chunk
            yield f"data: {json.dumps({'type': 'text', 'chunk': chunk}, ensure_ascii=False)}\n\n"

        # TTS after text is complete
        if req.with_audio and full_text:
            voice_id = req.voice or prompt_result.get("voice_id")
            try:
                tts = await get_tts_client()
                audio_data = await tts.synthesize_to_wav(
                    text=full_text,
                    voice=voice_id,
                    speed=prompt_result.get("voice_speed", 1.0),
                    pitch_rate=prompt_result.get("pitch_rate", 0),
                    speech_rate=prompt_result.get("speech_rate", 0),
                    instruction=prompt_result.get("voice_instruction", ""),
                )
                audio_b64 = base64.b64encode(audio_data).decode()
                audio_fmt = "mp3" if audio_data[:3] == b"ID3" or (audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0) else "wav"
                yield f"data: {json.dumps({'type': 'audio', 'audio_base64': audio_b64, 'audio_format': audio_fmt}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.warning("tts.stream_error", error=str(e))

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
