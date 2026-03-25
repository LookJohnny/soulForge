"""Relationship Evolution Engine — tracks affinity between character and user.

Affinity score (0-1000) determines relationship stage, which influences
system prompt tone, proactive trigger probability, and memory depth.

Stages:
- 陌生人 STRANGER    (0-99)
- 初识   ACQUAINTANCE (100-299)
- 熟人   FAMILIAR     (300-599)
- 好友   FRIEND       (600-849)
- 挚友   BESTFRIEND   (850-1000)
"""

from datetime import date, timedelta

import structlog
import asyncpg

from ai_core.services.cache import CacheService

logger = structlog.get_logger()

_REL_CACHE_TTL = 3600  # 1 hour

# Stage thresholds
STAGE_THRESHOLDS = [
    (850, 1000, "BESTFRIEND"),
    (600, 849, "FRIEND"),
    (300, 599, "FAMILIAR"),
    (100, 299, "ACQUAINTANCE"),
    (0, 99, "STRANGER"),
]

# Stage descriptions for system prompt injection
STAGE_PROMPTS: dict[str, str] = {
    "STRANGER": "你们还不太熟，要礼貌友好，但不要太热情",
    "ACQUAINTANCE": "你们刚认识不久，可以慢慢熟络起来",
    "FAMILIAR": "你们已经比较熟了，可以开一些小玩笑",
    "FRIEND": "你们是好朋友，可以很随意地聊天，偶尔撒娇",
    "BESTFRIEND": "你们是无话不说的好朋友，非常亲密，可以分享秘密和心事",
}

# How many memories to inject per stage
STAGE_MEMORY_DEPTH: dict[str, int] = {
    "STRANGER": 2,
    "ACQUAINTANCE": 4,
    "FAMILIAR": 6,
    "FRIEND": 8,
    "BESTFRIEND": 10,
}

# Proactive trigger probability per stage
STAGE_TRIGGER_PROB: dict[str, float] = {
    "STRANGER": 0.0,
    "ACQUAINTANCE": 0.0,
    "FAMILIAR": 0.5,
    "FRIEND": 0.7,
    "BESTFRIEND": 0.9,
}

_DEFAULT_STATE = {
    "affinity": 0,
    "stage": "STRANGER",
    "streak_days": 0,
    "last_interaction_date": None,
    "turn_count_today": 0,
}


def _affinity_to_stage(affinity: int) -> str:
    for lo, hi, stage in STAGE_THRESHOLDS:
        if lo <= affinity <= hi:
            return stage
    return "STRANGER"


class RelationshipEngine:
    """Track and evolve character-user relationship."""

    def __init__(self, pool: asyncpg.Pool, cache: CacheService):
        self.pool = pool
        self.cache = cache

    def _cache_key(self, end_user_id: str, character_id: str) -> str:
        return f"rel:{end_user_id}:{character_id}"

    async def get_state(self, end_user_id: str, character_id: str) -> dict:
        """Load relationship state, cached in Redis."""
        if not end_user_id:
            return dict(_DEFAULT_STATE)

        key = self._cache_key(end_user_id, character_id)
        cached = await self.cache.get_json(key)
        if cached is not None:
            return cached

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT affinity, stage, streak_days, last_interaction_date, turn_count_today
                   FROM relationship_states
                   WHERE end_user_id = $1 AND character_id = $2""",
                end_user_id,
                character_id,
            )

        if not row:
            return dict(_DEFAULT_STATE)

        state = {
            "affinity": row["affinity"],
            "stage": row["stage"],
            "streak_days": row["streak_days"],
            "last_interaction_date": row["last_interaction_date"].isoformat() if row["last_interaction_date"] else None,
            "turn_count_today": row["turn_count_today"],
        }
        await self.cache.set_json(key, state, ttl=_REL_CACHE_TTL)
        return state

    async def award_points(
        self,
        end_user_id: str,
        character_id: str,
        memory_types: list[str] | None = None,
        touch_bonus: int = 0,
    ) -> dict:
        """Award affinity points after a conversation turn. Returns updated state."""
        if not end_user_id:
            return dict(_DEFAULT_STATE)

        state = await self.get_state(end_user_id, character_id)
        today = date.today()
        last_date = None
        if state["last_interaction_date"]:
            try:
                last_date = date.fromisoformat(state["last_interaction_date"])
            except (ValueError, TypeError):
                last_date = None

        is_first_today = (last_date != today)

        # Update streak
        streak = state["streak_days"]
        turn_count = state["turn_count_today"]
        if is_first_today:
            turn_count = 0
            if last_date == today - timedelta(days=1):
                streak += 1
            elif last_date is None or last_date < today - timedelta(days=1):
                streak = 1
        turn_count += 1

        # Calculate points
        points = 3  # base
        if is_first_today:
            points += 10  # daily first
        if streak >= 2:
            points += 5  # streak bonus
        if turn_count > 5:
            points += 2  # long conversation
        if memory_types:
            for mt in memory_types:
                if mt in ("PREFERENCE", "EVENT"):
                    points += 5
        if touch_bonus > 0:
            points += touch_bonus

        new_affinity = min(1000, state["affinity"] + points)
        new_stage = _affinity_to_stage(new_affinity)

        # Upsert with atomic update
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO relationship_states
                       (id, end_user_id, character_id, affinity, stage,
                        streak_days, last_interaction_date, turn_count_today,
                        created_at, updated_at)
                   VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, now(), now())
                   ON CONFLICT (end_user_id, character_id) DO UPDATE SET
                       affinity = $3,
                       stage = $4,
                       streak_days = $5,
                       last_interaction_date = $6,
                       turn_count_today = $7,
                       updated_at = now()""",
                end_user_id,
                character_id,
                new_affinity,
                new_stage,
                streak,
                today,
                turn_count,
            )

        # Invalidate cache
        await self.cache.delete(self._cache_key(end_user_id, character_id))

        updated = {
            "affinity": new_affinity,
            "stage": new_stage,
            "streak_days": streak,
            "last_interaction_date": today.isoformat(),
            "turn_count_today": turn_count,
        }

        if new_stage != state["stage"]:
            logger.info(
                "relationship.stage_up",
                end_user_id=end_user_id,
                character_id=character_id,
                old_stage=state["stage"],
                new_stage=new_stage,
                affinity=new_affinity,
            )

        return updated

    def get_stage_prompt(self, stage: str) -> str:
        return STAGE_PROMPTS.get(stage, STAGE_PROMPTS["STRANGER"])

    def get_memory_depth(self, stage: str) -> int:
        return STAGE_MEMORY_DEPTH.get(stage, 2)
