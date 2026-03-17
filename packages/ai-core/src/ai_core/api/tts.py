"""TTS preview endpoints."""

import base64

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ai_core.dependencies import get_tts_client
from ai_core.middleware.rate_limit import limiter

router = APIRouter(prefix="/tts", tags=["tts"])


class TTSPreviewRequest(BaseModel):
    text: str
    voice: str | None = None
    speed: float = 1.0


@router.get("/voices")
async def list_voices():
    """List available preset voices."""
    tts = await get_tts_client()
    voices = tts.get_preset_voices()
    return {
        "voices": [
            {"id": vid, "name": name} for vid, name in voices.items()
        ]
    }


@router.post("/preview")
@limiter.limit("20/minute")
async def preview_tts(req: TTSPreviewRequest, request: Request):
    """Synthesize text and return WAV audio as base64."""
    tts = await get_tts_client()
    wav_data = await tts.synthesize_to_wav(
        text=req.text,
        voice=req.voice,
        speed=req.speed,
    )
    return {
        "audio_base64": base64.b64encode(wav_data).decode(),
        "format": "wav",
        "voice": req.voice or "default",
    }


@router.post("/preview.wav")
@limiter.limit("20/minute")
async def preview_tts_wav(req: TTSPreviewRequest, request: Request):
    """Synthesize text and return WAV audio directly (for <audio> src)."""
    tts = await get_tts_client()
    wav_data = await tts.synthesize_to_wav(
        text=req.text,
        voice=req.voice,
        speed=req.speed,
    )
    return Response(content=wav_data, media_type="audio/wav")
