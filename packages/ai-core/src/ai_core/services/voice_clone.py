"""Voice Clone Service — upload audio → create Fish Audio voice model.

Flow:
  1. User uploads MP3/WAV audio (10-60 seconds)
  2. POST to Fish Audio /model API with audio file
  3. Get back reference_id (32-char hex)
  4. Store in VoiceProfile.fishAudioId
  5. TTS automatically uses this voice for the character
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import structlog

from ai_core.config import settings

logger = structlog.get_logger()

_FISH_API = "https://api.fish.audio"
_MAX_REDIRECTS = 5


def _is_public_ip(value: str) -> bool:
    return ipaddress.ip_address(value).is_global


def _looks_like_audio_bytes(data: bytes) -> bool:
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


async def _resolve_host_ips(hostname: str, port: int) -> set[str]:
    loop = asyncio.get_running_loop()
    addrinfo = await loop.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return {item[4][0] for item in addrinfo if item and item[4]}


async def _assert_public_http_url(
    audio_url: str,
    resolver=_resolve_host_ips,
) -> None:
    parsed = urlsplit(audio_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError("voice_clone: audio_url must be http(s)")
    if parsed.username or parsed.password:
        raise RuntimeError("voice_clone: credentialed URLs are not allowed")

    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        if not _is_public_ip(host):
            raise RuntimeError("voice_clone: audio_url must resolve to a public IP")
        return
    except ValueError:
        pass

    try:
        resolved_ips = await resolver(host, port)
    except OSError as e:
        raise RuntimeError(f"voice_clone: unable to resolve host: {e}") from e

    if not resolved_ips:
        raise RuntimeError("voice_clone: host did not resolve to any IP")
    if any(not _is_public_ip(ip) for ip in resolved_ips):
        raise RuntimeError("voice_clone: audio_url must resolve to public IPs only")


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
    # Download the audio sample. Cap size to protect us from arbitrary URLs.
    MAX_DOWNLOAD = 25 * 1024 * 1024  # 25MB
    audio_url_current = audio_url
    audio_bytes = b""
    content_type = ""

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            await _assert_public_http_url(audio_url_current)
            try:
                async with client.stream("GET", audio_url_current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise RuntimeError("voice_clone: redirect missing location")
                        audio_url_current = urljoin(str(resp.request.url), location)
                        continue

                    if resp.status_code != 200:
                        raise RuntimeError(f"voice_clone: download HTTP {resp.status_code}")

                    content_type = resp.headers.get("content-type", "").lower()
                    content_length = resp.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > MAX_DOWNLOAD:
                                raise RuntimeError(
                                    f"voice_clone: audio exceeds {MAX_DOWNLOAD // (1024*1024)}MB limit"
                                )
                        except ValueError:
                            pass

                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOWNLOAD:
                            raise RuntimeError(
                                f"voice_clone: audio exceeds {MAX_DOWNLOAD // (1024*1024)}MB limit"
                            )
                        chunks.append(chunk)
                    audio_bytes = b"".join(chunks)
                    break
            except httpx.HTTPError as e:
                raise RuntimeError(f"voice_clone: download failed: {e}") from e
        else:
            raise RuntimeError("voice_clone: too many redirects")

    if not audio_bytes or len(audio_bytes) < 1000:
        raise RuntimeError("voice_clone: audio too small (need at least ~10 seconds)")

    if content_type and not content_type.startswith(("audio/", "application/octet-stream")):
        raise RuntimeError("voice_clone: URL did not return audio content")
    if not _looks_like_audio_bytes(audio_bytes):
        raise RuntimeError("voice_clone: downloaded content is not recognized audio")

    logger.info("voice_clone.url_downloaded", url=audio_url_current[:120], bytes=len(audio_bytes))
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
