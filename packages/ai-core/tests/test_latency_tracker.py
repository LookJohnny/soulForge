"""Tests for the stage-level latency tracker and Stopwatch."""

import time

from ai_core.services.latency import LatencyTracker, Stopwatch, _percentile


class TestStopwatch:
    def test_mark_records_delta_since_previous_mark(self):
        sw = Stopwatch()
        time.sleep(0.01)
        ms = sw.mark("asr")
        assert ms >= 10
        assert sw.stages["asr"] == ms

        time.sleep(0.01)
        llm_ms = sw.mark("llm")
        # llm delta should not include the asr time
        assert llm_ms < ms + 15

    def test_mark_accumulates_repeated_stage(self):
        sw = Stopwatch()
        sw.mark("tts")
        first = sw.stages["tts"]
        time.sleep(0.005)
        sw.mark("tts")
        assert sw.stages["tts"] > first

    def test_stamp_is_absolute_and_first_wins(self):
        sw = Stopwatch()
        time.sleep(0.01)
        first = sw.stamp("first_audio")
        time.sleep(0.01)
        second = sw.stamp("first_audio")
        assert first == second  # setdefault: first occurrence wins
        assert sw.stages["first_audio"] == first

    def test_add_accumulates_external_ms(self):
        sw = Stopwatch()
        sw.add("tts", 100.0)
        sw.add("tts", 50.0)
        assert sw.stages["tts"] == 150.0

    def test_since_start_grows(self):
        sw = Stopwatch()
        a = sw.since_start_ms()
        time.sleep(0.005)
        assert sw.since_start_ms() > a


class TestPercentile:
    def test_empty(self):
        assert _percentile([], 0.5) == 0.0

    def test_single_value(self):
        assert _percentile([42.0], 0.99) == 42.0

    def test_median_and_extremes(self):
        values = [float(i) for i in range(1, 101)]
        assert _percentile(values, 0.50) == 50.5
        assert _percentile(values, 0.0) == 1.0
        assert _percentile(values, 1.0) == 100.0


class TestLatencyTracker:
    def test_record_and_snapshot(self):
        tracker = LatencyTracker()
        tracker.record_turn("chat", {"asr": 120, "llm": 800, "total": 1000})
        tracker.record_turn("chat", {"asr": 80, "llm": 600, "total": 700})

        snap = tracker.snapshot()
        assert snap["chat"]["turns"] == 2
        asr = snap["chat"]["stages_ms"]["asr"]
        assert asr["count"] == 2
        assert asr["avg"] == 100.0
        assert asr["max"] == 120.0
        assert snap["chat"]["last_turn"] == {"asr": 80.0, "llm": 600.0, "total": 700.0}

    def test_none_stages_are_dropped(self):
        tracker = LatencyTracker()
        tracker.record_turn("chat", {"asr": None, "total": 500})
        snap = tracker.snapshot()
        assert "asr" not in snap["chat"]["stages_ms"]
        assert snap["chat"]["stages_ms"]["total"]["count"] == 1

    def test_routes_are_independent(self):
        tracker = LatencyTracker()
        tracker.record_turn("chat", {"total": 100})
        tracker.record_turn("chat_stream", {"total": 200})
        snap = tracker.snapshot()
        assert snap["chat"]["stages_ms"]["total"]["avg"] == 100.0
        assert snap["chat_stream"]["stages_ms"]["total"]["avg"] == 200.0

    def test_rolling_window_caps_turns(self):
        tracker = LatencyTracker(max_turns=10)
        for i in range(25):
            tracker.record_turn("chat", {"total": float(i)})
        snap = tracker.snapshot()
        assert snap["chat"]["turns"] == 10
        # Only the latest 10 turns (15..24) survive
        assert snap["chat"]["stages_ms"]["total"]["avg"] == 19.5
        assert snap["chat"]["last_turn"]["total"] == 24.0

    def test_missing_stage_in_some_turns(self):
        tracker = LatencyTracker()
        tracker.record_turn("chat", {"asr": 100, "total": 500})
        tracker.record_turn("chat", {"total": 300})  # text input — no ASR
        snap = tracker.snapshot()
        assert snap["chat"]["stages_ms"]["asr"]["count"] == 1
        assert snap["chat"]["stages_ms"]["total"]["count"] == 2

    def test_reset(self):
        tracker = LatencyTracker()
        tracker.record_turn("chat", {"total": 100})
        tracker.reset()
        assert tracker.snapshot() == {}
