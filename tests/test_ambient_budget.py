"""Ambient decision budget: on a local model, arrival notices must not crowd out a user's turn."""

import pytest

from engine.planner import CompanionRuntime, MockBehaviorLLM, Persona, WorldState
from soulforge_harness.runtime import runtime as runtime_module
from soulforge_harness.runtime.models import Event, EventKind


def personas():
    return [
        Persona(
            "luna", "Luna", "creative_care", relationships={"user": 0.8, "kai": 0.75}
        ),
        Persona(
            "kai", "Kai", "steady_caretaker", relationships={"user": 0.75, "luna": 0.75}
        ),
        Persona("pipo", "Pipo", "playful", relationships={"user": 0.7}),
    ]


class CountingLLM(MockBehaviorLLM):
    def __init__(self):
        super().__init__()
        self.kinds = []

    def decide(self, event, *args, **kwargs):
        self.kinds.append(event.kind)
        return super().decide(event, *args, **kwargs)


def arrival(to, minute=900.0):
    return Event(
        t_min=minute,
        kind=EventKind.AGENT_STATE,
        source="luna",
        text="Luna来了客厅沙发",
        target_agent=to,
    )


def test_default_is_unlimited_so_hosted_models_keep_every_reaction():
    llm = CountingLLM()
    rt = CompanionRuntime(personas(), WorldState(sim_minute=900), llm=llm)
    rt.tick(900)
    llm.kinds.clear()
    for to in ("kai", "pipo", "kai"):
        rt.handle_event_now(arrival(to), 900)
    assert llm.kinds.count(EventKind.AGENT_STATE) == 3


def test_budget_is_per_agent_and_never_limits_user_or_conversation_turns(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    llm = CountingLLM()
    rt = CompanionRuntime(personas(), WorldState(sim_minute=900), llm=llm, ambient_min_interval_s=60)
    rt.tick(900)
    llm.kinds.clear()
    rt.handle_event_now(arrival("kai"), 900)  # kai notices: decided
    rt.handle_event_now(arrival("kai"), 900)  # kai again inside his window: dropped
    rt.handle_event_now(arrival("pipo"), 900)  # pipo has her own budget: decided
    user = Event(t_min=900, kind=EventKind.USER_UTTERANCE, source="user", text="你好", target_agent="kai")
    rt.handle_event_now(user, 900)  # a user's turn is never budgeted
    rt.handle_event_now(user, 900)
    # a conversation opens with an AGENT_STATE event: it must never be budgeted away,
    # or the conversation would wait forever for an opener that never speaks
    conv = rt.start_conversation("kai", "luna", 900)
    rt.handle_event_now(rt.event_queue.pop(), 900)
    clock[0] += 61
    rt.handle_event_now(arrival("kai"), 901)  # kai's window passed: decided again
    assert llm.kinds == [
        EventKind.AGENT_STATE,
        EventKind.AGENT_STATE,
        EventKind.USER_UTTERANCE,
        EventKind.USER_UTTERANCE,
        EventKind.AGENT_STATE,
        EventKind.AGENT_STATE,
    ]
    dropped = [t for t in rt.trace if t.kind == "event_dropped" and t.detail.get("reason") == "ambient budget"]
    assert [t.agent_id for t in dropped] == ["kai"]
    assert conv is not None and not conv.ended


def test_event_classes():
    from soulforge_harness.runtime.runtime import event_class

    assert event_class(arrival("kai")) == "droppable"
    assert event_class(Event(t_min=0, kind=EventKind.USER_UTTERANCE, source="user", text="x")) == "user"
    sensed = Event(t_min=0, kind=EventKind.PERSON_DETECTED, source="cam", text="", payload={"reply_body_id": "b"})
    assert event_class(sensed) == "user"  # a body is waiting on it
    proactive = Event(t_min=0, kind=EventKind.USER_PRESENCE, source="user", text="", payload={"proactive": "loneliness"})
    assert event_class(proactive) == "droppable"
    opener = Event(t_min=0, kind=EventKind.AGENT_STATE, source="luna", text="", payload={"conversation": {"id": "c"}})
    assert event_class(opener) == "ambient"


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_budget_must_be_a_finite_non_negative_number(bad):
    with pytest.raises(ValueError):
        CompanionRuntime(
            personas(),
            WorldState(sim_minute=900),
            llm=MockBehaviorLLM(),
            ambient_min_interval_s=bad,
        )


def test_failed_optional_musings_are_quiet_but_user_turns_still_get_a_reply():
    from soulforge_harness.runtime.llm_interface import SafeDecisionLLM

    class Down:
        provider_name = "down"
        model = "m"

        def decide(self, *a, **k):
            raise ConnectionError("provider down")

    safe = SafeDecisionLLM(Down(), timeout_s=2)
    persona, world = personas()[1], WorldState(sim_minute=900)
    try:
        quiet = safe.decide(arrival("kai"), persona, world, "idle", True)
        assert quiet.dialogue == [] and quiet.provider_status["status"] == "degraded"
        user = Event(t_min=900, kind=EventKind.USER_UTTERANCE, source="user", text="你好", target_agent="kai")
        reply = safe.decide(user, persona, world, "idle", True)
        assert reply.dialogue  # someone is waiting: the deterministic fallback answers
    finally:
        safe.shutdown()
