import pytest

from ai_core.services.voice_clone import (
    _assert_public_http_url,
    _looks_like_audio_bytes,
)


@pytest.mark.asyncio
async def test_public_url_rejects_private_ip_literal():
    with pytest.raises(RuntimeError, match="public IP"):
        await _assert_public_http_url("http://127.0.0.1/audio.wav")


@pytest.mark.asyncio
async def test_public_url_rejects_private_resolution():
    async def resolver(_hostname: str, _port: int) -> set[str]:
        return {"127.0.0.1"}

    with pytest.raises(RuntimeError, match="public IPs only"):
        await _assert_public_http_url("https://example.com/audio.wav", resolver=resolver)


@pytest.mark.asyncio
async def test_public_url_accepts_public_resolution():
    async def resolver(_hostname: str, _port: int) -> set[str]:
        return {"93.184.216.34"}

    await _assert_public_http_url("https://example.com/audio.wav", resolver=resolver)


def test_audio_sniffer_accepts_wav_and_mp3():
    wav = b"RIFF\x24\x00\x00\x00WAVEfmt "
    mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x21"
    assert _looks_like_audio_bytes(wav)
    assert _looks_like_audio_bytes(mp3)


def test_audio_sniffer_rejects_html():
    assert not _looks_like_audio_bytes(b"<!DOCTYPE html><html></html>")
