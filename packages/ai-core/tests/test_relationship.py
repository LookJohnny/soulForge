"""Tests for the five-axis Relationship Evolution Engine."""

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_core.services.relationship import (
    AXES,
    COMPANION_STAGE,
    STAGE_BEHAVIORS,
    STAGE_MEMORY_DEPTH,
    STAGE_ORDER,
    STAGE_PROMPTS,
    STAGE_REQUIREMENTS,
    STAGE_TRIGGER_PROB,
    RelationshipEngine,
    _affinity_to_stage,
    _to_legacy_stage,
    apply_deltas,
    apply_time_decay,
    baseline_impact,
    compute_stage,
    default_state,
    describe_for_prompt,
    meets_requirements,
    merge_updates,
    near_stage,
    normalize_stage,
    relationship_payload,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _state(**over) -> dict:
    s = default_state()
    s["first_interaction_at"] = (NOW - timedelta(days=90)).isoformat()
    s["last_interaction_at"] = NOW.isoformat()
    s["total_interactions"] = 100
    s.update(over)
    s["affinity"] = s["affection"]
    return s


# ── tables ───────────────────────────────────


class TestStageTables:
    def test_every_stage_has_all_tables(self):
        for stage in STAGE_ORDER + [COMPANION_STAGE]:
            assert stage in STAGE_PROMPTS and len(STAGE_PROMPTS[stage]) > 5
            assert stage in STAGE_MEMORY_DEPTH
            assert stage in STAGE_TRIGGER_PROB
            assert stage in STAGE_BEHAVIORS

    def test_memory_depth_and_trigger_monotonic(self):
        depths = [STAGE_MEMORY_DEPTH[s] for s in STAGE_ORDER]
        assert depths == sorted(depths)
        probs = [STAGE_TRIGGER_PROB[s] for s in STAGE_ORDER]
        assert probs == sorted(probs)

    def test_legacy_aliases(self):
        assert normalize_stage("FAMILIAR") == "FRIEND"
        assert normalize_stage("BESTFRIEND") == "CLOSE_FRIEND"
        assert normalize_stage("bestfriend") == "CLOSE_FRIEND"
        assert normalize_stage(None) == "STRANGER"
        assert _to_legacy_stage("SOULMATE") == "BESTFRIEND"
        assert _to_legacy_stage("CLOSE_FRIEND") == "BESTFRIEND"
        assert _to_legacy_stage("FRIEND") == "FRIEND"

    def test_affinity_to_stage_compat(self):
        assert _affinity_to_stage(0) == "STRANGER"
        assert _affinity_to_stage(150) == "ACQUAINTANCE"
        assert _affinity_to_stage(900) == "CLOSE_FRIEND"

    def test_dating_requires_confession_event_not_scene_id(self):
        # aikeya bug: required 'confession_accepted' (a scene id) → unreachable
        assert STAGE_REQUIREMENTS["DATING"]["events"] == ["confession_event"]


# ── stage computation ────────────────────────


class TestComputeStage:
    def test_fresh_state_is_stranger(self):
        assert compute_stage(default_state()) == "STRANGER"

    def test_conjunctive_requirements(self):
        # affection alone is not enough for FRIEND: trust 50 + 3 days + 10 interactions
        s = _state(affection=200, trust=10)
        assert compute_stage(s) == "STRANGER"  # trust 10 < 20 blocks even ACQUAINTANCE
        s = _state(affection=200, trust=55)
        assert compute_stage(s) == "FRIEND"
        s = _state(affection=200, trust=55, total_interactions=5)
        assert compute_stage(s) == "ACQUAINTANCE"

    def test_days_known_gate(self):
        s = _state(affection=400, trust=80, comfort=60)
        s["first_interaction_at"] = (NOW - timedelta(days=2)).isoformat()
        assert compute_stage(s, []) == "ACQUAINTANCE"  # FRIEND needs 3 days

    def test_romance_requires_events(self):
        s = _state(affection=700, trust=90, intimacy=60, comfort=70)
        assert compute_stage(s, []) == "CLOSE_FRIEND"
        assert (
            compute_stage(s, ["first_deep_conversation", "shared_vulnerability"])
            == "ROMANTIC_INTEREST"
        )
        assert (
            compute_stage(
                s, ["first_deep_conversation", "shared_vulnerability", "confession_event"]
            )
            == "DATING"
        )

    def test_stage_can_regress(self):
        s = _state(affection=100, trust=60)  # was FRIEND, affection fell below 150
        s["stage"] = "FRIEND"
        assert compute_stage(s) == "ACQUAINTANCE"

    def test_companion_mode_pins_stage(self):
        s = _state(affection=999, trust=100, app_mode="companion")
        assert compute_stage(s) == COMPANION_STAGE

    def test_missing_requirements_are_readable(self):
        s = _state(affection=100, trust=30, total_interactions=4)
        missing = meets_requirements(s, "FRIEND")
        assert any("好感" in m for m in missing) and any("信任" in m for m in missing)
        assert any("对话次数" in m for m in missing)
        assert meets_requirements(s, "ACQUAINTANCE") == []

    def test_near_stage(self):
        s = _state(affection=100, trust=30, stage="ACQUAINTANCE")
        ns = near_stage(s)
        assert ns["stage"] == "FRIEND" and ns["missing"]
        assert near_stage(_state(stage="SOULMATE")) is None
        assert near_stage(_state(stage=COMPANION_STAGE, app_mode="companion")) is None


# ── deltas ───────────────────────────────────


class TestBaselineImpact:
    def test_positive_deep_emotional_question(self):
        rng = random.Random(1)
        d = baseline_impact(
            _state(affection=100),
            user_mood="excited",
            user_text="我今天终于把项目做完了，你能告诉我接下来该怎么庆祝吗？" * 3,
            rng=rng,
        )
        assert d["energy"] == -4  # base -2, deep -2
        assert d["affection"] > 0 and d["intimacy"] >= 2 and d["trust"] >= 1
        assert d["respect"] == 1  # question
        assert -5 <= d["affection"] <= 10

    def test_negative_mood_is_closeness_not_rejection(self):
        d = baseline_impact(
            _state(affection=100), user_mood="sad", user_text="我好难过", rng=random.Random(2)
        )
        assert d["affection"] >= 0
        assert d["intimacy"] >= 2

    def test_honeymoon_phase_amplifies(self):
        rng_a, rng_b = random.Random(3), random.Random(3)
        low = baseline_impact(
            _state(affection=50), user_mood="happy", user_text="哈哈哈今天真开心呀" * 3, rng=rng_a
        )
        high = baseline_impact(
            _state(affection=900), user_mood="happy", user_text="哈哈哈今天真开心呀" * 3, rng=rng_b
        )
        assert low["affection"] > high["affection"]

    def test_legacy_bonuses(self):
        base = baseline_impact(_state(affection=500), user_text="嗯", rng=random.Random(0))
        bonus = baseline_impact(
            _state(affection=500),
            user_text="嗯",
            is_first_today=True,
            streak_days=3,
            memory_types=["PREFERENCE"],
            touch_bonus=8,
            rng=random.Random(0),
        )
        assert bonus["affection"] > base["affection"]
        assert bonus["affection"] <= 10

    def test_clamps(self):
        d = baseline_impact(
            _state(),
            user_mood="excited",
            user_text="?" * 300,
            touch_bonus=50,
            is_first_today=True,
            streak_days=9,
        )
        assert d["affection"] <= 10 and d["trust"] <= 5 and d["intimacy"] <= 5


class TestMergeUpdates:
    def test_none_keeps_baseline(self):
        b = {"energy": -2, "affection": 3, "trust": 1, "intimacy": 0, "comfort": 0, "respect": 0}
        assert merge_updates(b, None) == b

    def test_llm_clamped_relative_to_baseline(self):
        b = {"energy": -2, "affection": 3, "trust": 1, "intimacy": 0, "comfort": 0, "respect": 0}
        m = merge_updates(
            b, {"affection": 40, "trust": -20, "intimacy": 9, "comfort": -9, "respect": 2}
        )
        assert m["affection"] == 6  # 2× baseline
        assert m["trust"] == -3  # floor max(2, 3)
        assert m["intimacy"] == 5 and m["comfort"] == -3 and m["respect"] == 2

    def test_llm_floor_when_baseline_zero(self):
        b = {"energy": -2, "affection": 0, "trust": 0, "intimacy": 0, "comfort": 0, "respect": 0}
        m = merge_updates(b, {"affection_delta": -30, "trust_delta": 2})
        assert m["affection"] == -5 and m["trust"] == 2

    def test_llm_cannot_touch_energy(self):
        b = {"energy": -2, "affection": 1, "trust": 0, "intimacy": 0, "comfort": 0, "respect": 0}
        assert merge_updates(b, {"energy": 50})["energy"] == -2

    def test_garbage_ignored(self):
        b = {"energy": -2, "affection": 1, "trust": 0, "intimacy": 0, "comfort": 0, "respect": 0}
        assert merge_updates(b, {"affection": "lots"})["affection"] == 1


class TestApplyDeltas:
    def test_clamps_to_axis_limits(self):
        s = apply_deltas(
            _state(affection=998, trust=99, energy=1), {"affection": 10, "trust": 5, "energy": -5}
        )
        assert s["affection"] == 1000 and s["trust"] == 100 and s["energy"] == 0
        assert s["affinity"] == 1000


# ── decay ────────────────────────────────────


class TestTimeDecay:
    def test_no_last_interaction_noop(self):
        r = apply_time_decay(default_state(), NOW)
        assert not r.applied

    def test_energy_refills_partially_then_fully(self):
        s = _state(energy=40)
        s["last_interaction_at"] = (NOW - timedelta(hours=3)).isoformat()
        r = apply_time_decay(s, NOW)
        assert r.applied and r.deltas["energy"] == 30
        s = _state(energy=40)
        s["last_interaction_at"] = (NOW - timedelta(hours=7)).isoformat()
        assert apply_time_decay(s, NOW).state["energy"] == 100

    def test_affection_decays_after_two_days_capped(self):
        s = _state(affection=800)
        s["last_interaction_at"] = (NOW - timedelta(days=5)).isoformat()
        r = apply_time_decay(s, NOW)
        assert r.deltas["affection"] == -min(int(800 * 0.03), 50) == -24
        assert "trust" not in r.deltas
        assert r.mood_cause == "想你了"
        s = _state(affection=1000)
        s["last_interaction_at"] = (NOW - timedelta(days=30)).isoformat()
        assert apply_time_decay(s, NOW).deltas["affection"] == -50

    def test_trust_decays_after_a_week(self):
        s = _state(trust=50)
        s["last_interaction_at"] = (NOW - timedelta(days=15)).isoformat()
        assert apply_time_decay(s, NOW).deltas["trust"] == -4

    def test_idempotent_via_clock(self):
        s = _state(affection=800, energy=50)
        s["last_interaction_at"] = (NOW - timedelta(days=5)).isoformat()
        first = apply_time_decay(s, NOW)
        assert first.applied
        again = apply_time_decay(first.state, NOW + timedelta(minutes=10))
        assert not again.applied
        # a day later: energy already full, affection charged only for the new day
        later = apply_time_decay(first.state, NOW + timedelta(days=1))
        assert later.applied and "energy" not in later.deltas
        assert later.deltas.get("affection", 0) < 0

    def test_companion_mode_only_energy(self):
        s = _state(affection=800, trust=50, energy=10, app_mode="companion")
        s["last_interaction_at"] = (NOW - timedelta(days=20)).isoformat()
        r = apply_time_decay(s, NOW)
        assert set(r.deltas) == {"energy"}


# ── prompt / payload ─────────────────────────


class TestDescribe:
    def test_prompt_block(self):
        txt = describe_for_prompt(
            _state(
                affection=312,
                trust=54,
                intimacy=12,
                comfort=40,
                respect=30,
                energy=88,
                stage="FRIEND",
                streak_days=3,
            )
        )
        assert "朋友" in txt and "312/1000" in txt and "连续 3 天" in txt and "身体亲昵 15%" in txt
        assert "陪伴模式" not in txt

    def test_companion_note(self):
        assert "陪伴模式" in describe_for_prompt(
            _state(app_mode="companion", stage=COMPANION_STAGE)
        )

    def test_payload_shape(self):
        p = relationship_payload(
            _state(affection=312, stage="FAMILIAR"), deltas={"affection": 4, "trust": 0}
        )
        assert p["type"] == "relationship" and p["stage"] == "FRIEND"
        assert set(p["axes"]) == set(AXES)
        assert p["deltas"] == {"affection": 4}
        assert p["near_stage"]["stage"] == "CLOSE_FRIEND"
        assert p["behavior"]["initiation"] == 0.4


# ── engine ───────────────────────────────────


class _Cache:
    def __init__(self):
        self.store = {}

    async def get_json(self, k):
        return self.store.get(k)

    async def set_json(self, k, v, ttl=None):
        self.store[k] = v

    async def delete(self, k):
        self.store.pop(k, None)


def _engine(axes_schema=True):
    pool = MagicMock()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acq)
    eng = RelationshipEngine(pool=pool, cache=_Cache())
    eng._axes_schema = axes_schema
    return eng, conn


class TestRelationshipEngine:
    @pytest.mark.asyncio
    async def test_no_user_returns_default(self):
        eng, _ = _engine()
        s = await eng.get_state("", "c")
        assert s["stage"] == "STRANGER" and s["affection"] == 0 and s["energy"] == 100

    @pytest.mark.asyncio
    async def test_apply_turn_moves_axes_and_persists(self):
        eng, conn = _engine()
        r = await eng.apply_turn(
            "u", "c", user_mood="happy", user_text="今天和你聊天真开心，你觉得呢？"
        )
        assert r.state["affection"] > 0 and r.state["total_interactions"] == 1
        assert r.state["streak_days"] == 1 and r.state["turn_count_today"] == 1
        assert r.state["first_interaction_at"] and r.state["last_interaction_at"]
        assert conn.execute.await_count == 1
        sql = conn.execute.await_args.args[0]
        assert "trust" in sql and "completed_events" in sql
        # cached
        cached = await eng.cache.get_json("rel:u:c")
        assert cached["affection"] == r.state["affection"]

    @pytest.mark.asyncio
    async def test_apply_turn_companion_mode_locks_axes(self):
        eng, _ = _engine()
        await eng.cache.set_json(
            "rel:u:c", _state(affection=100, trust=20, app_mode="companion", stage=COMPANION_STAGE)
        )
        r = await eng.apply_turn("u", "c", user_mood="happy", user_text="哈哈哈开心" * 5)
        assert r.state["affection"] == 100 and r.state["trust"] == 20
        assert r.deltas["energy"] < 0
        assert r.state["stage"] == COMPANION_STAGE

    @pytest.mark.asyncio
    async def test_stage_change_reported(self):
        eng, _ = _engine()
        s = _state(affection=48, trust=25, total_interactions=5, stage="STRANGER")
        await eng.cache.set_json("rel:u:c", s)
        r = await eng.apply_turn("u", "c", user_mood="happy", user_text="今天真开心！" * 3)
        assert r.stage_changed and r.from_stage == "STRANGER" and r.state["stage"] == "ACQUAINTANCE"

    @pytest.mark.asyncio
    async def test_llm_suggestion_clamped(self):
        eng, _ = _engine()
        await eng.cache.set_json("rel:u:c", _state(affection=500))
        r = await eng.apply_turn(
            "u", "c", user_text="嗯", llm_suggestion={"affection": 100, "trust": 50}
        )
        assert r.deltas["affection"] <= 10 and r.deltas["trust"] <= 5

    @pytest.mark.asyncio
    async def test_set_app_mode_round_trip(self):
        eng, _ = _engine()
        await eng.cache.set_json("rel:u:c", _state(affection=200, trust=60, stage="FRIEND"))
        s = await eng.set_app_mode("u", "c", "companion")
        assert s["stage"] == COMPANION_STAGE and s["saved_stage"] == "FRIEND"
        s = await eng.set_app_mode("u", "c", "dating_sim")
        assert s["stage"] == "FRIEND" and s["saved_stage"] is None
        with pytest.raises(ValueError):
            await eng.set_app_mode("u", "c", "nope")

    @pytest.mark.asyncio
    async def test_record_event_unlocks_stage(self):
        eng, _ = _engine()
        await eng.cache.set_json(
            "rel:u:c",
            _state(affection=700, trust=90, intimacy=60, comfort=70, stage="CLOSE_FRIEND"),
        )
        r = await eng.record_event("u", "c", "first_deep_conversation", {"intimacy": 5})
        assert r.state["intimacy"] == 65 and not r.stage_changed
        r = await eng.record_event("u", "c", "shared_vulnerability")
        assert r.stage_changed and r.state["stage"] == "ROMANTIC_INTEREST"
        assert r.state["completed_events"] == ["first_deep_conversation", "shared_vulnerability"]

    @pytest.mark.asyncio
    async def test_legacy_schema_fallback(self):
        eng, conn = _engine(axes_schema=False)
        r = await eng.apply_turn("u", "c", user_mood="happy", user_text="你好呀")
        sql = conn.execute.await_args.args[0]
        assert "trust" not in sql
        assert r.state["affection"] > 0

    @pytest.mark.asyncio
    async def test_lazy_decay_on_read(self):
        eng, conn = _engine()
        s = _state(affection=800, energy=20)
        s["last_interaction_at"] = (NOW - timedelta(days=5)).isoformat()
        s["last_interaction_date"] = (NOW - timedelta(days=5)).date().isoformat()
        await eng.cache.set_json("rel:u:c", s)
        got = await eng.get_state("u", "c")
        assert got["affection"] < 800 and got["energy"] == 100
        assert got.get("_decay_mood_cause") == "想你了"
        assert conn.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_award_points_compat(self):
        eng, _ = _engine()
        s = await eng.award_points("u", "c", memory_types=["PREFERENCE"], touch_bonus=3)
        assert s["affection"] > 0 and s["stage"] == "STRANGER"

    @pytest.mark.asyncio
    async def test_row_to_state_legacy_stage_names(self):
        eng, conn = _engine()
        row = {
            "affinity": 900,
            "stage": "BESTFRIEND",
            "streak_days": 2,
            "last_interaction_date": None,
            "turn_count_today": 0,
            "trust": 90,
            "intimacy": 60,
            "comfort": 75,
            "respect": 60,
            "energy": 80,
            "app_mode": "dating_sim",
            "saved_stage": None,
            "total_interactions": 40,
            "first_interaction_at": NOW - timedelta(days=30),
            "last_interaction_at": NOW,
            "decay_clocks": '{"at": "2026-08-26T11:00:00+00:00"}',
            "completed_events": "[]",
        }
        conn.fetchrow = AsyncMock(return_value=row)
        s = await eng._load("u", "c")
        assert s["stage"] == "CLOSE_FRIEND" and s["affection"] == 900 and s["decay_clocks"]["at"]
