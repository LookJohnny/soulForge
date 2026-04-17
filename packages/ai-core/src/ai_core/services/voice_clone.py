"""Voice Clone Service — upload audio → create Fish Audio voice model.

Flow:
  1. User uploads MP3/WAV audio (10-60 seconds) or supplies a public URL
  2. POST to Fish Audio /model API with audio file
  3. Get back reference_id (32-char hex)
  4. Store in VoiceProfile.fishAudioId or Character.voice_clone_ref_id
  5. TTS automatically uses this voice for the character

All URL-based fetches go through ``services.url_safety`` which defeats
DNS rebinding and blocks private/loopback/CGNAT/multicast targets.
"""

import httpx
import structlog

from ai_core.config import settings
from ai_core.services.url_safety import fetch_public_url

logger = structlog.get_logger()

_FISH_API = "https://api.fish.audio"
_AUDIO_CONTENT_TYPES = ("audio/", "application/octet-stream")


def _looks_like_audio_bytes(data: bytes) -> bool:
    """Cheap magic-byte check to reject obvious non-audio payloads.

    Covers WAV, MP3 (ID3 or raw MPEG frame), Ogg, FLAC, and MP4/M4A
    (ftyp box in the first 12 bytes). Not exhaustive — treat as a
    smoke filter, not a strict validator.
    """
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return True
    if len(data) >= 3 and data[:3] == b"ID3":
        return True
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return True
    if len(data) >= 4 and data[:4] == b"OggS":
        return True
    if len(data) >= 4 and data[:4] == b"fLaC":
        return True
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return True
    return False


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
    """Fetch an audio URL safely and clone it via Fish Audio.

    Used by the vocalized-character flow where the designer supplies a
    URL to source-material audio. Downloads via the SSRF-hardened
    ``fetch_public_url`` (IP-pinned, redirect-validated, size-capped,
    public-IP-only) before handing bytes to the Fish Audio API.

    Raises:
        RuntimeError if download fails, URL is unsafe, or clone fails.
    """
    result = await fetch_public_url(
        audio_url,
        max_bytes=25 * 1024 * 1024,
        timeout_s=30.0,
        allowed_content_types=_AUDIO_CONTENT_TYPES,
    )

    audio_bytes = result.content
    if len(audio_bytes) < 1000:
        raise RuntimeError("voice_clone: audio too small (need at least ~10 seconds)")
    if not _looks_like_audio_bytes(audio_bytes):
        raise RuntimeError("voice_clone: downloaded content is not recognized audio")

    # Log the URL without query string so S3 presigned params / tokens
    # don't end up in log aggregators.
    url_for_log = audio_url.split("?", 1)[0]
    logger.info(
        "voice_clone.url_downloaded",
        url=url_for_log[:120],
        bytes=len(audio_bytes),
        content_type=result.content_type,
    )
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
