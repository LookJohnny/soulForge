"""Agora token minting.

A wrong RTC signature is rejected silently — Vidu only ever reports NOT_READY —
so these pin the shape rather than trusting that it looks right.
"""

import pytest

from ai_core.services import agora_token
from ai_core.services.agora_token import AgoraConfigError, mint_token

APP_ID = "a" * 32
CERT = "0" * 32


def test_builds_an_accesstoken2():
    """Vidu's component edition needs the 007 format, not the older 006."""
    token = mint_token("ch", 1001, app_id=APP_ID, app_certificate=CERT)
    assert token.startswith("007")
    assert len(token) > 50


def test_channel_and_uid_change_the_token():
    a = mint_token("ch-a", 1, app_id=APP_ID, app_certificate=CERT)
    b = mint_token("ch-b", 1, app_id=APP_ID, app_certificate=CERT)
    c = mint_token("ch-a", 2, app_id=APP_ID, app_certificate=CERT)
    assert a != b != c and a != c


def test_publisher_and_subscriber_differ():
    """Vidu publishes the avatar; a viewer must not be handed the same rights."""
    pub = mint_token("ch", 1, app_id=APP_ID, app_certificate=CERT, publisher=True)
    sub = mint_token("ch", 1, app_id=APP_ID, app_certificate=CERT, publisher=False)
    assert pub != sub


def test_missing_credentials_is_explicit(monkeypatch):
    monkeypatch.setattr(agora_token.settings, "agora_app_id", "", raising=False)
    monkeypatch.setattr(agora_token.settings, "agora_app_certificate", "", raising=False)
    with pytest.raises(AgoraConfigError):
        mint_token("ch", 1)
