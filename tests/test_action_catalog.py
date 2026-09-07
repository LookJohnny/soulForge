"""Game-interaction loop: world snapshot -> finite action catalog -> outcome memory.

The decision model sees engine state as data and a negotiated action catalog,
may only request actions a connected body actually offered (fail-closed), and
terminal receipts flow back into episodic memory so reflection can learn from
repeated failures.
"""

import asyncio

import pytest

from engine.planner import MockBehaviorLLM, Persona
from engine.planner.llm_interface import (
    BehaviorDecision,
    DecisionValidationError,
    validate_decision,
)
from engine.planner.models import Event, EventKind, ImpactLevel, WorldState
from engine.planner.reflection import reflect_day
from engine.planner.replanner import Replanner
from engine.planner.runtime import CompanionRuntime
from engine.server import (
    BodyHello,
    EmbodimentManifest,
    SoulForgeRuntimeServer,
    decode,
    encode,
)


def make_personas():
    return [
        Persona("luna", "Luna", "creative_care", relationships={"user": 0.8}),
        Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.75}),
    ]


def _decision(**overrides):
    base = dict(
        selected_intent="perform_for_user",
        emotional_read="playful",
        plan_delta="micro",
        impact=ImpactLevel.LOW,
        template_to_call="chatting",
        dialogue=[{"agent": "kai", "text": "看好啦！", "emotion": "playful"}],
        body_actions=["wave"],
    )
    base.update(overrides)
    return BehaviorDecision(**base)


# ---------------------------------------------------------------- world context
def test_world_context_snapshot_is_structured_and_bounded():
    world = WorldState(sim_minute=20 * 60 + 47, user_mood_hint="tired")
    world.space.agent_place["kai"] = "kitchen"
    world.space.agent_place["luna"] = "kitchen"
    world.sensors.update({f"sensor_{i}": float(i) for i in range(30)})

    context = world.context_for("kai")

    assert context["clock"] == "20:47"
    assert context["place"] == "kitchen"
    assert context["place_label"] == "厨房"
    assert "stove" in context["props_here"]
    assert context["others_here"] == ["luna"]
    assert context["user_mood_hint"] == "tired"
    assert len(context["sensors"]) <= 12  # prompt never grows with world size


# ---------------------------------------------------------------- catalog gates
def test_selectable_actions_offer_gestures_but_never_plumbing():
    manifest = EmbodimentManifest(
        body_id="web-1",
        backend="web",
        supported_steps=["wave", "jump", "speak_line", "pause_template"],
    )
    actions = manifest.selectable_actions()
    assert "wave" in actions and "jump" in actions
    assert "speak_line" not in actions  # dialogue is not a choosable gesture
    assert "pause_template" not in actions  # planner plumbing stays internal
    assert "safe_stop" not in actions


def test_validate_decision_gates_body_actions_against_catalog():
    decision = _decision(body_actions=["wave", "self_destruct", "jump", "clap"])
    validate_decision(decision, "chatting", available_actions=["wave", "jump", "clap"])
    assert decision.body_actions == ["wave", "jump"]  # filtered + capped at 2

    # no catalog at all -> nothing executes (fail-closed)
    decision = _decision(body_actions=["wave"])
    validate_decision(decision, "chatting", available_actions=None)
    assert decision.body_actions == []

    with pytest.raises(DecisionValidationError):
        validate_decision(_decision(body_actions="wave"), "chatting")


def test_replanner_performs_requested_actions_on_low_beats_only():
    event = Event(t_min=0, kind=EventKind.USER_UTTERANCE, source="user", text="跳个舞")
    persona = make_personas()[1]
    low = Replanner().apply(
        _decision(body_actions=["wave"]),
        event,
        persona,
        day_plan=None,
        hour_plan=None,
        minute=0,
    )
    names = [a.name for a in low.micro_actions]
    assert "wave" in names
    wave = next(a for a in low.micro_actions if a.name == "wave")
    assert wave.correlation_id is not None  # rides the same beat as the dialogue
    # gesture/move happens first, the line lands while it plays out
    assert (
        names.index("wave") < names.index("speak_line") < names.index("resume_activity")
    )


def test_runtime_catalog_gate_blocks_unoffered_actions():
    dispatched: list = []
    runtime = CompanionRuntime(
        make_personas(),
        llm=MockBehaviorLLM(),
        adapter=lambda agent_id, action: dispatched.append((agent_id, action.name)),
    )
    minute = 19 * 60.0
    runtime.tick(minute)  # build plans
    for plan in runtime.hour_plans.values():  # deterministic: never defer the event
        for activity in plan.activities:
            activity.interruptible = True
    event = Event(
        t_min=minute,
        kind=EventKind.USER_UTTERANCE,
        source="user",
        text="挥挥手",
        target_agent="kai",
    )

    # no body offered "wave": the request is dropped at the choke point
    runtime.handle_event_now(event, minute)
    assert ("kai", "wave") not in dispatched

    # a body offering "wave" makes the same decision executable
    runtime.world.body_actions = {"kai": ["wave"]}
    runtime.handle_event_now(event, minute)
    assert ("kai", "wave") in dispatched


def test_explicit_gesture_request_survives_a_prose_only_decision():
    """A model that answers in prose must not eat an explicit 挥挥手 request."""

    class ProseOnlyLLM:
        def decide(
            self, event, persona, world, current_template, current_interruptible
        ):
            return _decision(
                body_actions=[], impact=ImpactLevel.LOW, plan_delta="micro"
            )

    dispatched: list = []
    runtime = CompanionRuntime(
        make_personas(),
        llm=ProseOnlyLLM(),
        adapter=lambda agent_id, action: dispatched.append((agent_id, action.name)),
    )
    minute = 19 * 60.0
    runtime.tick(minute)
    for plan in runtime.hour_plans.values():
        for activity in plan.activities:
            activity.interruptible = True
    runtime.world.body_actions = {"kai": ["wave"]}
    runtime.handle_event_now(
        Event(
            t_min=minute,
            kind=EventKind.USER_UTTERANCE,
            source="user",
            text="挥挥手",
            target_agent="kai",
        ),
        minute,
    )
    assert ("kai", "wave") in dispatched  # keyword fallback, still catalog-gated


def test_proactive_presence_triggers_a_joi_moment():
    """A present but silent user gets approached by the closest companion."""
    dispatched: list = []
    runtime = CompanionRuntime(
        make_personas(),
        llm=MockBehaviorLLM(),
        adapter=lambda agent_id, action: dispatched.append((agent_id, action.name)),
    )
    runtime.proactive_after_min = 5.0
    runtime.world.body_actions = {"luna": ["approach_user"], "kai": ["approach_user"]}
    minute = 10 * 60.0
    runtime.tick(minute)
    for plan in runtime.hour_plans.values():
        for activity in plan.activities:
            activity.interruptible = True

    runtime.tick(minute + 6)  # silence threshold crossed -> proactive event fires
    approached = [(a, n) for a, n in dispatched if n == "approach_user"]
    assert approached, "silent user must be approached"
    # luna has the closer bond with the user, so she is the one who comes over
    assert approached[0][0] == "luna"

    # a real user event resets the silence clock — no immediate re-trigger
    runtime.last_user_event_min = minute + 6
    before = len(approached)
    runtime.tick(minute + 8)
    assert len([1 for a, n in dispatched if n == "approach_user"]) == before


# ---------------------------------------------------------------- outcome loop
def test_action_outcomes_feed_memory_and_reflection():
    runtime = CompanionRuntime(make_personas(), llm=MockBehaviorLLM())
    minute = 10 * 60.0
    runtime.record_action_outcome("kai", "water_plant", "done", "", minute)
    assert (
        "action_failed_water_plant" not in runtime.memory["kai"]
    )  # successes stay in trace

    runtime.record_action_outcome("kai", "water_plant", "failed", "joint stall", minute)
    runtime.record_action_outcome("kai", "water_plant", "failed", "joint stall", minute)
    record = runtime.memory["kai"]["action_failed_water_plant"]
    assert record["count"] == 2

    insights = reflect_day(runtime.personas["kai"], runtime.memory["kai"], {})
    assert any("water_plant" in r.insight for r in insights)


# ---------------------------------------------------------------- server wiring
@pytest.mark.asyncio
async def test_server_publishes_and_withdraws_action_catalog():
    server = SoulForgeRuntimeServer(
        make_personas(),
        start_minute=19 * 60,
        time_scale=1.0,
        tick_hz=8.0,
        llm=MockBehaviorLLM(),
    )
    serve_task = asyncio.create_task(server.serve(port=0))
    await asyncio.wait_for(server.ready.wait(), timeout=5)

    import websockets

    try:
        socket = await websockets.connect(f"ws://127.0.0.1:{server.bound_port}/body")
        manifest = EmbodimentManifest(
            body_id="web-1",
            backend="web",
            supported_steps=["wave", "jump", "speak_line"],
        )
        await socket.send(
            encode(
                BodyHello(
                    body_id="web-1",
                    backend="web",
                    agent_ids=["kai"],
                    manifest=manifest.to_dict(),
                )
            )
        )
        decode(await socket.recv())  # welcome

        offered = server.runtime.world.body_actions.get("kai", [])
        assert "wave" in offered and "jump" in offered
        assert "speak_line" not in offered

        await socket.close()
        for _ in range(50):  # teardown withdraws the catalog
            if not server.runtime.world.body_actions.get("kai"):
                break
            await asyncio.sleep(0.05)
        assert not server.runtime.world.body_actions.get("kai")
    finally:
        server.stop()
        await asyncio.wait_for(serve_task, timeout=5)
