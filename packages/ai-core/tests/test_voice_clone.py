import pytest

from ai_core.services.url_safety import (
    _is_safe_ip,
    _resolve_and_validate,
    _rewrite_to_ip,
    assert_public_http_url,
)
from ai_core.services.voice_clone import _looks_like_audio_bytes


@pytest.mark.asyncio
async def test_public_url_rejects_private_ip_literal():
    with pytest.raises(RuntimeError, match="non-public IP"):
        await assert_public_http_url("http://127.0.0.1/audio.wav")


@pytest.mark.asyncio
async def test_public_url_rejects_private_resolution():
    async def resolver(_hostname: str, _port: int) -> list[str]:
        return ["127.0.0.1"]

    with pytest.raises(RuntimeError, match="non-public IP"):
        await _resolve_and_validate(
            "https://example.com/audio.wav",
            resolver=resolver,
        )


@pytest.mark.asyncio
async def test_public_url_accepts_public_resolution():
    async def resolver(_hostname: str, _port: int) -> list[str]:
        return ["93.184.216.34"]

    host, port, ips = await _resolve_and_validate(
        "https://example.com/audio.wav",
        resolver=resolver,
    )
    assert host == "example.com"
    assert port == 443
    assert ips == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_rejects_credentialed_url():
    with pytest.raises(RuntimeError, match="credentialed"):
        await assert_public_http_url("http://user:pass@example.com/x")


@pytest.mark.asyncio
async def test_rejects_non_http_scheme():
    with pytest.raises(RuntimeError, match="http"):
        await assert_public_http_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_rejects_cgnat_shared_space():
    # 100.64.0.0/10 is RFC 6598 CGNAT; often routable to internal infra
    # but not on the public Internet. Must be blocked.
    with pytest.raises(RuntimeError, match="non-public IP"):
        await assert_public_http_url("http://100.64.1.1/x")


@pytest.mark.asyncio
async def test_rejects_ipv4_mapped_ipv6_loopback():
    # ::ffff:127.0.0.1 must be recognized as loopback, not bypass the check
    with pytest.raises(RuntimeError, match="non-public IP"):
        await assert_public_http_url("http://[::ffff:127.0.0.1]/x")


@pytest.mark.asyncio
async def test_rejects_mixed_resolution_with_one_private_ip():
    # If a host resolves to [public, private], must reject — attacker can
    # force httpx onto the private one otherwise.
    async def resolver(_h: str, _p: int) -> list[str]:
        return ["93.184.216.34", "10.0.0.5"]

    with pytest.raises(RuntimeError, match="non-public IP"):
        await _resolve_and_validate(
            "https://example.com/x",
            resolver=resolver,
        )


def test_is_safe_ip_allows_public_v4():
    assert _is_safe_ip("8.8.8.8")
    assert _is_safe_ip("93.184.216.34")


def test_is_safe_ip_rejects_rfc1918_and_friends():
    for bad in [
        "127.0.0.1",       # loopback
        "10.0.0.1",        # private A
        "192.168.1.1",     # private C
        "169.254.169.254", # link-local (AWS metadata)
        "100.64.1.1",      # CGNAT
        "224.0.0.1",       # multicast
        "0.0.0.0",         # unspecified
        "::1",             # loopback v6
        "fc00::1",         # unique-local v6
        "fe80::1",         # link-local v6
    ]:
        assert not _is_safe_ip(bad), f"{bad} should be rejected"


def test_rewrite_to_ip_preserves_path_and_query():
    assert _rewrite_to_ip(
        "https://example.com/path?a=1", "93.184.216.34"
    ) == "https://93.184.216.34/path?a=1"
    # Port preserved
    assert _rewrite_to_ip(
        "https://example.com:8443/x", "1.2.3.4"
    ) == "https://1.2.3.4:8443/x"
    # IPv6 gets bracketed
    assert _rewrite_to_ip(
        "https://example.com/x", "2606:4700:4700::1111"
    ) == "https://[2606:4700:4700::1111]/x"


def test_audio_sniffer_accepts_wav_and_mp3():
    wav = b"RIFF\x24\x00\x00\x00WAVEfmt "
    mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x21"
    assert _looks_like_audio_bytes(wav)
    assert _looks_like_audio_bytes(mp3)


def test_audio_sniffer_rejects_html():
    assert not _looks_like_audio_bytes(b"<!DOCTYPE html><html></html>")
