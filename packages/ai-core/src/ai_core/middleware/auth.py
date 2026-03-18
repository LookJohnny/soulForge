"""JWT + API Key authentication middleware for ai-core.

Supports three auth methods:
1. NextAuth v5 JWE token (Authorization: Bearer <jwe>) — for admin-web frontend
2. API Key (Authorization: Bearer sk-xxx) — for programmatic access
3. Internal service token (X-Service-Token: <secret>) — for gateway → ai-core
"""

import base64
import hashlib
import hmac
import json
import struct
import time

import structlog
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ai_core.config import settings
from ai_core.db import get_pool

logger = structlog.get_logger()


# ──────────────────────────────────────────────
# Data class for authenticated context
# ──────────────────────────────────────────────


class AuthInfo:
    """Authenticated request context, stored in request.state.auth."""

    __slots__ = ("user_id", "brand_id", "role", "source")

    def __init__(self, user_id: str | None, brand_id: str, role: str, source: str):
        self.user_id = user_id
        self.brand_id = brand_id
        self.role = role
        self.source = source  # "jwt" | "api_key" | "service"


# ──────────────────────────────────────────────
# JWE Decryption (NextAuth v5 / Auth.js)
# ──────────────────────────────────────────────

def _base64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


_jwe_key_cache: bytes | None = None


def _get_jwe_key() -> bytes:
    """Derive 64-byte key from AUTH_SECRET via HKDF (matches Auth.js)."""
    global _jwe_key_cache
    if _jwe_key_cache is not None:
        return _jwe_key_cache
    hkdf_inst = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=None,  # Auth.js uses empty salt → HKDF default = zero-filled HashLen
        info=b"Auth.js Generated Encryption Key",
    )
    _jwe_key_cache = hkdf_inst.derive(settings.auth_secret.encode("utf-8"))
    return _jwe_key_cache


def decrypt_nextauth_jwe(token: str) -> dict:
    """Decrypt NextAuth v5 JWE token (dir + A256CBC-HS512)."""
    key = _get_jwe_key()
    mac_key = key[:32]
    enc_key = key[32:]

    parts = token.split(".")
    if len(parts) != 5:
        raise ValueError("Invalid JWE compact serialization")

    header_b64, _, iv_b64, ciphertext_b64, tag_b64 = parts

    iv = _base64url_decode(iv_b64)
    ciphertext = _base64url_decode(ciphertext_b64)
    tag = _base64url_decode(tag_b64)

    # Verify HMAC-SHA-512 tag (first 32 bytes = 256 bits)
    aad = header_b64.encode("ascii")
    al = struct.pack(">Q", len(aad) * 8)
    hmac_input = aad + iv + ciphertext + al
    full_hmac = hmac.new(mac_key, hmac_input, hashlib.sha512).digest()
    computed_tag = full_hmac[:32]

    if not hmac.compare_digest(tag, computed_tag):
        raise ValueError("JWE authentication tag mismatch")

    # AES-256-CBC decrypt
    cipher = Cipher(algorithms.AES(enc_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    # PKCS7 unpad
    unpadder = sym_padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    return json.loads(plaintext)


# ──────────────────────────────────────────────
# API Key verification
# ──────────────────────────────────────────────

async def _verify_api_key(key: str) -> dict | None:
    """Verify API key against the api_keys table. Returns auth info or None."""
    if not key.startswith("sk-") or len(key) < 12:
        return None

    prefix = key[:10]
    hashed = hashlib.sha256(key.encode()).hexdigest()

    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT brand_id, name, expires_at, revoked
           FROM api_keys
           WHERE prefix = $1 AND hashed_key = $2""",
        prefix,
        hashed,
    )
    if not row:
        return None
    if row["revoked"]:
        return None
    if row["expires_at"] and row["expires_at"].timestamp() < time.time():
        return None

    # Update last_used_at (best-effort)
    try:
        await pool.execute(
            "UPDATE api_keys SET last_used_at = now() WHERE prefix = $1", prefix
        )
    except Exception:
        pass

    return {"brand_id": str(row["brand_id"]), "name": row["name"]}


# ──────────────────────────────────────────────
# Auth Middleware
# ──────────────────────────────────────────────

# Paths that skip authentication
PUBLIC_PATHS = frozenset({"/health", "/metrics", "/docs", "/openapi.json", "/redoc"})


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on all endpoints except PUBLIC_PATHS."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public endpoints
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # --- 1. Internal service token ---
        service_token = request.headers.get("x-service-token")
        if service_token:
            if service_token == settings.service_token:
                request.state.auth = AuthInfo(
                    user_id=None,
                    brand_id=request.headers.get("x-brand-id", ""),
                    role="service",
                    source="service",
                )
                return await call_next(request)
            return JSONResponse(status_code=401, content={"error": "Invalid service token"})

        # --- 2. Bearer token (JWT or API key) ---
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing authentication. Provide Authorization: Bearer <token>"},
            )

        token = auth_header[7:]

        # 2a. API key
        if token.startswith("sk-"):
            result = await _verify_api_key(token)
            if not result:
                return JSONResponse(status_code=401, content={"error": "Invalid or expired API key"})
            request.state.auth = AuthInfo(
                user_id=None,
                brand_id=result["brand_id"],
                role="api",
                source="api_key",
            )
            return await call_next(request)

        # 2b. NextAuth JWE token
        try:
            claims = decrypt_nextauth_jwe(token)
            if claims.get("exp") and claims["exp"] < time.time():
                return JSONResponse(status_code=401, content={"error": "Token expired"})

            request.state.auth = AuthInfo(
                user_id=claims.get("sub"),
                brand_id=claims.get("brandId", ""),
                role=claims.get("role", "user"),
                source="jwt",
            )
            return await call_next(request)
        except Exception as e:
            logger.warning("auth.token_invalid", error=str(e))
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
