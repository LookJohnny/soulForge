"""Personality Micro-Drift — character traits slowly adapt per user.

After each conversation, emotion patterns and memory types are analyzed
to compute tiny trait offsets (max ±1 per trait per day, max ±10 total).
Drift stored as JSONB in user_customizations.personality_drift.
"""

from datetime import date

import structlog
import asyncpg

from ai_core.services.cache import CacheService

logger = structlog.get_logger()

# Max drift per trait (absolute value)
_MAX_DRIFT_PER_TRAIT = 10
# Max sum of all absolute drifts
_MAX_TOTAL_DRIFT = 30

# Traits that can drift
_DRIFTABLE_TRAITS = ("extrovert", "humor", "warmth", "curiosity", "energy")


def merge_personality_with_drift(
    base: dict, offsets: dict | None, drift: dict | None
) -> dict:
    """Merge base personality + user offsets + micro-drift, clamp to 0-100."""
    result = dict(base)
    if offsets:
        for key, offset in offsets.items():
            if key in result:
                result[key] = result[key] + offset
    if drift:
        for key, d in drift.items():
            if key.startswith("_"):
                continue  # skip metadata like _last_drift_date
            if key in result:
                result[key] = result[key] + d
    for key in result:
        result[key] = max(0, min(100, result[key]))
    return result


class PersonalityDriftService:
    """Compute and apply personality micro-drift per user."""

    def __init__(self, pool: asyncpg.Pool, cache: CacheService):
        self.pool = pool
        self.cache = cache

    async def get_drift(self, end_user_id: str, character_id: str) -> dict:
        """Read personality_drift from user_customizations. Cached."""
        if not end_user_id:
            return {}

        key = f"drift:{end_user_id}:{character_id}"
        cached = await self.cache.get_json(key)
        if cached is not None:
            return cached

        async with self.pool.acquire() as conn:
            row = await conn.fetchval(
                """SELECT personality_drift FROM user_customizations
                   WHERE end_user_id = $1 AND character_id = $2 AND is_active = true""",
                end_user_id,
                character_id,
            )

        import json
        drift = {}
        if row:
            if isinstance(row, str):
                drift = json.loads(row)
            elif isinstance(row, dict):
                drift = row

        await self.cache.set_json(key, drift, ttl=3600)
        return drift

    async def compute_and_apply_drift(
        self,
        end_user_id: str,
        character_id: str,
        emotion_history: list[str],
        memory_types: list[str],
    ) -> None:
        """Compute trait drift from emotion/memory patterns and store it.

        Called async after each conversation turn. Max 1 drift per day.
        """
        if not end_user_id:
            return

        try:
            drift = await self.get_drift(end_user_id, character_id)
            today_str = date.today().isoformat()

            # Already drifted today? Skip
            if drift.get("_last_drift_date") == today_str:
                return

            # Count emotions in this session
            from collections import Counter
            emotion_counts = Counter(emotion_history)

            # Compute drift deltas
            deltas: dict[str, int] = {}

            if emotion_counts.get("happy", 0) >= 2:
                deltas["humor"] = 1
            if emotion_counts.get("curious", 0) >= 2:
                deltas["curiosity"] = 1
            if emotion_counts.get("worried", 0) >= 1 or emotion_counts.get("sad", 0) >= 1:
                deltas["warmth"] = 1
            if emotion_counts.get("playful", 0) >= 2:
                deltas["energy"] = 1
            if any(mt in ("PREFERENCE", "EVENT") for mt in memory_types):
                deltas.setdefault("warmth", 0)
                deltas["warmth"] = min(1, deltas["warmth"] + 1)

            if not deltas:
                return  # Nothing to drift

            # Apply deltas with bounds
            new_drift = {k: v for k, v in drift.items() if not k.startswith("_")}
            for trait, delta in deltas.items():
                current = new_drift.get(trait, 0)
                new_val = max(-_MAX_DRIFT_PER_TRAIT, min(_MAX_DRIFT_PER_TRAIT, current + delta))
                new_drift[trait] = new_val

            # Check total drift bound
            total = sum(abs(v) for v in new_drift.values())
            if total > _MAX_TOTAL_DRIFT:
                return  # Hit ceiling, no more drift

            new_drift["_last_drift_date"] = today_str

            # Write to DB
            import json
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """UPDATE user_customizations
                       SET personality_drift = $3, updated_at = now()
                       WHERE end_user_id = $1 AND character_id = $2 AND is_active = true""",
                    end_user_id,
                    character_id,
                    json.dumps(new_drift),
                )

            # Invalidate caches
            await self.cache.delete(f"drift:{end_user_id}:{character_id}")
            await self.cache.delete(f"custom:{end_user_id}:{character_id}")

            logger.info(
                "personality.drift_applied",
                end_user_id=end_user_id,
                character_id=character_id,
                deltas=deltas,
            )
        except Exception:
            logger.exception("personality.drift_error")
