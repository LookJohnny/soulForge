"""AES-256-GCM for `.soul` passphrase encryption.

`cryptography` is an optional extra (`soulforge-harness[crypto]`); without it,
plaintext souls still work and encrypted ones raise a clear error.
"""

from __future__ import annotations

import os

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - environment without the extra
    AESGCM = None  # type: ignore[assignment]
    HAVE_CRYPTO = False


def _require() -> None:
    if not HAVE_CRYPTO:
        raise RuntimeError(
            "encrypted .soul files need the optional dependency: "
            "pip install 'soulforge-harness[crypto]'"
        )


def encrypt_data(data: bytes, key: bytes) -> bytes:
    """nonce(12) + AES-GCM ciphertext."""
    _require()
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt_data(encrypted: bytes, key: bytes) -> bytes:
    _require()
    return AESGCM(key).decrypt(encrypted[:12], encrypted[12:], None)
