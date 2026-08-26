"""Event engine — decides which scene (if any) happens this turn and records
outcomes so the *next* turn's prompt knows what just happened.

Contract fixes over aikeya:
- The triggered scene is injected into the current turn's prompt and its
  outcome (the user's choice + the companion's canned line) is fed into the
  next turn as ``event_context``, so the LLM never talks past a confession.
- At most one event per turn; at most one *random* event per user per day.
- Companion mode never fires romance-arc events.
- Persistence: ``relationship_events`` rows (when migration 006 exists) plus
  the ``completed_events`` list on the relationship state, which is what stage
  requirements read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from ai_core.services.events.conditions import EventContext, check_condition, describe_condition
from ai_core.services.events.definitions import ALL_EVENTS, EVENTS_BY_ID, EventDef, Scene

logger = structlog.get_logger()

_PENDING_TTL = 3600  # a scene waits this long for a choice
_LAST_TTL = 3600  # how long "what just happened" stays in the prompt


@dataclass
class TriggeredEvent:
    event: EventDef
    scene: Scene
    character_name: str = ""

    def to_payload(self) -> dict:
        intro = self.scene.intro.replace("{name}", self.character_name or "TA")
        return {
            "type": "event",
            "event_id": self.event.id,
            "name": self.event.name,
            "event_type": self.event.event_type,
            "romance": self.event.romance,
            "scene": {
                "id": self.scene.id,
                "intro": intro,
                "dialogue": self.scene.dialogue,
                "choices": [{"text": ch.text} for ch in self.scene.choices],
                "outro": self.scene.outro,
            },
            "state_changes": dict(self.event.state_changes),
            "one_time": self.event.one_time,
        }

    def prompt_context(self) -> str:
        intro = self.scene.intro.replace("{name}", self.character_name or "你")
        lines = ["此刻正发生一个特别的时刻："]
        if intro:
            lines.append(f"（{intro}）")
        lines.append(f"你刚刚说了：「{self.scene.dialogue}」")
        if self.scene.choices:
            lines.append(
                "对方还没回应。把这句话自然地融进你接下来的回复里，不要重复念一遍，也不要抢着替对方回答。"
            )
        else:
            lines.append("把这一刻自然地带进接下来的回复里，不要重复念一遍。")
        return "\n".join(lines)


def is_on_cooldown(event: EventDef, history: list[dict], now: datetime) -> bool:
    """``history`` rows: {"event_id", "completed_at" (iso)}."""
    mine = [h for h in history if h.get("event_id") == event.id]
    if event.one_time:
        return bool(mine)
    if not event.cooldown_days or not mine:
        return False
    last = max(_parse(h.get("completed_at")) or datetime.min.replace(tzinfo=UTC) for h in mine)
    return (now - last).total_seconds() < event.cooldown_days * 86400


def check_all_events(
    ctx: EventContext,
    history: list[dict],
    *,
    events: list[EventDef] | None = None,
    allow_romance: bool = True,
    allow_random: bool = True,
) -> list[EventDef]:
    """All events whose conditions hold right now, highest priority first."""
    out = []
    for ev in events or ALL_EVENTS:
        if ev.romance and not allow_romance:
            continue
        if ev.event_type == "random" and not allow_random:
            continue
        if is_on_cooldown(ev, history, ctx.now):
            continue
        if all(check_condition(c, ctx) for c in ev.conditions):
            out.append(ev)
    return sorted(out, key=lambda e: -e.priority)


def near_trigger_events(
    ctx: EventContext, history: list[dict], events: list[EventDef] | None = None
) -> list[dict]:
    """Events >50% ready (random conditions count half) — for UI hints."""
    out = []
    for ev in events or ALL_EVENTS:
        if is_on_cooldown(ev, history, ctx.now):
            continue
        total = len(ev.conditions) or 1
        met = 0.0
        missing = []
        for c in ev.conditions:
            if c.get("type") == "random_chance":
                met += 0.5
                continue
            if check_condition(c, ctx):
                met += 1
            else:
                missing.append(describe_condition(c))
        progress = met / total * 100
        if 50 < progress < 100:
            out.append(
                {"event_id": ev.id, "name": ev.name, "progress": int(progress), "missing": missing}
            )
    return sorted(out, key=lambda x: -x["progress"])


def _parse(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


class EventEngine:
    """Per-turn trigger + persistence. Needs the relationship engine for the
    stage-affecting side effects and a cache for pending/last-event state."""

    def __init__(self, pool, cache, rel_engine):
        self.pool = pool
        self.cache = cache
        self.rel = rel_engine
        self._table_ok: bool | None = None

    # ── keys ─────────────────────────────────────
    @staticmethod
    def _pending_key(end_user_id: str, character_id: str) -> str:
        return f"event_pending:{end_user_id}:{character_id}"

    @staticmethod
    def _last_key(end_user_id: str, character_id: str) -> str:
        return f"event_last:{end_user_id}:{character_id}"

    @staticmethod
    def _random_day_key(end_user_id: str, character_id: str, now: datetime) -> str:
        return f"event_random_day:{end_user_id}:{character_id}:{now.date().isoformat()}"

    # ── history ──────────────────────────────────
    async def history(self, end_user_id: str, character_id: str) -> list[dict]:
        rows: list[dict] = []
        if self._table_ok is not False:
            try:
                async with self.pool.acquire() as conn:
                    recs = await conn.fetch(
                        """SELECT event_id, event_type, choice_index, outcome, completed_at
                           FROM relationship_events
                           WHERE end_user_id = $1 AND character_id = $2
                           ORDER BY completed_at DESC LIMIT 200""",
                        end_user_id,
                        character_id,
                    )
                rows = [
                    {
                        "event_id": r["event_id"],
                        "event_type": r["event_type"],
                        "choice_index": r["choice_index"],
                        "outcome": r["outcome"],
                        "completed_at": r["completed_at"].isoformat()
                        if r["completed_at"]
                        else None,
                    }
                    for r in recs
                ]
                self._table_ok = True
            except Exception as e:  # UndefinedTable on pre-006 schemas
                if self._table_ok is None:
                    logger.warning("events.table_missing — run migration 006", error=str(e)[:80])
                self._table_ok = False
        return rows

    async def _insert(
        self,
        end_user_id: str,
        character_id: str,
        event: EventDef,
        *,
        choice_index: int | None,
        outcome: str,
        state_changes: dict,
    ) -> None:
        if self._table_ok is False:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO relationship_events
                           (id, end_user_id, character_id, event_id, event_type, choice_index,
                            outcome, state_changes, completed_at)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7::jsonb, now())""",
                    end_user_id,
                    character_id,
                    event.id,
                    event.event_type,
                    choice_index,
                    outcome[:500],
                    json.dumps(state_changes),
                )
            self._table_ok = True
        except Exception:
            logger.exception("events.insert_failed")
            self._table_ok = False

    # ── per turn ─────────────────────────────────
    async def check(
        self,
        end_user_id: str,
        character_id: str,
        *,
        rel_state: dict,
        emotion: str | None,
        emotion_intensity: float,
        message: str,
        character_name: str = "",
        now: datetime | None = None,
    ) -> TriggeredEvent | None:
        """Pick this turn's event (or None). A pending scene blocks new ones."""
        if not end_user_id:
            return None
        now = now or datetime.now(UTC)
        if await self.cache.get_json(self._pending_key(end_user_id, character_id)):
            return None
        history = await self.history(end_user_id, character_id)
        completed = list(rel_state.get("completed_events") or [])
        completed_all = sorted(set(completed) | {h["event_id"] for h in history})
        last_at = _parse(rel_state.get("last_interaction_at"))
        hours = (now - last_at).total_seconds() / 3600 if last_at else None
        ctx = EventContext(
            state=rel_state,
            completed=completed_all,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
            message=message,
            now=now.astimezone() if now.tzinfo else now,
            hours_since_last=hours,
        )
        random_used = await self.cache.get(self._random_day_key(end_user_id, character_id, now))
        hits = check_all_events(
            ctx,
            history,
            allow_romance=rel_state.get("app_mode") != "companion",
            allow_random=not random_used,
        )
        if not hits:
            return None
        ev = hits[0]
        trig = TriggeredEvent(event=ev, scene=ev.scene, character_name=character_name)
        if ev.event_type == "random":
            await self.cache.set(
                self._random_day_key(end_user_id, character_id, now), "1", ttl=86400
            )
        if ev.scene.choices:
            await self.cache.set_json(
                self._pending_key(end_user_id, character_id),
                {"event_id": ev.id, "scene_id": ev.scene.id, "at": now.isoformat()},
                ttl=_PENDING_TTL,
            )
        else:
            # No choice to make: it happened. Apply state changes + record now.
            await self._complete(
                end_user_id,
                character_id,
                ev,
                choice_index=None,
                outcome=ev.scene.dialogue,
                state_changes=ev.state_changes,
            )
        logger.info("events.triggered", event_id=ev.id, end_user_id=end_user_id)
        return trig

    async def choose(
        self, end_user_id: str, character_id: str, event_id: str, choice_index: int
    ) -> dict:
        """Resolve a pending scene choice. Returns {response, relationship, next_scene}."""
        ev = EVENTS_BY_ID.get(event_id)
        if not ev:
            raise KeyError(event_id)
        pending = await self.cache.get_json(self._pending_key(end_user_id, character_id)) or {}
        scene = ev.scene_by_id(pending.get("scene_id")) or ev.scene
        if not scene.choices or not (0 <= choice_index < len(scene.choices)):
            raise IndexError(choice_index)
        choice = scene.choices[choice_index]
        changes = {**ev.state_changes, **choice.state_changes}
        rel = await self._complete(
            end_user_id,
            character_id,
            ev,
            choice_index=choice_index,
            outcome=f"{choice.text} → {choice.response}",
            state_changes=changes,
        )
        await self.cache.delete(self._pending_key(end_user_id, character_id))
        nxt = ev.scene_by_id(choice.next_scene_id)
        return {
            "response": choice.response,
            "relationship": rel,
            "next_scene": {"id": nxt.id, "dialogue": nxt.dialogue, "outro": nxt.outro}
            if nxt
            else None,
        }

    async def _complete(
        self,
        end_user_id: str,
        character_id: str,
        ev: EventDef,
        *,
        choice_index: int | None,
        outcome: str,
        state_changes: dict,
    ) -> dict:
        result = await self.rel.record_event(end_user_id, character_id, ev.id, state_changes)
        await self._insert(
            end_user_id,
            character_id,
            ev,
            choice_index=choice_index,
            outcome=outcome,
            state_changes=state_changes,
        )
        await self.cache.set_json(
            self._last_key(end_user_id, character_id),
            {
                "event_id": ev.id,
                "name": ev.name,
                "outcome": outcome,
                "at": datetime.now(UTC).isoformat(),
            },
            ttl=_LAST_TTL,
        )
        return result.to_payload()

    async def last_outcome_context(self, end_user_id: str, character_id: str) -> str:
        """Prompt line about what just happened (consumed once)."""
        if not end_user_id:
            return ""
        key = self._last_key(end_user_id, character_id)
        last = await self.cache.get_json(key)
        if not last:
            return ""
        await self.cache.delete(key)
        return (
            f"刚刚发生了「{last['name']}」：{last['outcome']}。"
            "接下来的对话要记得这件事，让它自然地影响你的语气。"
        )

    async def near(
        self, end_user_id: str, character_id: str, rel_state: dict, emotion: str | None = None
    ) -> list[dict]:
        history = await self.history(end_user_id, character_id)
        ctx = EventContext(
            state=rel_state,
            completed=list(rel_state.get("completed_events") or []),
            emotion=emotion,
        )
        return near_trigger_events(ctx, history)
