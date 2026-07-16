"""Phase-1 regressions: time model, deterministic interruption, LLM isolation."""

import time

import pytest

from engine.planner import (
    CompanionRuntime,
    Event,
    EventKind,
    ImpactLevel,
    MockBehaviorLLM,
    Persona,
    WorldState,
    expand_hour,
    generate_day_plan,
)
from engine.planner.clock import (
    GameClock,
    SimulationClock,
    WallClock,
    clock_label,
    day_index,
    day_minute,
)
from engine.planner.llm_interface import (
    BehaviorDecision,
    DecisionValidationError,
    SafeDecisionLLM,
    validate_decision,
)


def persona(agent_id="kai", archetype="steady_caretaker"):
    return Persona(agent_id, agent_id.title(), archetype, relationships={"user": 0.7})


def make_runtime(start_minute=19 * 60, personas=None):
    return CompanionRuntime(
        personas or [persona()],
        WorldState(sim_minute=start_minute),
        llm=MockBehaviorLLM(),
    )


# ------------------------------------------------------------------- clock
def test_clock_abstractions():
    sim = SimulationClock(100.0)
    sim.advance(50)
    assert sim.now_minutes() == 150.0
    with pytest.raises(ValueError):
        sim.advance(-1)

    assert day_minute(1500) == 60 and day_index(1500) == 1
    assert clock_label(1440 + 90) == "01:30"

    game = GameClock(
        source=lambda: 120.0, host_units_per_minute=60.0, offset_minutes=600
    )
    assert game.now_minutes() == 602.0

    wall = WallClock()
    assert 0 <= wall.now_minutes() < 24 * 60 + 1


# ------------------------------------------------- 48h continuous simulation
def test_48h_simulation_survives_midnights():
    runtime = make_runtime(start_minute=20 * 60)  # day 0, 20:00
    runtime.run(start_min=20 * 60, duration_min=48 * 60, step_min=15)

    # day plans regenerated for day 1 and day 2
    day_changes = [
        t
        for t in runtime.trace
        if t.kind == "plan_change"
        and t.detail.get("level") == "day"
        and "new_day" in t.detail
    ]
    assert {d.detail["new_day"] for d in day_changes} >= {1, 2}

    # post-midnight hours must NOT degrade to idle: day-1 noon should be cooking
    # for a steady_caretaker (12:00 next day = total minute 1440+720)
    world = runtime.world
    assert world.sim_minute > 2 * 1440 + 1140
    plan = runtime.day_plans["kai"]
    assert plan.day == day_index(world.sim_minute)
    assert plan.block_at(12 * 60).activity_key == "cooking"

    # hour plans across the run were never permanently idle after midnight
    hour_logs = [
        t.detail
        for t in runtime.trace
        if t.kind == "plan_change" and t.detail.get("level") == "hour"
    ]
    families_after_midnight = {tuple(d.get("activities", [])) for d in hour_logs}
    assert any("cooking" in fam for fam in families_after_midnight)


def test_critical_near_midnight_produces_valid_intervals():
    runtime = make_runtime(start_minute=23 * 60 + 50)
    runtime.push_event(
        Event(
            t_min=23 * 60 + 51,
            kind=EventKind.ROBOT_STATE,
            source="battery",
            text="检测到低电量警告",
            target_agent="kai",
        )
    )
    runtime.run(start_min=23 * 60 + 50, duration_min=5)
    for block in runtime.day_plans["kai"].blocks:
        assert block.start_min < block.end_min, f"reversed interval: {block}"
        assert 0 <= block.start_min < 24 * 60
        assert 0 < block.end_min <= 24 * 60


def test_hour_plan_respects_non_top_of_hour_block_boundary():
    """22:00-23:00 crosses the 22:30 chatting->rest boundary."""
    p = persona()
    world = WorldState(sim_minute=0)
    day = generate_day_plan(p, world)
    hour = expand_hour(p, day, 22, world)
    families = [(a.template_id, a.start_min, a.duration_min) for a in hour.activities]
    # first half hour comes from the chatting block, second from rest
    assert any(t == "chatting" and s < 22 * 60 + 30 for t, s, _ in families)
    assert any(t == "rest" and s >= 22 * 60 + 30 for t, s, _ in families)
    # activities tile the hour exactly
    assert sum(d for _, _, d in families) == 60
    boundary_starts = [s for _, s, _ in families]
    assert 22 * 60 + 30 in boundary_starts


# ------------------------------------------------ deterministic interruption
def test_non_interruptible_activity_defers_normal_events():
    """repair (interruptible=False) may not be paused by a MEDIUM preference."""
    p = persona(archetype="utility_robot")  # 17:00-19:00 repair for robots
    runtime = CompanionRuntime(
        [p], WorldState(sim_minute=17 * 60 + 5), llm=MockBehaviorLLM()
    )
    runtime.push_event(
        Event(
            t_min=17 * 60 + 6,
            kind=EventKind.USER_UTTERANCE,
            source="user",
            text="想吃清淡一点",
            target_agent="kai",
        )
    )
    runtime.run(start_min=17 * 60 + 5, duration_min=4)
    deferred = [
        t
        for t in runtime.trace
        if t.kind == "decision" and t.detail.get("scope") == "deferred"
    ]
    assert deferred, "MEDIUM event during non-interruptible repair must be deferred"
    # the params were NOT patched mid-repair
    repair = [
        a for a in runtime.hour_plans["kai"].activities if a.template_id == "repair"
    ]
    assert all("flavor" not in a.params for a in repair)
    # and the event is re-queued for the safe breakpoint, not lost
    assert any(e.payload.get("_deferred_from") for e in runtime.event_queue)


def test_critical_still_interrupts_but_via_safe_stop():
    p = persona(archetype="utility_robot")
    runtime = CompanionRuntime(
        [p], WorldState(sim_minute=17 * 60 + 5), llm=MockBehaviorLLM()
    )
    dispatched = []
    runtime.adapter = lambda agent_id, action: dispatched.append(action.name)
    runtime.push_event(
        Event(
            t_min=17 * 60 + 6,
            kind=EventKind.ROBOT_STATE,
            source="battery",
            text="检测到低电量警告",
            target_agent="kai",
        )
    )
    runtime.run(start_min=17 * 60 + 5, duration_min=3)
    assert "safe_stop" in dispatched
    assert (
        dispatched.index("hold_safe_breakpoint")
        < dispatched.index("safe_stop")
        < dispatched.index("abort_all_templates")
    )


def test_routine_status_signals_are_not_critical():
    runtime = make_runtime()
    for text, kind in [
        ("电量正常", EventKind.ROBOT_STATE),
        ("heartbeat", EventKind.SYSTEM),
    ]:
        runtime.push_event(
            Event(
                t_min=19 * 60 + 1,
                kind=kind,
                source="sys",
                text=text,
                target_agent="kai",
            )
        )
    runtime.run(start_min=19 * 60, duration_min=3)
    decisions = [t.detail for t in runtime.trace if t.kind == "decision"]
    assert decisions and all(d["impact"] == "LOW" for d in decisions)
    # plan untouched
    assert any(a.template_id == "cooking" for a in runtime.hour_plans["kai"].activities)


# ------------------------------------------------------------- LLM isolation
class SlowLLM:
    def __init__(self, delay_s):
        self.delay_s = delay_s

    def decide(self, *args, **kwargs):
        time.sleep(self.delay_s)
        raise AssertionError("should have been timed out")


class MalformedLLM:
    def decide(self, event, persona_, world, current_template, current_interruptible):
        return BehaviorDecision(
            selected_intent="x",
            emotional_read="",
            plan_delta="hour",
            impact=ImpactLevel.HIGH,
            template_to_call="warp_drive",
            dialogue=[{"agent": "kai", "text": ""}],  # empty text -> invalid
        )


def test_safe_llm_times_out_and_falls_back():
    safe = SafeDecisionLLM(SlowLLM(3.0), timeout_s=0.2)
    started = time.monotonic()
    decision = safe.decide(
        Event(t_min=0, kind=EventKind.USER_UTTERANCE, source="user", text="你好"),
        persona(),
        WorldState(),
        "cooking",
        True,
    )
    assert time.monotonic() - started < 1.5
    assert "fallback" in decision.reason
    assert decision.impact == ImpactLevel.LOW  # mock handled the greeting
    safe.shutdown()


def test_safe_llm_rejects_malformed_and_event_not_lost():
    safe = SafeDecisionLLM(MalformedLLM(), timeout_s=2.0)
    decision = safe.decide(
        Event(
            t_min=0, kind=EventKind.USER_UTTERANCE, source="user", text="我今天很难过"
        ),
        persona(),
        WorldState(),
        "cooking",
        True,
    )
    assert "fallback" in decision.reason
    assert decision.impact == ImpactLevel.HIGH  # mock still comforts properly
    safe.shutdown()


def test_validate_decision_rules():
    good = MockBehaviorLLM().decide(
        Event(t_min=0, kind=EventKind.USER_UTTERANCE, source="user", text="你好"),
        persona(),
        WorldState(),
        "cooking",
        True,
    )
    assert validate_decision(good, "cooking") is good

    bad = BehaviorDecision(
        selected_intent="x",
        emotional_read="",
        plan_delta="warp",
        impact=ImpactLevel.LOW,
        template_to_call="cooking",
    )
    with pytest.raises(DecisionValidationError):
        validate_decision(bad, "cooking")

    unknown_template = BehaviorDecision(
        selected_intent="x",
        emotional_read="",
        plan_delta="micro",
        impact=ImpactLevel.LOW,
        template_to_call="not_a_template",
    )
    validated = validate_decision(unknown_template, "cooking")
    assert validated.template_to_call == "cooking"  # degraded, not crashed
