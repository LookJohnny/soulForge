"""Phase-5 acceptance: one character, many bodies, shared memory & relationships."""

import pytest

from engine.planner import (
    CompanionRuntime,
    Event,
    EventKind,
    MockBehaviorLLM,
    Persona,
    WorldState,
)
from engine.planner.memory_store import InMemoryMemoryStore, MEMORY_LAYERS, MemoryStore


def persona():
    return Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.75})


def test_layers_and_validation():
    store = InMemoryMemoryStore()
    assert isinstance(store, MemoryStore)
    for layer in MEMORY_LAYERS:
        store.remember("kai", layer, "k", {"v": 1})
        assert store.recall("kai", layer) == {"k": {"v": 1}}
    with pytest.raises(ValueError):
        store.remember("kai", "third_memory_system", "k", 1)


def test_same_character_across_unity_and_robot_bodies_shares_memory():
    """Session 1 = Unity body; session 2 = robot body. Same agent_id, same store:
    relationship growth and long-term memory must survive the body switch."""
    store = InMemoryMemoryStore()

    # --- session 1: the character lives in a Unity body ---
    unity_session = CompanionRuntime(
        [persona()],
        WorldState(sim_minute=19 * 60),
        llm=MockBehaviorLLM(),
        memory_store=store,
    )
    unity_session.push_event(
        Event(
            t_min=19 * 60 + 1,
            kind=EventKind.USER_UTTERANCE,
            source="user",
            text="我今天很难过",
            target_agent="kai",
        )
    )
    unity_session.run(start_min=19 * 60, duration_min=3)
    grown = unity_session.personas["kai"].relationships["user"]
    assert grown > 0.75
    assert unity_session.memory["kai"].get("evening_mode") == "companion"

    # --- session 2: same character wakes up inside a robot ---
    robot_session = CompanionRuntime(
        [persona()],
        WorldState(sim_minute=20 * 60),
        llm=MockBehaviorLLM(),
        memory_store=store,
    )
    hydrated = robot_session.personas["kai"]
    assert hydrated.relationships["user"] == pytest.approx(grown), (
        "relationship state must follow the character, not the body"
    )
    assert robot_session.memory["kai"].get("evening_mode") == "companion", (
        "long-term memory must be readable from the new body"
    )
    assert store.recall("kai", "episodic").get("user_mood") == "tired"


def test_memory_is_agent_scoped_not_shared_between_characters():
    store = InMemoryMemoryStore()
    store.remember("kai", "episodic", "secret", "kai-only")
    store.set_relationship("kai", "user", 0.9)
    assert store.recall("luna", "episodic") == {}
    assert store.get_relationships("luna") == {}


def test_runtime_defaults_to_inmemory_store():
    runtime = CompanionRuntime(
        [persona()], WorldState(sim_minute=19 * 60), llm=MockBehaviorLLM()
    )
    assert isinstance(runtime.memory_store, InMemoryMemoryStore)
