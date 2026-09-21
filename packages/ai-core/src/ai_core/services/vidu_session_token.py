"""Signed session tokens for Vidu S2 external retrieval callbacks.

Vidu's external memory / knowledge protocol sends only ``live_id`` in the request
body — there is no end-user identifier. The endpoint and the ``Authorization``
header are, however, configured per session at CreateLive time, so the binding
``(end_user_id, character_id, live_id)`` is carried inside the token itself.

This keeps the end-user identifier out of the callback URL and makes the token
both the authentication and the routing key: an unforgeable token is the only way
to name whose memory is being read.

Token layout (all base64url, no padding)::

    v1.<payload_b64>.<hmac_sha256_b64>

``payload_b64`` decodes to a compact JSON object with ``u`` (end user), ``c``
(character, may be null), ``l`` (live id, may be null before CreateLive returns)
and ``exp`` (unix seconds).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from ai_core.config import settings

_PREFIX = "v1"
_DEFAULT_TTL_SECONDS = 8 * 3600  # a live session tops out at 7200s; leave headroom


class ViduTokenError(ValueError):
    """Raised when a callback token is malformed, forged or expired."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signing_key() -> bytes:
    """Derive a purpose-scoped key so this token cannot be replayed elsewhere."""
    return hashlib.sha256(b"vidu-external-retrieval\x00" + settings.master_secret.encode()).digest()


def _sign(payload_b64: str) -> str:
    mac = hmac.new(_signing_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64e(mac)


def mint_session_token(
    end_user_id: str,
    character_id: str | None = None,
    live_id: str | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Mint a token binding a Vidu live session to one SoulForge end user."""
    if not end_user_id or not end_user_id.strip():
        raise ViduTokenError("end_user_id is required")
    payload = {
        "u": end_user_id.strip(),
        "c": character_id,
        "l": live_id,
        "exp": int(time.time()) + int(ttl_seconds),
    }
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{_PREFIX}.{payload_b64}.{_sign(payload_b64)}"


def verify_session_token(token: str, live_id: str | None = None) -> dict:
    """Verify a token and return its claims.

    ``live_id``, when given, must match the token's own ``l`` claim if that claim
    was set — so a token minted for one session cannot read another session's
    memory even though both belong to the same account.
    """
    if not token:
        raise ViduTokenError("missing token")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _PREFIX:
        raise ViduTokenError("malformed token")

    _, payload_b64, signature = parts
    if not hmac.compare_digest(signature, _sign(payload_b64)):
        raise ViduTokenError("bad signature")

    try:
        claims = json.loads(_b64d(payload_b64))
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad token
        raise ViduTokenError("undecodable payload") from exc

    if not isinstance(claims, dict) or not claims.get("u"):
        raise ViduTokenError("payload missing subject")
    if int(claims.get("exp", 0)) < time.time():
        raise ViduTokenError("token expired")

    bound_live = claims.get("l")
    if bound_live and live_id and bound_live != live_id:
        raise ViduTokenError("token not valid for this live session")

    return claims


def parse_authorization_header(header: str | None) -> str:
    """Pull the raw token out of whatever Vidu forwards as ``Authorization``.

    Vidu forwards the configured string verbatim, so accept it both bare and
    behind a ``Bearer`` prefix.
    """
    if not header:
        raise ViduTokenError("missing Authorization header")
    value = header.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not value:
        raise ViduTokenError("empty Authorization header")
    return value
