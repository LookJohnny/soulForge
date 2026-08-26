"""Visual-novel event system: conditions, cooldown/priority, engine flow."""

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_core.services.events import (
    ALL_EVENTS,
    EVENTS_BY_ID,
    EventContext,
    EventEngine,
    check_all_events,
    check_condition,
    near_trigger_events,
)
from ai_core.services.events.engine import is_on_cooldown
from ai_core.services.relationship import STAGE_REQUIREMENTS, default_state

NOW = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)  # Wednesday morning


def _state(**over):
    s = default_state()
    s["first_interaction_at"] = (NOW - timedelta(days=40)).isoformat()
    s["last_interaction_at"] = NOW.isoformat()
    s["total_interactions"] = 50
    s.update(over)
    return s


def _ctx(state=None, **kw):
    return EventContext(
        state=state or _state(), now=NOW.astimezone(UTC), rng=random.Random(0), **kw
    )


# ── catalogue integrity ──────────────────────


def test_catalogue_ids_unique_and_stage_requirements_resolvable():
    ids = [e.id for e in ALL_EVENTS]
    assert len(ids) == len(set(ids)) == 28
    for req in STAGE_REQUIREMENTS.values():
        for ev_id in req.get("events", []):
            assert ev_id in EVENTS_BY_ID, ev_id
    for e in ALL_EVENTS:
        for c in e.conditions:
            for key in ("event_completed", "event_not_completed"):
                if c["type"] == key:
                    assert c["value"] in EVENTS_BY_ID
        for ch in e.scene.choices:
            if ch.next_scene_id:
                assert e.scene_by_id(ch.next_scene_id) is not None, (e.id, ch.next_scene_id)


def test_confession_branches_to_follow_up_scenes():
    ev = EVENTS_BY_ID["confession_event"]
    assert ev.scene.choices[0].next_scene_id == "confession_accepted"
    assert ev.scene_by_id("confession_accepted").dialogue


# ── conditions ───────────────────────────────


@pytest.mark.parametrize(
    "cond,state_over,expected",
    [
        ({"type": "min_affection", "value": 100}, {"affection": 100}, True),
        ({"type": "min_affection", "value": 100}, {"affection": 99}, False),
        ({"type": "max_energy", "value": 30}, {"energy": 30}, True),
        ({"type": "max_energy", "value": 30}, {"energy": 31}, False),
        ({"type": "relationship_stage", "value": "FRIEND"}, {"stage": "FAMILIAR"}, True),
        ({"type": "relationship_stage_min", "value": "FRIEND"}, {"stage": "DATING"}, True),
        ({"type": "relationship_stage_min", "value": "DATING"}, {"stage": "FRIEND"}, False),
        ({"type": "days_known", "value": 30}, {}, True),
        ({"type": "days_known", "value": 60}, {}, False),
        ({"type": "total_interactions", "value": 50}, {}, True),
        ({"type": "max_total_interactions", "value": 2}, {"total_interactions": 2}, True),
        ({"type": "max_total_interactions", "value": 2}, {}, False),
        ({"type": "consecutive_days", "value": 7}, {"streak_days": 7}, True),
    ],
)
def test_state_conditions(cond, state_over, expected):
    assert check_condition(cond, _ctx(_state(**state_over))) is expected


def test_context_conditions():
    ctx = _ctx(
        completed=["a"],
        emotion="happy",
        emotion_intensity=40,
        message="我们去看星星吧",
        hours_since_last=50,
    )
    assert check_condition({"type": "event_completed", "value": "a"}, ctx)
    assert not check_condition({"type": "event_not_completed", "value": "a"}, ctx)
    assert check_condition({"type": "time_of_day", "value": "morning"}, ctx)
    assert check_condition({"type": "day_of_week", "value": 3}, ctx)  # Wednesday (0=Sunday)
    assert check_condition({"type": "keyword_mentioned", "value": "星星"}, ctx)
    assert check_condition({"type": "mood_is", "value": "happy"}, ctx)
    assert check_condition({"type": "mood_is", "value": ["shy", "happy"]}, ctx)
    assert not check_condition({"type": "mood_is", "value": "sad"}, ctx)
    assert check_condition({"type": "mood_intensity_min", "value": 30}, ctx)
    assert check_condition({"type": "hours_since_last_interaction_min", "value": 48}, ctx)
    assert not check_condition({"type": "hours_since_last_interaction_max", "value": 48}, ctx)
    assert check_condition({"type": "random_chance", "value": 1.0}, ctx)
    assert not check_condition({"type": "random_chance", "value": 0.0}, ctx)
    assert not check_condition({"type": "bogus", "value": 1}, ctx)


def test_first_contact_counts_as_long_absence():
    ctx = _ctx(hours_since_last=None)
    assert check_condition({"type": "hours_since_last_interaction_min", "value": 72}, ctx)
    assert not check_condition({"type": "hours_since_last_interaction_max", "value": 72}, ctx)


# ── cooldown / priority ──────────────────────


def test_cooldown_rules():
    one_time = EVENTS_BY_ID["first_conversation"]
    repeat = EVENTS_BY_ID["random_thought"]  # cooldown 6 days
    assert is_on_cooldown(
        one_time, [{"event_id": "first_conversation", "completed_at": NOW.isoformat()}], NOW
    )
    assert not is_on_cooldown(one_time, [], NOW)
    recent = [{"event_id": "random_thought", "completed_at": (NOW - timedelta(days=2)).isoformat()}]
    assert is_on_cooldown(repeat, recent, NOW)
    old = [{"event_id": "random_thought", "completed_at": (NOW - timedelta(days=7)).isoformat()}]
    assert not is_on_cooldown(repeat, old, NOW)


def test_check_all_events_priority_and_filters():
    state = _state(affection=750, trust=90, intimacy=60, comfort=70, stage="DATING", streak_days=7)
    ctx = EventContext(state=state, completed=[], emotion="happy", now=NOW, rng=random.Random(0))
    hits = check_all_events(ctx, [])
    ids = [e.id for e in hits]
    assert ids[0] == "first_i_love_you"  # priority 98 beats streak_7_days (60)
    assert "streak_7_days" in ids and "first_conversation" not in ids  # not new anymore
    # companion mode drops romance
    no_romance = [e.id for e in check_all_events(ctx, [], allow_romance=False)]
    assert "first_i_love_you" not in no_romance and "streak_7_days" in no_romance
    # random budget spent → no random events
    no_random = check_all_events(ctx, [], allow_random=False)
    assert all(e.event_type != "random" for e in no_random)


def test_near_trigger_events():
    # shared_vulnerability: trust ≥65 ✓, intimacy ≥40 ✓, first_deep_conversation ✗ → 66%
    state = _state(affection=100, trust=70, intimacy=45, stage="FRIEND")
    ctx = EventContext(state=state, completed=[], now=NOW)
    near = near_trigger_events(ctx, [])
    hit = next(n for n in near if n["event_id"] == "shared_vulnerability")
    assert hit["progress"] == 66
    assert any("first_deep_conversation" in m for m in hit["missing"])
    assert all(n["event_id"] != "first_deep_conversation" for n in near)  # 100% → not "near"


# ── engine ───────────────────────────────────


class _Cache:
    def __init__(self):
        self.store = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, ttl=None):
        self.store[k] = v

    async def get_json(self, k):
        return self.store.get(k)

    async def set_json(self, k, v, ttl=None):
        self.store[k] = v

    async def delete(self, k):
        self.store.pop(k, None)


class _Rel:
    def __init__(self, state):
        self.state = state
        self.recorded = []

    async def record_event(self, end_user_id, character_id, event_id, state_changes=None):
        from ai_core.services.relationship import TurnResult, apply_deltas

        self.recorded.append((event_id, state_changes))
        self.state["completed_events"] = list(self.state.get("completed_events") or []) + [event_id]
        self.state = apply_deltas(self.state, state_changes or {})
        return TurnResult(state=self.state, deltas=state_changes or {})


def _engine(state, table_ok=True):
    pool = MagicMock()
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acq)
    rel = _Rel(state)
    eng = EventEngine(pool, _Cache(), rel)
    eng._table_ok = table_ok
    return eng, rel, conn


@pytest.mark.asyncio
async def test_engine_choice_flow_and_next_turn_context():
    state = _state(
        affection=550,
        trust=85,
        intimacy=45,
        stage="ROMANTIC_INTEREST",
        completed_events=["first_deep_conversation"],
    )
    eng, rel, conn = _engine(state)
    trig = await eng.check(
        "u",
        "c",
        rel_state=state,
        emotion="shy",
        emotion_intensity=30,
        message="今天想见你",
        character_name="小星",
        now=NOW,
    )
    assert trig is not None and trig.event.id == "confession_event"
    payload = trig.to_payload()
    assert payload["type"] == "event" and len(payload["scene"]["choices"]) == 2
    assert "小星" in payload["scene"]["intro"]
    assert "告白" not in trig.prompt_context() or "刚刚说了" in trig.prompt_context()
    # pending blocks further events
    assert (
        await eng.check(
            "u", "c", rel_state=state, emotion="shy", emotion_intensity=30, message="x", now=NOW
        )
        is None
    )
    # choose → state changes applied, recorded, next scene returned
    out = await eng.choose("u", "c", "confession_event", 0)
    assert out["next_scene"]["id"] == "confession_accepted"
    assert rel.recorded[0][0] == "confession_event" and rel.recorded[0][1]["affection"] == 100
    assert conn.execute.await_count == 1
    assert out["relationship"]["type"] == "relationship"
    # next turn learns what happened, exactly once
    ctxt = await eng.last_outcome_context("u", "c")
    assert "告白" in ctxt and "我也喜欢你" in ctxt
    assert await eng.last_outcome_context("u", "c") == ""


@pytest.mark.asyncio
async def test_engine_no_choice_event_completes_immediately_and_random_budget():
    state = _state(affection=250, trust=60, stage="FRIEND", total_interactions=1)
    eng, rel, _ = _engine(state)
    trig = await eng.check(
        "u", "c", rel_state=state, emotion="happy", emotion_intensity=20, message="嗨", now=NOW
    )
    assert trig.event.id == "first_conversation"  # priority 100, no choices
    assert rel.recorded and rel.recorded[0][0] == "first_conversation"
    assert eng.cache.store.get("event_pending:u:c") is None
    # a random event may fire at most once per day
    state2 = _state(
        affection=250,
        trust=60,
        stage="FRIEND",
        completed_events=[
            "first_conversation",
            "first_long_conversation",
            "one_week_anniversary",
            "one_month_anniversary",
        ],
    )
    eng2, _, _ = _engine(state2)
    eng2.cache.store[eng2._random_day_key("u", "c", NOW)] = "1"
    hist = [{"event_id": e, "completed_at": NOW.isoformat()} for e in state2["completed_events"]]
    eng2.history = AsyncMock(return_value=hist)
    # morning_greeting (random_chance 0.3) may or may not fire — but never a random-type one
    for _ in range(5):
        t = await eng2.check(
            "u",
            "c",
            rel_state=state2,
            emotion="curious",
            emotion_intensity=20,
            message="嗨",
            now=NOW,
        )
        assert t is None or t.event.event_type != "random"


@pytest.mark.asyncio
async def test_engine_companion_mode_skips_romance():
    state = _state(
        affection=900,
        trust=99,
        intimacy=90,
        comfort=90,
        stage="COMPANION",
        app_mode="companion",
        completed_events=["first_deep_conversation"],
    )
    eng, _, _ = _engine(state)
    eng.history = AsyncMock(
        return_value=[
            {"event_id": e, "completed_at": NOW.isoformat()}
            for e in (
                "first_conversation",
                "first_long_conversation",
                "one_week_anniversary",
                "one_month_anniversary",
            )
        ]
    )
    t = await eng.check(
        "u", "c", rel_state=state, emotion="happy", emotion_intensity=20, message="嗨", now=NOW
    )
    assert t is None or not t.event.romance


@pytest.mark.asyncio
async def test_engine_survives_missing_table():
    state = _state(total_interactions=1)
    eng, rel, conn = _engine(state, table_ok=None)
    conn.fetch = AsyncMock(side_effect=RuntimeError("relation relationship_events does not exist"))
    t = await eng.check(
        "u", "c", rel_state=state, emotion=None, emotion_intensity=0, message="嗨", now=NOW
    )
    assert t.event.id == "first_conversation" and eng._table_ok is False
    assert rel.recorded  # completed_events on the relationship still records it


@pytest.mark.asyncio
async def test_choose_validation():
    eng, _, _ = _engine(_state())
    with pytest.raises(KeyError):
        await eng.choose("u", "c", "nope", 0)
    with pytest.raises(IndexError):
        await eng.choose("u", "c", "confession_event", 9)


@pytest.mark.asyncio
async def test_near_with_aware_history_and_default_now():
    # Regression: /events/near mixed a naive default `now` with tz-aware rows → TypeError
    state = _state(affection=100, trust=70, intimacy=45, stage="FRIEND")
    eng, _, _ = _engine(state)
    eng.history = AsyncMock(
        return_value=[{"event_id": "random_thought", "completed_at": NOW.isoformat()}]
    )
    near = await eng.near("u", "c", state)
    assert any(n["event_id"] == "shared_vulnerability" for n in near)
    ctx = EventContext(state=state)  # default now must be tz-aware
    assert ctx.now.tzinfo is not None
