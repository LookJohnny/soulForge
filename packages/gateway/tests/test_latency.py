"""Tests for the gateway voice-turn latency tracker."""

from gateway.latency import LatencyTracker, _percentile


def test_percentile_basics():
    assert _percentile([], 0.5) == 0.0
    values = [float(i) for i in range(1, 101)]
    assert _percentile(values, 0.50) == 50.5
    assert _percentile(values, 1.0) == 100.0


def test_record_and_snapshot():
    tracker = LatencyTracker()
    tracker.record_turn(
        "voice_turn",
        {"asr_finalize": 50, "first_chunk": 900, "first_word": 1100, "respond": 4000},
    )
    tracker.record_turn(
        "voice_turn",
        {"asr_finalize": 70, "first_chunk": 1100, "first_word": 1300, "respond": 5000},
    )
    snap = tracker.snapshot()
    assert snap["voice_turn"]["turns"] == 2
    fw = snap["voice_turn"]["stages_ms"]["first_word"]
    assert fw["avg"] == 1200.0
    assert fw["count"] == 2
    assert snap["voice_turn"]["last_turn"]["first_word"] == 1300.0


def test_non_numeric_and_none_values_dropped():
    tracker = LatencyTracker()
    tracker.record_turn("voice_turn", {"first_word": None, "respond": 1000, "note": "x"})
    snap = tracker.snapshot()
    stages = snap["voice_turn"]["stages_ms"]
    assert "first_word" not in stages
    assert "note" not in stages
    assert stages["respond"]["count"] == 1


def test_core_stage_merge_keys():
    tracker = LatencyTracker()
    tracker.record_turn(
        "voice_turn",
        {"first_word": 1200, "core_llm_first_token": 600, "core_total": 1500},
    )
    snap = tracker.snapshot()
    assert "core_llm_first_token" in snap["voice_turn"]["stages_ms"]


def test_rolling_window():
    tracker = LatencyTracker(max_turns=5)
    for i in range(12):
        tracker.record_turn("voice_turn", {"respond": float(i)})
    snap = tracker.snapshot()
    assert snap["voice_turn"]["turns"] == 5
    assert snap["voice_turn"]["last_turn"]["respond"] == 11.0


def test_unified_aliases_keep_missing_audio_distinct_from_measured_zero():
    tracker = LatencyTracker()
    assert tracker.snapshot() == {}  # No voice turn is not a zero-latency turn.
    tracker.record_turn("voice_turn", {"core_decision_ms": 120, "core_first_audio_ms": 0})
    tracker.record_turn("voice_turn", {"core_decision_ms": 180, "core_first_audio_ms": None})
    snapshot = tracker.snapshot()["voice_turn"]
    assert snapshot["stages_ms"]["decision_ms"]["count"] == 2
    assert snapshot["stages_ms"]["first_audio_ms"] == {
        "avg": 0.0,
        "p50": 0.0,
        "p95": 0.0,
        "p99": 0.0,
        "max": 0.0,
        "count": 1,
        "missing_count": 1,
    }
    assert "first_audio_ms" not in snapshot["last_turn"]
    assert snapshot["stages_ms"]["core_first_audio_ms"] == snapshot["stages_ms"]["first_audio_ms"]


def test_invalid_measurements_do_not_pollute_percentiles():
    tracker = LatencyTracker()
    for bad in (True, False, float("nan"), float("inf"), -1, "12", None):
        tracker.record_turn("voice_turn", {"core_first_audio_ms": bad})
    tracker.record_turn("voice_turn", {"core_first_audio_ms": 75})
    stage = tracker.snapshot()["voice_turn"]["stages_ms"]["first_audio_ms"]
    assert stage["count"] == 1 and stage["missing_count"] == 7
    assert stage["p95"] == 75
