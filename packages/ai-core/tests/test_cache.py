"""Tests for the Redis cache service — uses mock Redis to avoid real connections."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_core.services.cache import CacheService


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _make_mock_redis():
    """Create a mock Redis client with common async methods."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock()
    mock.delete = AsyncMock()
    mock.scan = AsyncMock(return_value=(0, []))
    return mock


# ──────────────────────────────────────────────
# Basic set/get/delete
# ──────────────────────────────────────────────


class TestCacheBasicOperations:
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(return_value="hello")
        cache = CacheService(redis_client=mock_redis)

        await cache.set("key1", "hello", ttl=300)
        result = await cache.get("key1")

        mock_redis.set.assert_called_once_with("key1", "hello", ex=300)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_get_returns_none_when_missing(self):
        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(return_value=None)
        cache = CacheService(redis_client=mock_redis)

        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        mock_redis = _make_mock_redis()
        cache = CacheService(redis_client=mock_redis)

        await cache.delete("key1")
        mock_redis.delete.assert_called_once_with("key1")

    @pytest.mark.asyncio
    async def test_set_default_ttl(self):
        """Default TTL should be 3600 seconds (1 hour)."""
        mock_redis = _make_mock_redis()
        cache = CacheService(redis_client=mock_redis)

        await cache.set("key1", "value1")
        mock_redis.set.assert_called_once_with("key1", "value1", ex=3600)


# ──────────────────────────────────────────────
# TTL verification
# ──────────────────────────────────────────────


class TestCacheTTL:
    @pytest.mark.asyncio
    async def test_ttl_passed_correctly(self):
        mock_redis = _make_mock_redis()
        cache = CacheService(redis_client=mock_redis)

        await cache.set("key", "val", ttl=600)
        mock_redis.set.assert_called_once_with("key", "val", ex=600)

    @pytest.mark.asyncio
    async def test_custom_ttl_values(self):
        mock_redis = _make_mock_redis()
        cache = CacheService(redis_client=mock_redis)

        for ttl in [1, 60, 300, 3600, 86400]:
            mock_redis.set.reset_mock()
            await cache.set("k", "v", ttl=ttl)
            mock_redis.set.assert_called_once_with("k", "v", ex=ttl)


# ──────────────────────────────────────────────
# invalidate_pattern
# ──────────────────────────────────────────────


class TestCacheInvalidatePattern:
    @pytest.mark.asyncio
    async def test_invalidate_pattern_deletes_matching_keys(self):
        mock_redis = _make_mock_redis()
        # Simulate scan returning keys then finishing
        mock_redis.scan = AsyncMock(
            return_value=(0, ["char:abc", "char:def"])
        )
        cache = CacheService(redis_client=mock_redis)

        await cache.invalidate_pattern("char:*")

        mock_redis.scan.assert_called_once_with(cursor=0, match="char:*", count=100)
        mock_redis.delete.assert_called_once_with("char:abc", "char:def")

    @pytest.mark.asyncio
    async def test_invalidate_pattern_no_keys(self):
        mock_redis = _make_mock_redis()
        mock_redis.scan = AsyncMock(return_value=(0, []))
        cache = CacheService(redis_client=mock_redis)

        await cache.invalidate_pattern("nonexistent:*")

        mock_redis.scan.assert_called_once()
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalidate_pattern_multi_scan(self):
        """When scan returns a non-zero cursor, we continue scanning."""
        mock_redis = _make_mock_redis()
        mock_redis.scan = AsyncMock(
            side_effect=[
                (42, ["key:1", "key:2"]),  # First scan, cursor=42 means more
                (0, ["key:3"]),  # Second scan, cursor=0 means done
            ]
        )
        cache = CacheService(redis_client=mock_redis)

        await cache.invalidate_pattern("key:*")

        assert mock_redis.scan.call_count == 2
        assert mock_redis.delete.call_count == 2


# ──────────────────────────────────────────────
# JSON convenience methods
# ──────────────────────────────────────────────


class TestCacheJSON:
    @pytest.mark.asyncio
    async def test_set_json_and_get_json(self):
        mock_redis = _make_mock_redis()
        cache = CacheService(redis_client=mock_redis)

        data = {"name": "小熊", "species": "bear"}

        # set_json should serialize to JSON string
        await cache.set_json("char:123", data, ttl=3600)
        expected_json = json.dumps(data, ensure_ascii=False)
        mock_redis.set.assert_called_once_with("char:123", expected_json, ex=3600)

        # get_json should deserialize
        mock_redis.get = AsyncMock(return_value=expected_json)
        result = await cache.get_json("char:123")
        assert result == data

    @pytest.mark.asyncio
    async def test_get_json_returns_none_when_missing(self):
        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(return_value=None)
        cache = CacheService(redis_client=mock_redis)

        result = await cache.get_json("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_json_returns_none_on_invalid_json(self):
        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(return_value="not-valid-json{{{")
        cache = CacheService(redis_client=mock_redis)

        result = await cache.get_json("bad-json-key")
        assert result is None


# ──────────────────────────────────────────────
# Error resilience
# ──────────────────────────────────────────────


class TestCacheErrorResilience:
    @pytest.mark.asyncio
    async def test_get_returns_none_on_redis_error(self):
        """Cache should be resilient — return None on connection errors."""
        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = CacheService(redis_client=mock_redis)

        result = await cache.get("key")
        assert result is None  # No exception raised

    @pytest.mark.asyncio
    async def test_set_does_not_raise_on_redis_error(self):
        """set() should silently log errors, not raise."""
        mock_redis = _make_mock_redis()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = CacheService(redis_client=mock_redis)

        # Should not raise
        await cache.set("key", "value")

    @pytest.mark.asyncio
    async def test_delete_does_not_raise_on_redis_error(self):
        mock_redis = _make_mock_redis()
        mock_redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = CacheService(redis_client=mock_redis)

        await cache.delete("key")

    @pytest.mark.asyncio
    async def test_invalidate_does_not_raise_on_redis_error(self):
        mock_redis = _make_mock_redis()
        mock_redis.scan = AsyncMock(side_effect=ConnectionError("Redis down"))
        cache = CacheService(redis_client=mock_redis)

        await cache.invalidate_pattern("key:*")
