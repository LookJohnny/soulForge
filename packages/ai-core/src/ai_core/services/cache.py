"""Redis-backed cache service with TTL support.

Provides get/set/delete/invalidate_pattern for caching character data,
customizations, and voice profiles to reduce database load.
"""

import json

import redis.asyncio as aioredis
import structlog

from ai_core.config import settings

logger = structlog.get_logger()

_redis_client: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """Lazily create and return the shared Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


class CacheService:
    """Redis-backed cache with TTL support."""

    def __init__(self, redis_client: aioredis.Redis | None = None):
        self._client = redis_client

    async def _redis(self) -> aioredis.Redis:
        if self._client is None:
            self._client = await _get_redis()
        return self._client

    async def get(self, key: str) -> str | None:
        """Get a value by key. Returns None if not found or on error."""
        try:
            r = await self._redis()
            return await r.get(key)
        except Exception as e:
            logger.warning("cache.get_error", key=key, error=str(e))
            return None

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        """Set a value with TTL (in seconds). Default 1 hour."""
        try:
            r = await self._redis()
            await r.set(key, value, ex=ttl)
        except Exception as e:
            logger.warning("cache.set_error", key=key, error=str(e))

    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        try:
            r = await self._redis()
            await r.delete(key)
        except Exception as e:
            logger.warning("cache.delete_error", key=key, error=str(e))

    async def invalidate_pattern(self, pattern: str) -> None:
        """Delete all keys matching a glob pattern (e.g. 'char:*').

        Uses SCAN to avoid blocking Redis on large keyspaces.
        """
        try:
            r = await self._redis()
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("cache.invalidate_error", pattern=pattern, error=str(e))

    # ─── JSON convenience helpers ──────────────────────

    async def get_json(self, key: str) -> dict | None:
        """Get and deserialize a JSON value."""
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set_json(self, key: str, value: dict, ttl: int = 3600) -> None:
        """Serialize and set a JSON value."""
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl=ttl)
