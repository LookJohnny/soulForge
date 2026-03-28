"""Voice clone API — upload audio sample → create custom voice."""

import structlog
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form

from ai_core.services.voice_clone import clone_voice, delete_voice

router = APIRouter(prefix="/voice-clone", tags=["voice-clone"])
logger = structlog.get_logger()

MAX_AUDIO_SIZE = 20 * 1024 * 1024  # 20MB


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


@router.delete("/{fish_audio_id}")
async def delete_cloned_voice(fish_audio_id: str, request: Request):
    """Delete a cloned voice model from Fish Audio."""
    ok = await delete_voice(fish_audio_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Voice not found or delete failed")
    return {"status": "deleted"}
