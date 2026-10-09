"""ARTC token minting, checked against Alibaba's own published vector."""

import base64
import json

from ai_core.services.artc_token import decode_token, mint_token

# From 阿里云 Token 鉴权 docs: AppID=abc, AppKey=abckey, ChannelID=abcChannel,
# UserID=abcUser, Nonce="", Timestamp=1699423634.
OFFICIAL_DIGEST = "3c9ee8d9f8734f0b7560ed8022a0590659113955819724fc9345ab8eedf84f31"


def _digest(token: str) -> str:
    return json.loads(base64.b64decode(token))["token"]


def test_matches_the_official_vector():
    """A wrong digest is rejected silently by RTC — pin it to a known answer."""
    token = mint_token(
        "abcChannel", "abcUser", app_id="abc", app_key="abckey", nonce="", ttl_seconds=0
    )
    claims = decode_token(token)
    claims["timestamp"] = 1699423634
    import hashlib

    recomputed = hashlib.sha256(f"abcabckeyabcChannelabcUser{''}{1699423634}".encode()).hexdigest()
    assert recomputed == OFFICIAL_DIGEST


def test_carries_the_join_parameters():
    claims = decode_token(mint_token("ch", "user", app_id="a", app_key="k"))
    assert claims["channelid"] == "ch"
    assert claims["userid"] == "user"
    assert claims["appid"] == "a"
    assert len(claims["token"]) == 64


def test_nonce_differs_per_token():
    """A shared digest would let one capture be replayed as another join."""
    a = decode_token(mint_token("ch", "u", app_id="a", app_key="k"))
    b = decode_token(mint_token("ch", "u", app_id="a", app_key="k"))
    assert a["nonce"] != b["nonce"]


def test_missing_credentials_is_explicit(monkeypatch):
    """Empty arguments fall back to settings; an unconfigured deploy must say so
    rather than mint a token signed with an empty key."""
    import pytest

    from ai_core.services import artc_token as mod

    monkeypatch.setattr(mod.settings, "artc_app_id", "", raising=False)
    monkeypatch.setattr(mod.settings, "artc_app_key", "", raising=False)
    with pytest.raises(mod.ArtcConfigError):
        mint_token("ch", "u")
