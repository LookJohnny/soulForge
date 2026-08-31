"""Relationship engine (Postgres/Redis state, schema sniffing, REST helpers).

The pure math moved to soulforge_harness.persona.relationship; this module
keeps the stateful engine and re-exports everything for compatibility.
"""

from __future__ import annotations

import json
import random  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from datetime import UTC, date, datetime, timedelta  # noqa: F401
from typing import Any

import asyncpg
import structlog
from soulforge_harness.persona.relationship import (  # noqa: F401
    _AXES_COLUMNS,
    _DECAY_MIN_GAP_S,
    _EMOTIONAL_MOODS,
    _NEGATIVE_MOODS,
    _POSITIVE_MOODS,
    _REL_CACHE_TTL,
    _REQ_LABELS,
    APP_MODES,
    AXES,
    AXIS_LIMITS,
    COMPANION_STAGE,
    LEGACY_STAGE_ALIASES,
    ROMANCE_STAGES,
    STAGE_BEHAVIORS,
    STAGE_MEMORY_DEPTH,
    STAGE_ORDER,
    STAGE_PROMPTS,
    STAGE_REQUIREMENTS,
    STAGE_TRIGGER_PROB,
    STAGE_ZH,
    DecayResult,
    StageBehavior,
    TurnResult,
    _band,
    _clamp,
    _iso,
    _parse_dt,
    apply_deltas,
    apply_time_decay,
    baseline_impact,
    compute_stage,
    days_known,
    default_state,
    describe_axes,
    describe_for_prompt,
    lock_relationship_axes,
    meets_requirements,
    merge_updates,
    near_stage,
    normalize_stage,
    relationship_payload,
    stage_index,
)

from ai_core.services.cache import CacheService

logger = structlog.get_logger()


class RelationshipEngine:
    """Track and evolve the character–user relationship."""

    def __init__(self, pool: asyncpg.Pool, cache: CacheService):
        self.pool = pool
        self.cache = cache
        self._axes_schema: bool | None = None  # sniffed on first DB access

    def _cache_key(self, end_user_id: str, character_id: str) -> str:
        return f"rel:{end_user_id}:{character_id}"

    # ── read ─────────────────────────────────────

    async def get_state(self, end_user_id: str, character_id: str) -> dict:
        """Load relationship state (Redis-cached), applying lazy wall-clock decay."""
        if not end_user_id:
            return default_state()

        key = self._cache_key(end_user_id, character_id)
        cached = await self.cache.get_json(key)
        if cached is not None:
            state = {**default_state(), **cached}
        else:
            state = await self._load(end_user_id, character_id)
            await self.cache.set_json(key, state, ttl=_REL_CACHE_TTL)

        decay = apply_time_decay(state)
        if decay.applied:
            state = decay.state
            if decay.mood_cause:
                state["_decay_mood_cause"] = decay.mood_cause
            if decay.deltas:
                logger.info("relationship.decay", end_user_id=end_user_id, deltas=decay.deltas)
            await self._save(end_user_id, character_id, state)
        return state

    async def _ensure_schema(self) -> bool:
        """Sniff once whether migration 005 columns exist (cache hits skip _load)."""
        if self._axes_schema is None:
            try:
                async with self.pool.acquire() as conn:
                    exists = await conn.fetchval(
                        """SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'relationship_states'
                             AND column_name = 'decay_clocks'"""
                    )
                self._axes_schema = bool(exists)
                if not self._axes_schema:
                    logger.warning(
                        "relationship.schema_legacy — run migration 005_relationship_axes"
                    )
            except Exception:
                logger.exception("relationship.schema_check_failed")
                self._axes_schema = False
        return self._axes_schema

    async def _load(self, end_user_id: str, character_id: str) -> dict:
        await self._ensure_schema()
        async with self.pool.acquire() as conn:
            row = None
            if self._axes_schema is not False:
                try:
                    row = await conn.fetchrow(
                        f"""SELECT affinity, stage, streak_days, last_interaction_date,
                                   turn_count_today, {_AXES_COLUMNS}
                            FROM relationship_states
                            WHERE end_user_id = $1 AND character_id = $2""",
                        end_user_id,
                        character_id,
                    )
                    self._axes_schema = True
                except asyncpg.UndefinedColumnError:
                    self._axes_schema = False
                    logger.warning(
                        "relationship.schema_legacy — run migration 005_relationship_axes"
                    )
            if self._axes_schema is False:
                row = await conn.fetchrow(
                    """SELECT affinity, stage, streak_days, last_interaction_date, turn_count_today
                       FROM relationship_states
                       WHERE end_user_id = $1 AND character_id = $2""",
                    end_user_id,
                    character_id,
                )
        if not row:
            return default_state()
        return self._row_to_state(row)

    def _row_to_state(self, row: Any) -> dict:
        state = default_state()
        state["affinity"] = state["affection"] = row["affinity"]
        state["stage"] = normalize_stage(row["stage"])
        state["streak_days"] = row["streak_days"]
        state["last_interaction_date"] = (
            row["last_interaction_date"].isoformat() if row["last_interaction_date"] else None
        )
        state["turn_count_today"] = row["turn_count_today"]
        if self._axes_schema:
            for axis in ("trust", "intimacy", "comfort", "respect", "energy"):
                state[axis] = row[axis]
            state["app_mode"] = row["app_mode"] or "dating_sim"
            state["saved_stage"] = row["saved_stage"]
            state["total_interactions"] = row["total_interactions"] or 0
            state["first_interaction_at"] = _iso(row["first_interaction_at"])
            state["last_interaction_at"] = _iso(row["last_interaction_at"])
            state["decay_clocks"] = _json_field(row["decay_clocks"], {})
            state["completed_events"] = _json_field(row["completed_events"], [])
            if state["app_mode"] == "companion":
                state["stage"] = COMPANION_STAGE
        return state

    # ── write ────────────────────────────────────

    async def _save(self, end_user_id: str, character_id: str, state: dict) -> None:
        await self._ensure_schema()
        state = {k: v for k, v in state.items() if not k.startswith("_")}
        last_date = (
            date.fromisoformat(state["last_interaction_date"])
            if state.get("last_interaction_date")
            else None
        )
        db_stage = (
            state["stage"]
            if state["stage"] != COMPANION_STAGE
            else (state.get("saved_stage") or "STRANGER")
        )
        async with self.pool.acquire() as conn:
            if self._axes_schema:
                await conn.execute(
                    """INSERT INTO relationship_states
                           (id, end_user_id, character_id, affinity, stage, streak_days,
                            last_interaction_date, turn_count_today,
                            trust, intimacy, comfort, respect, energy, app_mode, saved_stage,
                            total_interactions, first_interaction_at, last_interaction_at,
                            decay_clocks, completed_events, created_at, updated_at)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7,
                               $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                               $18::jsonb, $19::jsonb, now(), now())
                       ON CONFLICT (end_user_id, character_id) DO UPDATE SET
                           affinity = $3, stage = $4, streak_days = $5,
                           last_interaction_date = $6, turn_count_today = $7,
                           trust = $8, intimacy = $9, comfort = $10, respect = $11,
                           energy = $12,
                           app_mode = $13, saved_stage = $14, total_interactions = $15,
                           first_interaction_at =
                               COALESCE(relationship_states.first_interaction_at, $16),
                           last_interaction_at = $17, decay_clocks = $18::jsonb,
                           completed_events = $19::jsonb, updated_at = now()""",
                    end_user_id,
                    character_id,
                    state["affection"],
                    db_stage,
                    state["streak_days"],
                    last_date,
                    state["turn_count_today"],
                    state["trust"],
                    state["intimacy"],
                    state["comfort"],
                    state["respect"],
                    state["energy"],
                    state["app_mode"],
                    state.get("saved_stage"),
                    state["total_interactions"],
                    _parse_dt(state.get("first_interaction_at")),
                    _parse_dt(state.get("last_interaction_at")),
                    json.dumps(state.get("decay_clocks") or {}),
                    json.dumps(state.get("completed_events") or []),
                )
            else:
                legacy_stage = _to_legacy_stage(db_stage)
                await conn.execute(
                    """INSERT INTO relationship_states
                           (id, end_user_id, character_id, affinity, stage,
                            streak_days, last_interaction_date, turn_count_today,
                            created_at, updated_at)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, now(), now())
                       ON CONFLICT (end_user_id, character_id) DO UPDATE SET
                           affinity = $3, stage = $4, streak_days = $5,
                           last_interaction_date = $6, turn_count_today = $7, updated_at = now()""",
                    end_user_id,
                    character_id,
                    state["affection"],
                    legacy_stage,
                    state["streak_days"],
                    last_date,
                    state["turn_count_today"],
                )
        await self.cache.set_json(
            self._cache_key(end_user_id, character_id), state, ttl=_REL_CACHE_TTL
        )

    # ── per turn ─────────────────────────────────

    async def apply_turn(
        self,
        end_user_id: str,
        character_id: str,
        *,
        user_mood: str | None = "neutral",
        user_text: str = "",
        llm_suggestion: dict | None = None,
        memory_types: list[str] | None = None,
        touch_bonus: int = 0,
        now: datetime | None = None,
    ) -> TurnResult:
        """Apply one conversation turn. Returns the new state and what moved."""
        if not end_user_id:
            return TurnResult(state=default_state(), deltas={})
        now = now or datetime.now(UTC)
        state = await self.get_state(end_user_id, character_id)
        today = now.date()
        last_date = None
        if state.get("last_interaction_date"):
            try:
                last_date = date.fromisoformat(state["last_interaction_date"])
            except (ValueError, TypeError):
                last_date = None
        is_first_today = last_date != today

        streak = state["streak_days"]
        turn_count = state["turn_count_today"]
        if is_first_today:
            turn_count = 0
            if last_date == today - timedelta(days=1):
                streak += 1
            elif last_date is None or last_date < today - timedelta(days=1):
                streak = 1
        turn_count += 1

        baseline = baseline_impact(
            state,
            user_mood=user_mood,
            user_text=user_text,
            touch_bonus=touch_bonus,
            memory_types=memory_types,
            is_first_today=is_first_today,
            streak_days=streak,
        )
        deltas = merge_updates(baseline, llm_suggestion)
        if state.get("app_mode") == "companion":
            deltas = lock_relationship_axes(deltas)

        new = apply_deltas(state, deltas)
        new.update(
            streak_days=streak,
            turn_count_today=turn_count,
            last_interaction_date=today.isoformat(),
            total_interactions=state.get("total_interactions", 0) + 1,
            first_interaction_at=state.get("first_interaction_at") or _iso(now),
            last_interaction_at=_iso(now),
        )
        old_stage = normalize_stage(state["stage"])
        new_stage = compute_stage(new)
        new["stage"] = new_stage
        changed = new_stage != old_stage

        await self._save(end_user_id, character_id, new)
        if changed:
            logger.info(
                "relationship.stage_change",
                end_user_id=end_user_id,
                character_id=character_id,
                old_stage=old_stage,
                new_stage=new_stage,
                axes={a: new[a] for a in AXES},
            )
        return TurnResult(
            state=new,
            deltas=deltas,
            stage_changed=changed,
            from_stage=old_stage if changed else None,
        )

    async def award_points(
        self,
        end_user_id: str,
        character_id: str,
        memory_types: list[str] | None = None,
        touch_bonus: int = 0,
    ) -> dict:
        """Backward-compatible wrapper around :meth:`apply_turn`."""
        result = await self.apply_turn(
            end_user_id, character_id, memory_types=memory_types, touch_bonus=touch_bonus
        )
        return result.state

    # ── modes & events ───────────────────────────

    async def set_app_mode(self, end_user_id: str, character_id: str, app_mode: str) -> dict:
        if app_mode not in APP_MODES:
            raise ValueError(f"unknown app_mode {app_mode!r}")
        state = await self.get_state(end_user_id, character_id)
        if state.get("app_mode") == app_mode:
            return state
        if app_mode == "companion":
            state["saved_stage"] = normalize_stage(state["stage"])
            state["stage"] = COMPANION_STAGE
        else:
            state["stage"] = normalize_stage(state.get("saved_stage") or "STRANGER")
            state["saved_stage"] = None
        state["app_mode"] = app_mode
        state["stage"] = compute_stage(state)
        await self._save(end_user_id, character_id, state)
        return state

    async def record_event(
        self, end_user_id: str, character_id: str, event_id: str, state_changes: dict | None = None
    ) -> TurnResult:
        """Mark an event completed (Phase 4) and apply its state changes."""
        state = await self.get_state(end_user_id, character_id)
        completed = list(state.get("completed_events") or [])
        if event_id not in completed:
            completed.append(event_id)
        state["completed_events"] = completed
        deltas = {axis: int((state_changes or {}).get(axis, 0) or 0) for axis in AXES}
        if state.get("app_mode") == "companion":
            deltas = lock_relationship_axes(deltas)
        new = apply_deltas(state, deltas)
        old_stage = normalize_stage(state["stage"])
        new["stage"] = compute_stage(new)
        changed = new["stage"] != old_stage
        await self._save(end_user_id, character_id, new)
        return TurnResult(
            state=new,
            deltas=deltas,
            stage_changed=changed,
            from_stage=old_stage if changed else None,
        )

    # ── helpers ──────────────────────────────────

    def get_stage_prompt(self, stage: str) -> str:
        return STAGE_PROMPTS.get(normalize_stage(stage), STAGE_PROMPTS["STRANGER"])

    def get_memory_depth(self, stage: str) -> int:
        return STAGE_MEMORY_DEPTH.get(normalize_stage(stage), 2)


def _json_field(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _to_legacy_stage(stage: str) -> str:
    """Map new stage names onto the five old enum values (pre-005 databases)."""
    stage = normalize_stage(stage)
    if stage in ("STRANGER", "ACQUAINTANCE", "FRIEND"):
        return stage
    if stage == "CLOSE_FRIEND":
        return "BESTFRIEND"
    if stage in ROMANCE_STAGES:
        return "BESTFRIEND"
    return "STRANGER"


# Kept for old imports/tests: the single-axis threshold mapping.
STAGE_THRESHOLDS = [
    (850, 1000, "CLOSE_FRIEND"),
    (600, 849, "FRIEND"),
    (300, 599, "FRIEND"),
    (100, 299, "ACQUAINTANCE"),
    (0, 99, "STRANGER"),
]


def _affinity_to_stage(affinity: int) -> str:
    for lo, hi, stage in STAGE_THRESHOLDS:
        if lo <= affinity <= hi:
            return stage
    return "STRANGER"
