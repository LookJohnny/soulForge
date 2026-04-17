"""Voice Clone Service — upload audio → create Fish Audio voice model.

Flow:
  1. User uploads MP3/WAV audio (10-60 seconds)
  2. POST to Fish Audio /model API with audio file
  3. Get back reference_id (32-char hex)
  4. Store in VoiceProfile.fishAudioId
  5. TTS automatically uses this voice for the character
"""

import httpx
import structlog

from ai_core.config import settings

logger = structlog.get_logger()

_FISH_API = "https://api.fish.audio"


async def clone_voice(audio_bytes: bytes, title: str,
                      description: str = "") -> dict:
    """Upload audio to Fish Audio and create a cloned voice model.

    Args:
        audio_bytes: MP3 or WAV audio (10-60 seconds recommended)
        title: Voice model name
        description: Optional description

    Returns:
        {"fish_audio_id": str, "title": str, "state": str}

    Raises:
        RuntimeError on API failure
    """
    api_key = settings.fish_audio_api_key
    if not api_key:
        raise RuntimeError("FISH_AUDIO_API_KEY not configured")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{_FISH_API}/model",
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "visibility": "private",
                "type": "tts",
                "train_mode": "fast",
                "title": title,
                "description": description,
            },
            files={"voices": ("voice_sample.mp3", audio_bytes, "audio/mpeg")},
        )

    if resp.status_code == 401:
        raise RuntimeError("Fish Audio: authentication failed")
    if resp.status_code == 402:
        raise RuntimeError("Fish Audio: insufficient credits")
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Fish Audio: HTTP {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    fish_id = data.get("_id", "")

    logger.info("voice_clone.created", fish_audio_id=fish_id, title=title, state=data.get("state"))

    return {
        "fish_audio_id": fish_id,
        "title": data.get("title", title),
        "state": data.get("state", "unknown"),
    }


async def clone_voice_from_url(audio_url: str, title: str,
                                description: str = "") -> dict:
    """Fetch an audio URL and clone it via Fish Audio.

    Convenience wrapper for the vocalized-character flow where the user
    supplies a URL to source-material audio rather than uploading a file.

    Args:
        audio_url: Publicly fetchable audio URL (MP3/WAV/OGG, 10-60s).
        title: Voice model name.
        description: Optional description.

    Returns:
        Same shape as clone_voice().

    Raises:
        RuntimeError if download fails or clone fails.
    """
    if not audio_url or not audio_url.startswith(("http://", "https://")):
        raise RuntimeError("voice_clone: audio_url must be http(s)")

    # Download the audio sample. Cap size to protect us from arbitrary URLs.
    MAX_DOWNLOAD = 25 * 1024 * 1024  # 25MB
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            resp = await client.get(audio_url)
        except httpx.HTTPError as e:
            raise RuntimeError(f"voice_clone: download failed: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(f"voice_clone: download HTTP {resp.status_code}")

    audio_bytes = resp.content
    if not audio_bytes or len(audio_bytes) < 1000:
        raise RuntimeError("voice_clone: audio too small (need at least ~10 seconds)")
    if len(audio_bytes) > MAX_DOWNLOAD:
        raise RuntimeError(f"voice_clone: audio exceeds {MAX_DOWNLOAD // (1024*1024)}MB limit")

    content_type = resp.headers.get("content-type", "").lower()
    if content_type and not content_type.startswith(("audio/", "application/octet-stream")):
        logger.warning("voice_clone.unexpected_content_type", content_type=content_type, url=audio_url[:120])

    logger.info("voice_clone.url_downloaded", url=audio_url[:120], bytes=len(audio_bytes))
    return await clone_voice(audio_bytes, title, description)


async def delete_voice(fish_audio_id: str) -> bool:
    """Delete a cloned voice model from Fish Audio."""
    api_key = settings.fish_audio_api_key
    if not api_key:
        return False

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.delete(
            f"{_FISH_API}/model/{fish_audio_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )

    return resp.status_code == 204
