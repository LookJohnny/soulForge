"""A busy body may defer motion, but a user turn is thought and spoken once."""

from dataclasses import replace

from soulforge_harness.runtime.llm_interface import BehaviorDecision
from soulforge_harness.runtime.memory_store import InMemoryMemoryStore
from soulforge_harness.runtime.models import (
    Event,
    EventKind,
    ImpactLevel,
    Persona,
    WorldState,
)
from soulforge_harness.runtime.runtime import CompanionRuntime
from soulforge_harness.runtime import runtime as runtime_module


class CountingStore(InMemoryMemoryStore):
    def __init__(self):
        super().__init__()
        self.writes = []

    def remember(self, agent_id, memory_type, key, value):
        self.writes.append((agent_id, memory_type, key))
        return super().remember(agent_id, memory_type, key, value)


class Cognition:
    def __init__(self):
        self.calls = 0

    def decide(self, event, persona, world, current_template, current_interruptible):
        self.calls += 1
        return BehaviorDecision(
            selected_intent="respond",
            emotional_read="happy",
            plan_delta="insert",
            impact=ImpactLevel.MEDIUM,
            template_to_call="chatting",
            template_params={"flavor": "mild"},
            dialogue=[{"agent": persona.agent_id, "text": "我记住了，忙完向你挥手。"}],
            body_actions=["wave"],
            memory_update={"preference": "mild"},
            cognitive_state={"pad": {"p": 0.7, "a": 0.2, "d": 0.1}},
            provider_status={"provider": "fake", "status": "ok"},
        )


def busy_runtime():
    provider, store, actions = Cognition(), CountingStore(), []
    runtime = CompanionRuntime(
        [Persona("kai", "Kai", "utility_robot")],
        WorldState(sim_minute=17 * 60 + 5),
        llm=provider,
        memory_store=store,
        adapter=lambda agent, action: actions.append(action),
    )
    runtime.tick(17 * 60 + 5, consume_events=False)
    actions.clear()
    runtime.world.body_actions["kai"] = ["wave"]
    return runtime, provider, store, actions


def user_event(**payload):
    return Event(
        17 * 60 + 6,
        EventKind.USER_UTTERANCE,
        "user",
        "我喜欢清淡，挥挥手",
        {"event_id": "one-turn", "reply_body_id": "voice-one", **payload},
        "kai",
    )


def test_busy_turn_speaks_immediately_then_reuses_decision_without_state_or_speech_replay():
    runtime, provider, store, actions = busy_runtime()
    event = user_event()
    runtime.handle_event_now(event, event.t_min)
    assert provider.calls == 1
    assert [action.name for action in actions] == ["speak_line"]
    assert actions[0].gaze_target is None
    assert actions[0].correlation_id == "one-turn"
    assert actions[0].params["reply_body_id"] == "voice-one"
    assert actions[0].params["cognitive_state"]["pad"]["p"] == 0.7
    activity = runtime.hour_plans["kai"].activity_at(event.t_min)
    assert "flavor" not in activity.params
    queued = next(e for e in runtime.event_queue if e.payload.get("_deferred_from"))
    assert len(runtime._deferred_decisions) == 1
    writes_after_thought = list(store.writes)
    history_after_thought = list(runtime.recent_dialogue["kai"])
    actions.clear()
    # Model a safe action boundary: the old activity has finished, and the
    # current plan allows interruption. No real clock or provider is involved.
    runtime.hour_plans["kai"].activities = [
        replace(
            activity,
            start_min=queued.t_min,
            duration_min=10,
            interruptible=True,
        )
    ]
    runtime.handle_event_now(queued, queued.t_min)
    assert provider.calls == 1
    assert "wave" in [a.name for a in actions]
    assert not any(a.dialogue for a in actions)
    assert store.writes == writes_after_thought
    assert list(runtime.recent_dialogue["kai"]) == history_after_thought
    assert not runtime._deferred_decisions
    # Duplicate delivery of the same scheduled object cannot repeat work.
    count = len(actions)
    runtime.handle_event_now(queued, queued.t_min)
    assert provider.calls == 1 and len(actions) == count


def test_external_deferred_payload_does_not_bypass_busy_activity():
    runtime, provider, _, actions = busy_runtime()
    event = user_event(_deferred_from=1, deferred_decision={"body_actions": ["wave"]})
    runtime.handle_event_now(event, event.t_min)
    assert provider.calls == 1
    assert [a.name for a in actions] == ["speak_line"]
    assert runtime._deferred_decisions


def test_deferred_cache_is_bounded_and_eviction_never_reruns_cognition(monkeypatch):
    monkeypatch.setattr(runtime_module, "_MAX_DEFERRED_DECISIONS", 2)
    runtime, provider, _, _ = busy_runtime()
    for _ in range(3):
        event = user_event()
        runtime.handle_event_now(event, event.t_min)
    assert provider.calls == 3 and len(runtime._deferred_decisions) == 2
    evicted = next(e for e in runtime.event_queue if e.payload.get("_deferred_from"))
    runtime.handle_event_now(evicted, evicted.t_min)
    assert provider.calls == 3
    assert runtime.trace[-1].detail["reason"] == "deferred decision expired"


def test_cached_motion_is_checked_against_current_body_capabilities():
    runtime, provider, _, actions = busy_runtime()
    event = user_event()
    runtime.handle_event_now(event, event.t_min)
    queued = next(e for e in runtime.event_queue if e.payload.get("_deferred_from"))
    runtime.hour_plans["kai"].activities = []
    runtime.world.body_actions["kai"] = []  # body disconnected while busy
    actions.clear()
    runtime.handle_event_now(queued, queued.t_min)
    assert provider.calls == 1
    assert "wave" not in [a.name for a in actions]
    assert not any(a.dialogue for a in actions)


def test_changed_busy_plan_defers_cached_motion_without_rethinking_or_speaking():
    runtime, provider, store, actions = busy_runtime()
    event = user_event()
    runtime.handle_event_now(event, event.t_min)
    queued = next(e for e in runtime.event_queue if e.payload.get("_deferred_from"))
    activity = runtime.hour_plans["kai"].activity_at(event.t_min)
    runtime.hour_plans["kai"].activities = [
        replace(
            activity,
            start_min=queued.t_min,
            duration_min=10,
            interruptible=False,
        )
    ]
    writes = list(store.writes)
    actions.clear()
    runtime.handle_event_now(queued, queued.t_min)
    assert provider.calls == 1 and not actions
    assert store.writes == writes and len(runtime._deferred_decisions) == 1
