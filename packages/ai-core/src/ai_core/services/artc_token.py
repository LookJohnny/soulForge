"""Mint Alibaba RTC (ARTC) join tokens.

Vidu's component edition joins *our* RTC channel, so we have to hand it a token
for our own ARTC application. The shape was confirmed against a token Vidu's
realtime edition issued from its own app: base64 of a small JSON object whose
``token`` field is a hex SHA-256 over the join parameters.

The AppKey never leaves this process — only the digest does.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time

from ai_core.config import settings

# ARTC rejects a token whose timestamp has passed, and a long window is a long
# window for a leaked token. An hour matches the realtime edition's own tokens.
DEFAULT_TTL_SECONDS = 3600


class ArtcConfigError(RuntimeError):
    """Raised when the ARTC application credentials are not configured."""


def mint_token(
    channel_id: str,
    user_id: str,
    app_id: str = "",
    app_key: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    nonce: str | None = None,
) -> str:
    """Return a base64 ARTC token for one user joining one channel."""
    app_id = app_id or settings.artc_app_id
    app_key = app_key or settings.artc_app_key
    if not app_id or not app_key:
        raise ArtcConfigError("ARTC_APP_ID / ARTC_APP_KEY are not set")
    if not channel_id or not user_id:
        raise ValueError("channel_id and user_id are required")

    # A fresh nonce per token keeps two joins to the same channel from sharing a
    # digest, so one captured token cannot be replayed as another user's.
    nonce = secrets.token_hex(8) if nonce is None else nonce
    timestamp = int(time.time()) + int(ttl_seconds)

    digest = hashlib.sha256(
        f"{app_id}{app_key}{channel_id}{user_id}{nonce}{timestamp}".encode()
    ).hexdigest()

    payload = {
        "appid": app_id,
        "channelid": channel_id,
        "userid": user_id,
        "nonce": nonce,
        "timestamp": timestamp,
        "token": digest,
    }
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode()


def decode_token(token: str) -> dict:
    """Read a token back. For diagnostics — it verifies nothing."""
    return json.loads(base64.b64decode(token))
