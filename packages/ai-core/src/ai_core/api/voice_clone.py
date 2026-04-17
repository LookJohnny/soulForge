"""Voice clone API — upload audio sample → create custom voice."""

import structlog
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel, Field

from ai_core.services.voice_clone import clone_voice, clone_voice_from_url, delete_voice

router = APIRouter(prefix="/voice-clone", tags=["voice-clone"])
logger = structlog.get_logger()

MAX_AUDIO_SIZE = 20 * 1024 * 1024  # 20MB


class CloneFromUrlRequest(BaseModel):
    audio_url: str = Field(..., min_length=10, max_length=2000)
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


@router.post("/create")
async def create_cloned_voice(
    request: Request,
    audio: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
):
    """Upload audio and create a Fish Audio cloned voice.

    Args:
        audio: MP3/WAV file (10-60 seconds recommended)
        title: Voice name (e.g. character name)
        description: Optional description

    Returns:
        {"fish_audio_id": str, "title": str, "state": str}
    """
    content = await audio.read()
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=422, detail="Audio file exceeds 20MB limit")
    if len(content) < 1000:
        raise HTTPException(status_code=422, detail="Audio file too small (need at least 10 seconds)")

    try:
        result = await clone_voice(content, title, description)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return result


@router.post("/from-url")
async def create_cloned_voice_from_url(req: CloneFromUrlRequest, request: Request):
    """Clone a Fish Audio voice from a publicly-fetchable audio URL.

    Used by the character creation wizard when the designer supplies a
    source-material URL (e.g. a 10-20s voice-actor sample) instead of
    uploading a file. Returns the reference_id that should be written to
    Character.voice_clone_ref_id.
    """
    try:
        result = await clone_voice_from_url(
            audio_url=req.audio_url,
            title=req.title,
            description=req.description,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result


@router.delete("/{fish_audio_id}")
async def delete_cloned_voice(fish_audio_id: str, request: Request):
    """Delete a cloned voice model from Fish Audio."""
    ok = await delete_voice(fish_audio_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Voice not found or delete failed")
    return {"status": "deleted"}
