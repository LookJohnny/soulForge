"""TTS preview and synthesis endpoints."""

import base64

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ai_core.dependencies import get_prompt_builder, get_tts_client
from ai_core.middleware.rate_limit import limiter
from ai_core.services.tts.context import prepare_for_character as _tts_prepare_for_character

router = APIRouter(prefix="/tts", tags=["tts"])
logger = structlog.get_logger()


class TTSPreviewRequest(BaseModel):
    text: str = Field(max_length=2000)
    voice: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class TTSSynthesizeRequest(BaseModel):
    text: str = Field(max_length=500)
    voice: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    # With character_id, synthesize in that character's voice (clone or preset)
    character_id: str | None = None
    brand_id: str | None = None


@router.get("/voices")
async def list_voices():
    """List available preset voices."""
    tts = await get_tts_client()
    voices = tts.get_preset_voices()
    return {"voices": [{"id": vid, "name": name} for vid, name in voices.items()]}


@router.post("/synthesize")
@limiter.limit("60/minute")
async def synthesize_tts(req: TTSSynthesizeRequest, request: Request):
    """Synthesize short text to MP3, returned as base64.

    Used by the gateway for plugin quick replies, thinking fillers, and
    ambient life sounds. When character_id is provided, the character's
    own voice (clone or matched preset) is used so the toy never breaks
    voice mid-session.
    """
    tts = await get_tts_client()
    voice = req.voice
    speed = req.speed
    pitch_rate = 0
    speech_rate = 0

    # Resolve the character's voice. Authenticated brand context wins over
    # the body value so a tenant can't borrow another brand's voice.
    auth = getattr(request.state, "auth", None)
    brand_id = (auth.brand_id if auth and auth.brand_id else None) or req.brand_id
    if req.character_id and brand_id:
        try:
            builder = await get_prompt_builder()
            pr = await builder.build(
                character_id=req.character_id,
                brand_id=brand_id,
                user_input="",
                structured_output=False,
            )
            if pr.get("voice_id"):
                _tts_prepare_for_character(tts, pr)
                voice = pr["voice_id"]
                speed = pr.get("voice_speed", 1.0) * req.speed
                pitch_rate = pr.get("pitch_rate", 0)
                speech_rate = pr.get("speech_rate", 0)
        except Exception:
            logger.warning("tts.synthesize.character_voice_fallback", exc_info=True)

    audio = await tts.synthesize(
        text=req.text,
        voice=voice,
        speed=speed,
        pitch_rate=pitch_rate,
        speech_rate=speech_rate,
    )
    return {"audio_data": base64.b64encode(audio).decode(), "format": "mp3"}


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
    # edge returns MP3 bytes; the old audio/wav label lied to <audio> consumers
    return Response(content=wav_data, media_type="audio/mpeg")
