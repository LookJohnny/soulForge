"""Refactor acceptance: character-config reusability + robustness hardening."""

import json

import pytest

from engine.planner import (
    CharacterConfigError, CompanionRuntime, Event, EventKind, MockBehaviorLLM,
    Persona, WorldState, generate_day_plan, load_archetypes, load_personas,
)
from engine.server.protocol import decode


# ------------------------------------------------------------ character config
def test_personas_load_from_single_source():
    personas = load_personas()
    ids = {p.agent_id for p in personas}
    assert {"luna", "kai", "pipo"} <= ids
    luna = next(p for p in personas if p.agent_id == "luna")
    assert luna.meta["voice"]["fish"]["reference_id"]
    assert luna.meta["embodiment"]["model"].endswith(".vrm")
    assert luna.meta["color"].startswith("#")


def test_new_character_needs_no_code_changes(tmp_path):
    """Adding a brand-new character with an unknown archetype must just work."""
    config = {
        "characters": [{
            "id": "nova", "name": "Nova", "archetype": "space_gardener",
            "traits": ["curious"], "energy": 0.9,
            "voice": {"edge": {"voice": "zh-CN-XiaoxiaoNeural"}},
            "embodiment": {"kind": "vrm", "model": "/x/nova.vrm"},
        }],
        "archetypes": {"default": {"focus": [["study", "自习"]], "evening": "chatting"}},
    }
    path = tmp_path / "chars.json"
    path.write_text(json.dumps(config, ensure_ascii=False), "utf-8")

    personas = load_personas(path)
    assert personas[0].name == "Nova"
    plan = generate_day_plan(personas[0], WorldState(), load_archetypes(path))
    assert plan.blocks[-1].end_min == 24 * 60          # full day, no crash
    assert plan.block_at(19 * 60 + 30).activity_key == "chatting"  # default fallback

    runtime = CompanionRuntime(personas, WorldState(sim_minute=19 * 60), llm=MockBehaviorLLM())
    runtime.push_event(Event(t_min=19 * 60 + 1, kind=EventKind.USER_UTTERANCE,
                             source="user", text="我今天很难过", target_agent="nova"))
    runtime.run(start_min=19 * 60, duration_min=3)
    assert "陪伴" in runtime.hour_plans["nova"].goal


def test_broken_config_fails_loudly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", "utf-8")
    with pytest.raises(CharacterConfigError):
        load_personas(bad)
    empty = tmp_path / "empty.json"
    empty.write_text('{"characters": []}', "utf-8")
    with pytest.raises(CharacterConfigError):
        load_personas(empty)


def test_comfort_line_comes_from_character_config():
    personas = load_personas()
    kai = next(p for p in personas if p.agent_id == "kai")
    decision = MockBehaviorLLM().decide(
        Event(t_min=0, kind=EventKind.USER_UTTERANCE, source="user", text="我好难过"),
        kai, WorldState(), "cooking", True)
    assert decision.dialogue[0]["text"] == kai.meta["comfort_line"]


# ------------------------------------------------------------------ hardening
def make_runtime(**kwargs):
    personas = [Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.7})]
    return CompanionRuntime(personas, WorldState(sim_minute=19 * 60),
                            llm=MockBehaviorLLM(), **kwargs)


def test_event_for_unknown_agent_is_dropped_not_crashing():
    runtime = make_runtime()
    runtime.push_event(Event(t_min=19 * 60, kind=EventKind.USER_UTTERANCE,
                             source="user", text="你好", target_agent="ghost"))
    runtime.run(start_min=19 * 60, duration_min=2)
    assert any(t.kind == "event_dropped" for t in runtime.trace)


def test_trace_is_bounded_ring_buffer():
    runtime = make_runtime(trace_limit=50)
    runtime.run(start_min=19 * 60, duration_min=200)     # would log 400+ entries
    assert len(runtime.trace) == 50
    assert runtime.trace_since(0)[-1].seq == runtime._trace_seq
    # cursor semantics survive eviction: nothing newer than the newest
    assert runtime.trace_since(runtime._trace_seq) == []


def test_empty_personas_rejected():
    with pytest.raises(ValueError):
        CompanionRuntime([], WorldState())


def test_medium_patch_does_not_alias_decision_params():
    runtime = make_runtime()
    runtime.push_event(Event(t_min=19 * 60 + 1, kind=EventKind.USER_UTTERANCE,
                             source="user", text="想吃清淡一点", target_agent="kai"))
    runtime.run(start_min=19 * 60, duration_min=3)
    activity = next(a for a in runtime.hour_plans["kai"].activities
                    if a.params.get("flavor") == "light")
    before = dict(activity.params)
    activity.params["flavor"] = "spicy"                 # renderer-side mutation
    # a second identical event must not see the mutated dict as its own default
    runtime.push_event(Event(t_min=19 * 60 + 4, kind=EventKind.USER_UTTERANCE,
                             source="user", text="想吃清淡一点", target_agent="kai"))
    runtime.run(start_min=19 * 60 + 4, duration_min=2)
    assert activity.params is not before


def test_wire_decode_rejects_garbage_without_crashing_types():
    with pytest.raises(ValueError):
        decode('{"type": "nonsense"}')
    with pytest.raises((ValueError, json.JSONDecodeError)):
        decode("not json at all")
    # extra unknown fields tolerated (forward compatibility)
    event = decode('{"type":"event","kind":"user_utterance","source":"u","v2_field":1}')
    assert event.kind == "user_utterance"
