"""Audio codec utilities — Opus/PCM/MP3 conversion via ffmpeg subprocess.

Xiaozhi ESP32 devices send and receive Opus-encoded audio:
  - Incoming: Opus 16kHz mono → decode to PCM 16kHz 16-bit mono (for ASR)
  - Outgoing: MP3 from TTS → encode to Opus 16kHz mono (for device playback)

Uses ffmpeg subprocess for reliability across all platforms.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# ffmpeg timeout in seconds
_FFMPEG_TIMEOUT = 10


async def opus_to_pcm(opus_data: bytes) -> bytes:
    """Decode Opus audio to raw PCM (16kHz 16-bit mono).

    Args:
        opus_data: Raw Opus-encoded bytes (OGG/Opus container or raw Opus packets).

    Returns:
        PCM bytes: signed 16-bit little-endian, 16kHz, mono.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",             # read from stdin
        "-f", "s16le",              # output format: raw PCM
        "-acodec", "pcm_s16le",     # signed 16-bit LE
        "-ar", "16000",             # 16kHz
        "-ac", "1",                 # mono
        "pipe:1",                   # write to stdout
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=opus_data), timeout=_FFMPEG_TIMEOUT,
    )
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        logger.error("opus_to_pcm failed: %s", err)
        # Fallback: return original data as-is (maybe it was already PCM)
        return opus_data
    return stdout


async def mp3_to_opus(mp3_data: bytes) -> bytes:
    """Encode MP3 audio to Opus (OGG container, 16kHz mono).

    Args:
        mp3_data: MP3-encoded bytes from TTS.

    Returns:
        OGG/Opus bytes suitable for xiaozhi device playback.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",             # read MP3 from stdin
        "-c:a", "libopus",          # Opus codec
        "-ar", "16000",             # 16kHz
        "-ac", "1",                 # mono
        "-b:a", "32k",              # 32kbps (good quality for speech, small size)
        "-application", "voip",     # optimized for speech
        "-f", "ogg",                # OGG container
        "pipe:1",                   # write to stdout
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=mp3_data), timeout=_FFMPEG_TIMEOUT,
    )
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        logger.error("mp3_to_opus failed: %s", err)
        # Fallback: return MP3 as-is (some devices may handle it)
        return mp3_data
    return stdout


async def pcm_to_opus(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Encode raw PCM to Opus (OGG container).

    Args:
        pcm_data: Raw PCM bytes (signed 16-bit LE, mono).
        sample_rate: Sample rate of input PCM.

    Returns:
        OGG/Opus bytes.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "s16le",              # input format: raw PCM
        "-ar", str(sample_rate),    # input sample rate
        "-ac", "1",                 # mono
        "-i", "pipe:0",             # read from stdin
        "-c:a", "libopus",          # Opus codec
        "-b:a", "32k",
        "-application", "voip",
        "-f", "ogg",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=pcm_data), timeout=_FFMPEG_TIMEOUT,
    )
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        logger.error("pcm_to_opus failed: %s", err)
        return pcm_data
    return stdout


def is_opus(data: bytes) -> bool:
    """Check if audio data is OGG/Opus format."""
    # OGG container starts with "OggS"
    if len(data) >= 4 and data[:4] == b"OggS":
        return True
    # Some raw Opus packets start with the OpusHead signature
    if len(data) >= 8 and b"OpusHead" in data[:36]:
        return True
    return False


def is_mp3(data: bytes) -> bool:
    """Check if audio data is MP3 format."""
    if len(data) < 3:
        return False
    # ID3 tag header
    if data[:3] == b"ID3":
        return True
    # MPEG audio frame sync
    if data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return True
    return False


async def mp3_to_pcm(mp3_data: bytes) -> bytes:
    """Decode MP3 to raw PCM (16kHz 16-bit mono)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-f", "s16le", "-ar", "16000", "-ac", "1",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=mp3_data), timeout=_FFMPEG_TIMEOUT,
    )
    if proc.returncode != 0:
        logger.error("mp3_to_pcm failed: %s", stderr.decode(errors="replace").strip())
        return b""
    return stdout


async def mp3_to_pcm_24k(mp3_data: bytes) -> bytes:
    """Decode MP3 to raw PCM at 24kHz 16-bit mono (xiaozhi TTS standard)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-f", "s16le", "-ar", "24000", "-ac", "1",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=mp3_data), timeout=_FFMPEG_TIMEOUT,
    )
    if proc.returncode != 0:
        logger.error("mp3_to_pcm_24k failed: %s", stderr.decode(errors="replace").strip())
        return b""
    return stdout


def pcm_to_opus_frames(
    pcm_data: bytes,
    sample_rate: int = 24000,
    frame_duration_ms: int = 60,
) -> list[bytes]:
    """Encode PCM to a list of raw Opus frames.

    Each frame is an independent Opus packet suitable for sending
    as a WebSocket binary message to xiaozhi devices.

    Args:
        pcm_data: Raw PCM bytes (mono 16-bit).
        sample_rate: Sample rate (24000 for xiaozhi TTS output).
        frame_duration_ms: Frame duration (60ms standard for xiaozhi).

    Returns:
        List of raw Opus packets (bytes).
    """
    import opuslib

    channels = 1
    frame_size = sample_rate * frame_duration_ms // 1000  # samples per frame
    frame_bytes = frame_size * channels * 2  # bytes per frame (16-bit)

    encoder = opuslib.Encoder(sample_rate, channels, opuslib.APPLICATION_VOIP)
    frames = []

    for offset in range(0, len(pcm_data) - frame_bytes + 1, frame_bytes):
        pcm_frame = pcm_data[offset:offset + frame_bytes]
        opus_frame = encoder.encode(pcm_frame, frame_size)
        frames.append(opus_frame)

    return frames
