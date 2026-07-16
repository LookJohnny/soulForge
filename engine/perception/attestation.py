"""Authenticity checks for perception-originated critical hazard claims.

Perception frames and WireEvents are untrusted.  A sensor event may only unlock
the Character Runtime's deterministic CRITICAL safe-stop path when the trusted
perception service signs the confirmation evidence with a deployment secret.
Deployments set ``SOULFORGE_PERCEPTION_ATTESTATION_KEY`` to the same high-entropy
value in the perception producer and Character Runtime processes.  With no key,
verification fails closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

ATTESTATION_ENV = "SOULFORGE_PERCEPTION_ATTESTATION_KEY"
ATTESTATION_VERSION = 1
MIN_SECRET_BYTES = 24

_CLAIM_KEYS = (
    "event_id",
    "captured_at",
    "confidence",
    "hazard_confirmed",
    "hazard_confirmation_hits",
    "hazard_confirmation_required_hits",
    "hazard_confirmation_window_s",
)


def _secret_bytes(secret: str | bytes | None = None) -> bytes | None:
    value = secret if secret is not None else os.environ.get(ATTESTATION_ENV)
    if value is None:
        return None
    encoded = value if isinstance(value, bytes) else value.encode("utf-8")
    return encoded if len(encoded) >= MIN_SECRET_BYTES else None


def _claim(payload: dict[str, Any], source: str, target_agent: str | None) -> bytes:
    data = {key: payload.get(key) for key in _CLAIM_KEYS}
    data["source"] = source
    data["target_agent"] = target_agent
    data["version"] = ATTESTATION_VERSION
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_hazard_claim(
    payload: dict[str, Any],
    source: str,
    target_agent: str | None,
    *,
    secret: str | bytes | None = None,
) -> str | None:
    """Sign confirmed hazard evidence, or return ``None`` when fail-closed."""
    key = _secret_bytes(secret)
    if key is None:
        return None
    if payload.get("severity") != "critical" or not payload.get("hazard_confirmed"):
        return None
    try:
        hits = int(payload.get("hazard_confirmation_hits", 0))
        required = int(payload.get("hazard_confirmation_required_hits", 3))
    except (TypeError, ValueError):
        return None
    if required < 3 or hits < required:
        return None
    return hmac.new(
        key, _claim(payload, source, target_agent), hashlib.sha256
    ).hexdigest()


def verify_hazard_claim(
    payload: dict[str, Any],
    source: str,
    target_agent: str | None,
    *,
    secret: str | bytes | None = None,
) -> bool:
    """Verify a critical hazard claim without trusting caller-controlled flags."""
    signature = payload.get("hazard_attestation")
    if not isinstance(signature, str):
        return False
    expected = sign_hazard_claim(payload, source, target_agent, secret=secret)
    return expected is not None and hmac.compare_digest(signature, expected)


__all__ = [
    "ATTESTATION_ENV",
    "ATTESTATION_VERSION",
    "sign_hazard_claim",
    "verify_hazard_claim",
]
