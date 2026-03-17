"""Usage metering — Redis counters with periodic flush to PostgreSQL."""

import asyncio
from datetime import date

import structlog
import redis.asyncio as aioredis

from ai_core.config import settings

logger = structlog.get_logger()

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _counter_key(brand_id: str, usage_type: str) -> str:
    today = date.today().isoformat()
    return f"usage:{brand_id}:{usage_type}:{today}"


async def increment(brand_id: str, usage_type: str, count: int = 1) -> int:
    """Increment a usage counter in Redis.

    Args:
        brand_id: The brand UUID.
        usage_type: "conversation", "tts_call", or "llm_token".
        count: Amount to increment.

    Returns:
        New counter value.
    """
    r = await _get_redis()
    key = _counter_key(brand_id, usage_type)
    value = await r.incrby(key, count)
    # Auto-expire counters after 48 hours
    await r.expire(key, 172800)
    return value


async def get_count(brand_id: str, usage_type: str) -> int:
    """Get current usage count for today."""
    r = await _get_redis()
    key = _counter_key(brand_id, usage_type)
    value = await r.get(key)
    return int(value) if value else 0


async def flush_to_db(pool) -> None:
    """Flush Redis counters to PostgreSQL usage_records table.

    Called periodically by a background task.
    """
    r = await _get_redis()
    today = date.today().isoformat()

    # Scan for all usage keys for today
    cursor = 0
    flushed = 0
    while True:
        cursor, keys = await r.scan(cursor, match=f"usage:*:*:{today}", count=100)
        for key in keys:
            parts = key.split(":")
            if len(parts) != 4:
                continue
            _, brand_id, usage_type, _ = parts
            count = await r.get(key)
            if not count:
                continue

            await pool.execute(
                """
                INSERT INTO usage_records (id, brand_id, type, count, date, created_at)
                VALUES (gen_random_uuid(), $1, $2, $3, $4, now())
                ON CONFLICT (brand_id, type, date) DO UPDATE SET count = $3
                """,
                brand_id,
                usage_type.upper(),
                int(count),
                today,
            )
            flushed += 1

        if cursor == 0:
            break

    if flushed > 0:
        logger.info("usage.flushed_to_db", count=flushed)


async def start_flush_task(pool) -> asyncio.Task:
    """Start background task that flushes every 5 minutes."""
    async def _loop():
        while True:
            await asyncio.sleep(300)  # 5 minutes
            try:
                await flush_to_db(pool)
            except Exception:
                logger.exception("usage.flush_error")

    return asyncio.create_task(_loop())
