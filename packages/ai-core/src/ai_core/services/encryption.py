"""Soul pack encryption — AES-256-GCM envelope encryption.

Each soul pack gets a unique DEK (Data Encryption Key).
The DEK is encrypted with a KEK (Key Encryption Key) derived from
the brand's master secret + brand_id.
"""

import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ai_core.config import settings


def _derive_kek(brand_id: str) -> bytes:
    """Derive a Key Encryption Key from master secret + brand_id."""
    material = f"{settings.master_secret}:{brand_id}".encode()
    return hashlib.sha256(material).digest()


def generate_dek() -> bytes:
    """Generate a random 256-bit Data Encryption Key."""
    return secrets.token_bytes(32)


def encrypt_dek(dek: bytes, brand_id: str) -> bytes:
    """Encrypt a DEK with the brand's KEK.

    Returns: nonce (12 bytes) + encrypted_dek
    """
    kek = _derive_kek(brand_id)
    aesgcm = AESGCM(kek)
    nonce = os.urandom(12)
    encrypted = aesgcm.encrypt(nonce, dek, None)
    return nonce + encrypted


def decrypt_dek(encrypted_dek: bytes, brand_id: str) -> bytes:
    """Decrypt a DEK with the brand's KEK."""
    kek = _derive_kek(brand_id)
    nonce = encrypted_dek[:12]
    ciphertext = encrypted_dek[12:]
    aesgcm = AESGCM(kek)
    return aesgcm.decrypt(nonce, ciphertext, None)


def encrypt_data(data: bytes, dek: bytes) -> bytes:
    """Encrypt data with a DEK using AES-256-GCM.

    Returns: nonce (12 bytes) + ciphertext
    """
    aesgcm = AESGCM(dek)
    nonce = os.urandom(12)
    encrypted = aesgcm.encrypt(nonce, data, None)
    return nonce + encrypted


def decrypt_data(encrypted: bytes, dek: bytes) -> bytes:
    """Decrypt data with a DEK."""
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(dek)
    return aesgcm.decrypt(nonce, ciphertext, None)
