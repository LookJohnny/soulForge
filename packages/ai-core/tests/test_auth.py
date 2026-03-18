"""Tests for the auth middleware — JWE decryption, API key verification, path skipping."""

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import hashes, padding as sym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Import the module directly so mock.patch can resolve the target
import ai_core.middleware.auth as auth_mod
from ai_core.middleware.auth import (
    AuthInfo,
    AuthMiddleware,
    PUBLIC_PATHS,
    _verify_api_key,
    decrypt_nextauth_jwe,
)


# ──────────────────────────────────────────────
# Helpers: create a valid JWE token for testing
# ──────────────────────────────────────────────

TEST_AUTH_SECRET = "test-secret-for-unit-tests-must-be-long-enough"


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jwe_token(claims: dict, auth_secret: str = TEST_AUTH_SECRET) -> str:
    """Create a valid NextAuth v5 JWE token (dir + A256CBC-HS512) for testing."""
    # Derive key same as Auth.js
    hkdf_inst = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=None,
        info=b"Auth.js Generated Encryption Key",
    )
    key = hkdf_inst.derive(auth_secret.encode("utf-8"))
    mac_key = key[:32]
    enc_key = key[32:]

    # Header
    header = {"alg": "dir", "enc": "A256CBC-HS512"}
    header_b64 = _base64url_encode(json.dumps(header).encode())

    # Empty encrypted key (direct key agreement)
    ek_b64 = ""

    # IV
    iv = os.urandom(16)
    iv_b64 = _base64url_encode(iv)

    # Encrypt payload with AES-256-CBC
    plaintext = json.dumps(claims).encode("utf-8")
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()

    cipher = Cipher(algorithms.AES(enc_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    ct_b64 = _base64url_encode(ciphertext)

    # HMAC-SHA-512 tag
    aad = header_b64.encode("ascii")
    al = struct.pack(">Q", len(aad) * 8)
    hmac_input = aad + iv + ciphertext + al
    full_hmac = hmac.new(mac_key, hmac_input, hashlib.sha512).digest()
    tag = full_hmac[:32]
    tag_b64 = _base64url_encode(tag)

    return f"{header_b64}.{ek_b64}.{iv_b64}.{ct_b64}.{tag_b64}"


# ──────────────────────────────────────────────
# Test JWE decryption
# ──────────────────────────────────────────────


class TestJWEDecryption:
    def setup_method(self):
        # Clear cached key before each test
        auth_mod._jwe_key_cache = None

    def teardown_method(self):
        auth_mod._jwe_key_cache = None

    def test_decrypt_valid_token(self):
        """decrypt_nextauth_jwe should correctly decrypt a token we create."""
        claims = {
            "sub": "user-123",
            "brandId": "brand-456",
            "role": "admin",
            "exp": int(time.time()) + 3600,
        }
        token = _make_jwe_token(claims)

        with patch.object(auth_mod, "settings") as mock_settings:
            mock_settings.auth_secret = TEST_AUTH_SECRET
            result = decrypt_nextauth_jwe(token)

        assert result["sub"] == "user-123"
        assert result["brandId"] == "brand-456"
        assert result["role"] == "admin"

    def test_decrypt_invalid_token_format(self):
        """Should raise ValueError for non-5-part token."""
        with patch.object(auth_mod, "settings") as mock_settings:
            mock_settings.auth_secret = TEST_AUTH_SECRET
            with pytest.raises(ValueError, match="Invalid JWE"):
                decrypt_nextauth_jwe("not.a.valid.token")

    def test_decrypt_tampered_token(self):
        """Should raise ValueError when tag doesn't match (tampered ciphertext)."""
        claims = {"sub": "user-123"}
        token = _make_jwe_token(claims)
        parts = token.split(".")
        # Tamper with ciphertext
        parts[3] = parts[3][:-4] + "AAAA"
        tampered = ".".join(parts)

        with patch.object(auth_mod, "settings") as mock_settings:
            mock_settings.auth_secret = TEST_AUTH_SECRET
            with pytest.raises(ValueError, match="tag mismatch"):
                decrypt_nextauth_jwe(tampered)


# ──────────────────────────────────────────────
# Test API Key verification
# ──────────────────────────────────────────────


class TestAPIKeyVerification:
    @pytest.mark.asyncio
    async def test_valid_api_key(self):
        """Should return auth info for a valid, non-expired, non-revoked key."""
        test_key = "sk-test1234567890abcdef"

        mock_row = {
            "brand_id": "brand-abc",
            "name": "Test Key",
            "expires_at": None,
            "revoked": False,
        }

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=mock_row)
        mock_pool.execute = AsyncMock()

        with patch.object(auth_mod, "get_pool", return_value=mock_pool):
            result = await _verify_api_key(test_key)

        assert result is not None
        assert result["brand_id"] == "brand-abc"
        assert result["name"] == "Test Key"

    @pytest.mark.asyncio
    async def test_invalid_prefix(self):
        """Keys not starting with 'sk-' should return None immediately."""
        result = await _verify_api_key("not-a-valid-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_too_short_key(self):
        """Keys shorter than 12 chars should return None."""
        result = await _verify_api_key("sk-short")
        assert result is None

    @pytest.mark.asyncio
    async def test_revoked_key(self):
        """Revoked keys should return None."""
        test_key = "sk-revokedkey12345"
        mock_row = {
            "brand_id": "brand-abc",
            "name": "Revoked Key",
            "expires_at": None,
            "revoked": True,
        }

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=mock_row)

        with patch.object(auth_mod, "get_pool", return_value=mock_pool):
            result = await _verify_api_key(test_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_expired_key(self):
        """Expired keys should return None."""
        test_key = "sk-expiredkey12345"
        mock_expires = MagicMock()
        mock_expires.timestamp.return_value = time.time() - 3600  # Expired 1h ago

        mock_row = {
            "brand_id": "brand-abc",
            "name": "Expired Key",
            "expires_at": mock_expires,
            "revoked": False,
        }

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=mock_row)

        with patch.object(auth_mod, "get_pool", return_value=mock_pool):
            result = await _verify_api_key(test_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_key_not_found_in_db(self):
        """Non-existent key should return None."""
        test_key = "sk-doesnotexist12345"

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with patch.object(auth_mod, "get_pool", return_value=mock_pool):
            result = await _verify_api_key(test_key)

        assert result is None


# ──────────────────────────────────────────────
# Test auth middleware path skipping
# ──────────────────────────────────────────────


class TestAuthMiddlewarePaths:
    def test_health_skips_auth(self):
        """GET /health should not require authentication."""
        assert "/health" in PUBLIC_PATHS

    def test_metrics_skips_auth(self):
        """GET /metrics should not require authentication."""
        assert "/metrics" in PUBLIC_PATHS

    def test_docs_skips_auth(self):
        """Docs endpoints skip auth."""
        assert "/docs" in PUBLIC_PATHS
        assert "/openapi.json" in PUBLIC_PATHS

    def test_non_public_path_not_in_set(self):
        """Arbitrary paths should NOT be in public paths."""
        assert "/api/chat" not in PUBLIC_PATHS
        assert "/prompt/build" not in PUBLIC_PATHS


class _FakeHeaders(dict):
    """A dict subclass that behaves like Starlette's Headers for .get()."""
    pass


class TestAuthMiddlewareBlocking:
    """Test that the middleware blocks requests without proper auth."""

    @pytest.mark.asyncio
    async def test_blocks_request_without_token(self):
        """Requests without any auth header should get 401."""
        middleware = AuthMiddleware(app=MagicMock())

        # Create a mock request for a protected path
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"
        mock_request.headers = _FakeHeaders()

        mock_call_next = AsyncMock()

        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should return 401 without calling the next handler
        assert response.status_code == 401
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocks_request_with_invalid_bearer(self):
        """Request with 'Bearer' but invalid token should get 401."""
        middleware = AuthMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"
        mock_request.headers = _FakeHeaders({
            "authorization": "Bearer invalid-token-not-jwe-not-sk",
        })

        # Clear the key cache
        auth_mod._jwe_key_cache = None

        with patch.object(auth_mod, "settings") as mock_settings:
            mock_settings.service_token = "some-service-token"
            mock_settings.auth_secret = TEST_AUTH_SECRET

            mock_call_next = AsyncMock()
            response = await middleware.dispatch(mock_request, mock_call_next)

            assert response.status_code == 401
            mock_call_next.assert_not_called()

        auth_mod._jwe_key_cache = None
