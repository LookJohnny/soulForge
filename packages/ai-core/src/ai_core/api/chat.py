"""Chat endpoint with TTS - for the admin preview panel."""

import base64
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_core.dependencies import get_llm_client, get_prompt_builder, get_tts_client

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatPreviewRequest(BaseModel):
    character_id: str
    text: str
    voice: str | None = None
    with_audio: bool = True


class ChatPreviewResponse(BaseModel):
    text: str
    audio_base64: str | None = None
    audio_format: str | None = None
    latency_ms: int = 0


@router.post("/preview", response_model=ChatPreviewResponse)
async def chat_preview(req: ChatPreviewRequest):
    """Chat with a character and get text + optional audio response."""
    start = time.monotonic()

    # Build prompt
    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            user_input=req.text,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # LLM
    llm = await get_llm_client()
    ai_text = await llm.chat(
        system_prompt=prompt_result["system_prompt"],
        user_input=req.text,
    )

    # TTS (optional)
    audio_b64 = None
    audio_fmt = None
    if req.with_audio:
        voice_id = req.voice or prompt_result.get("voice_id")
        tts = await get_tts_client()
        wav_data = await tts.synthesize_to_wav(
            text=ai_text,
            voice=voice_id,
            speed=prompt_result.get("voice_speed", 1.0),
        )
        audio_b64 = base64.b64encode(wav_data).decode()
        audio_fmt = "mp3" if wav_data[:3] == b"ID3" or (wav_data[0] == 0xFF and (wav_data[1] & 0xE0) == 0xE0) else "wav"

    latency = int((time.monotonic() - start) * 1000)

    return ChatPreviewResponse(
        text=ai_text,
        audio_base64=audio_b64,
        audio_format=audio_fmt,
        latency_ms=latency,
    )
