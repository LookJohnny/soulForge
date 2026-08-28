"""Agent ↔ agent conversation: floor control, turn routing, aftermath, auto start."""

from engine.planner import (
    CompanionRuntime,
    Event,
    EventKind,
    MockBehaviorLLM,
    Persona,
    SocialPolicy,
    WorldState,
)


def personas():
    return [
        Persona(
            "luna",
            "Luna",
            "creative_care",
            traits=["warm"],
            daily_goals=["完成一幅画"],
            relationships={"user": 0.8, "kai": 0.7},
            energy=0.7,
        ),
        Persona(
            "kai",
            "Kai",
            "steady_caretaker",
            traits=["calm"],
            daily_goals=["做三餐"],
            relationships={"user": 0.75, "luna": 0.7},
            energy=0.6,
        ),
        Persona(
            "pipo",
            "Pipo",
            "utility_robot",
            traits=["precise"],
            daily_goals=["植物巡检"],
            relationships={"user": 0.7, "luna": 0.3, "kai": 0.3},
            energy=0.9,
        ),
    ]


def make_runtime(start=15 * 60, **kw):
    return CompanionRuntime(
        personas(), WorldState(sim_minute=start), llm=MockBehaviorLLM(), **kw
    )


def lines(rt):
    return [t for t in rt.trace if t.kind == "conversation_line"]


def test_two_agents_alternate_until_goodbye():
    rt = make_runtime()
    conv = rt.start_conversation("luna", "kai", topic="今晚吃什么")
    rt.run(15 * 60, 10)
    assert conv.ended and conv.end_reason == "closed"
    speakers = [ln.agent_id for ln in conv.lines]
    assert speakers[0] == "luna" and all(a != b for a, b in zip(speakers, speakers[1:]))
    assert "今晚吃什么" in conv.lines[0].text and "回头聊" in conv.lines[-1].text
    assert conv.turns == conv.max_turns  # closes on the last allowed turn
    kinds = [t.kind for t in rt.trace]
    assert kinds.index("conversation_start") < kinds.index("conversation_end")


def test_speaking_floor_rejects_out_of_turn_events():
    rt = make_runtime()
    conv = rt.start_conversation("luna", "kai")
    rt.tick(15 * 60)  # luna opens, kai's reply is queued for +0.5
    assert conv.next_speaker == "kai"
    # a forged "reply" from luna while kai holds the floor must be dropped
    rt.push_event(
        Event(
            t_min=15 * 60,
            kind=EventKind.AGENT_UTTERANCE,
            source="kai",
            text="x",
            payload={"conversation": {"id": conv.id}},
            target_agent="luna",
        )
    )
    rt.tick(15 * 60 + 0.25)
    dropped = [t for t in rt.trace if t.kind == "event_dropped"]
    assert dropped and dropped[-1].detail["reason"] == "not this agent's turn"
    assert len(lines(rt)) == 1


def test_speak_lines_gaze_at_partner_not_user():
    rt = make_runtime()
    rt.start_conversation("kai", "luna")
    rt.run(15 * 60, 3)
    spoken = [t for t in rt.trace if t.kind == "dialogue" and t.agent_id == "kai"]
    assert spoken and spoken[0].detail["gaze"] == "luna"


def test_aftermath_moves_relationship_and_writes_memory_both_ways():
    rt = make_runtime()
    before = rt.personas["luna"].relationships["kai"]
    rt.start_conversation("luna", "kai", topic="画画")
    rt.run(15 * 60, 10)
    assert rt.personas["luna"].relationships["kai"] > before
    assert rt.personas["kai"].relationships["luna"] > before
    assert (
        rt.memory_store.get_relationships("kai")["luna"]
        == rt.personas["kai"].relationships["luna"]
    )
    assert (
        "Kai" in rt.memory["luna"]["talked_with_kai"]
        and "画画" in rt.memory["luna"]["talked_with_kai"]
    )
    assert "Luna" in rt.memory["kai"]["talked_with_luna"]


def test_one_conversation_per_agent_and_cooldown():
    rt = make_runtime()
    rt.start_conversation("luna", "kai")
    try:
        rt.start_conversation("pipo", "luna")
        raise AssertionError("luna is busy")
    except ValueError:
        pass
    rt.run(15 * 60, 10)
    assert rt.conversations.active_for("luna") is None


def test_silence_ends_conversation():
    class Mute(MockBehaviorLLM):
        def _decide_conversation(self, event, persona, current_template, meta):
            d = super()._decide_conversation(event, persona, current_template, meta)
            if meta.get("role") == "reply":
                d.dialogue = []
            return d

    rt = CompanionRuntime(personas(), WorldState(sim_minute=15 * 60), llm=Mute())
    conv = rt.start_conversation("luna", "kai")
    rt.run(15 * 60, 5)
    assert conv.ended and conv.end_reason == "silence" and conv.turns == 1


def test_auto_start_pairs_closest_free_agents():
    rt = make_runtime(
        social_policy=SocialPolicy(auto_start=True, check_every_min=5, cooldown_min=30)
    )
    rt.run(15 * 60, 12)
    convs = rt.conversations.history()
    assert convs, "household should start talking on its own"
    assert set(convs[0].participants) == {
        "luna",
        "kai",
    }  # pipo's 0.3 is below min_relationship
    assert convs[0].ended


def test_auto_start_off_by_default_and_user_events_untouched():
    rt = make_runtime()
    rt.push_event(
        Event(
            t_min=15 * 60 + 1,
            kind=EventKind.USER_UTTERANCE,
            source="user",
            text="你好呀",
            target_agent="kai",
        )
    )
    rt.run(15 * 60, 5)
    assert not rt.conversations.history()
    assert any(t.kind == "dialogue" and t.detail["gaze"] == "user" for t in rt.trace)


def test_release_hands_floor_over_as_soon_as_line_is_spoken():
    rt = make_runtime(
        social_policy=SocialPolicy(turn_gap_min=30.0)
    )  # long fallback, like the server
    conv = rt.start_conversation("luna", "kai")
    rt.tick(15 * 60)  # luna opens; kai's reply is parked 30 min out
    assert conv.pending is not None and conv.pending.t_min == 15 * 60 + 30
    rt.tick(15 * 60 + 1)
    assert conv.turns == 1  # nobody answered yet
    assert rt.conversations.release("luna", 15 * 60 + 1.5)  # body says: line finished
    rt.tick(15 * 60 + 2)
    assert conv.turns == 2 and conv.lines[1].agent_id == "kai"
    assert not rt.conversations.release(
        "luna", 15 * 60 + 2
    )  # nothing pending for luna now


def test_routed_llm_sends_conversation_events_to_the_conversation_lane():
    from engine.planner import RoutedBehaviorLLM

    class Tagged(MockBehaviorLLM):
        def __init__(self, tag):
            super().__init__()
            self.tag = tag
            self.calls = 0

        def decide(self, *a, **k):
            self.calls += 1
            return super().decide(*a, **k)

    user_lane, conv_lane = Tagged("user"), Tagged("conv")
    rt = CompanionRuntime(
        personas(),
        WorldState(sim_minute=15 * 60),
        llm=RoutedBehaviorLLM(user_lane, conv_lane),
    )
    rt.push_event(
        Event(
            t_min=15 * 60,
            kind=EventKind.USER_UTTERANCE,
            source="user",
            text="你好",
            target_agent="luna",
        )
    )
    rt.start_conversation("luna", "kai", topic="x", max_turns=2)
    rt.run(15 * 60, 4)
    assert user_lane.calls == 1 and conv_lane.calls == 2


def test_build_llm_routes_when_conversation_model_differs(monkeypatch):
    from engine.planner import RoutedBehaviorLLM, build_llm

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("CONVERSATION_LLM_MODEL", raising=False)
    assert not isinstance(build_llm(), RoutedBehaviorLLM)
    monkeypatch.setenv("CONVERSATION_LLM_MODEL", "deepseek-reasoner")
    llm = build_llm()
    assert (
        isinstance(llm, RoutedBehaviorLLM)
        and llm.conversation.model == "deepseek-reasoner"
    )
    assert llm.default.model == "deepseek-chat"
