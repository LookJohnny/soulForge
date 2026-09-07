"""Normal turn cancellation must not teach the companion that it cannot speak."""

from engine.planner import MockBehaviorLLM, Persona
from engine.planner.memory_store import InMemoryMemoryStore
from engine.planner.runtime import CompanionRuntime


def make_runtime(store=None):
    return CompanionRuntime(
        [Persona("joi", "Joi", "creative_care")],
        llm=MockBehaviorLLM(),
        memory_store=store,
    )


def test_repeated_barge_in_is_preserved_without_capability_failure_reflection():
    runtime = make_runtime()
    for minute in range(5):
        runtime.record_action_outcome(
            "joi", "speak_line", "interrupted", "user barge-in", minute
        )

    observation = {"status": "interrupted", "detail": "user barge-in", "count": 5}
    assert runtime.memory["joi"]["action_interrupted_speak_line"] == observation
    assert (
        runtime.memory_store.recall("joi", "episodic")["action_interrupted_speak_line"]
        == observation
    )
    assert "action_failed_speak_line" not in runtime.memory["joi"]
    assert runtime.reflect("joi", 1440) == []
    assert not runtime.personas["joi"].meta.get("reflections")
    assert len(runtime.trace) == 5
    assert all(entry.detail["status"] == "interrupted" for entry in runtime.trace)


def test_only_genuine_failures_cross_the_reflection_threshold_amid_many_interruptions():
    runtime = make_runtime()
    runtime.record_action_outcome("joi", "speak_line", "failed", "synthesis failed", 1)
    for minute in range(2, 8):
        runtime.record_action_outcome(
            "joi", "speak_line", "interrupted", "user barge-in", minute
        )

    assert runtime.memory["joi"]["action_failed_speak_line"]["count"] == 1
    assert runtime.reflect("joi", 100) == []
    runtime.record_action_outcome(
        "joi", "speak_line", "failed", "synthesis failed", 101
    )
    insights = runtime.reflect("joi", 1440)
    assert len(insights) == 1
    assert "speak_line" in insights[0].insight and "2次" in insights[0].insight
    assert insights[0].evidence == ["action_failed_speak_line"]
    assert runtime.memory["joi"]["action_interrupted_speak_line"]["count"] == 6
    assert runtime.memory_store.recall("joi", "episodic")[
        "action_failed_speak_line"
    ] == {
        "status": "failed",
        "detail": "synthesis failed",
        "count": 2,
    }


def test_unverified_browser_playback_is_neither_success_nor_inability():
    runtime = make_runtime()
    detail = "sender_transport_only; browser playback unverified"
    for minute in range(3):
        runtime.record_action_outcome(
            "joi", "speak_line", "interrupted", detail, minute
        )

    assert runtime.memory["joi"]["action_interrupted_speak_line"]["detail"] == detail
    assert runtime.reflect("joi", 1440) == []
    assert all(entry.detail["status"] != "done" for entry in runtime.trace)


def test_new_interruption_counter_survives_reload_without_rewriting_legacy_memories():
    store = InMemoryMemoryStore()
    # Old builds mixed failures and interruptions. Their true split is unknown;
    # keep the historical record and previously stored reflection unchanged.
    legacy = {"status": "interrupted", "detail": "old ambiguous outcome", "count": 7}
    store.remember("joi", "episodic", "action_failed_speak_line", legacy.copy())
    store.remember("joi", "semantic", "reflection_d0_0", "existing insight")
    first = make_runtime(store)
    first.record_action_outcome("joi", "speak_line", "interrupted", "user barge-in", 1)
    reloaded = make_runtime(store)
    reloaded.record_action_outcome(
        "joi", "speak_line", "interrupted", "user barge-in", 2
    )

    assert reloaded.memory["joi"]["action_interrupted_speak_line"]["count"] == 2
    assert reloaded.memory["joi"]["action_failed_speak_line"] == legacy
    assert store.recall("joi", "episodic")["action_failed_speak_line"] == legacy
    assert store.recall("joi", "semantic")["reflection_d0_0"] == "existing insight"
