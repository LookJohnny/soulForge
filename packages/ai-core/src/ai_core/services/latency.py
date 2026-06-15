"""Stage-level latency tracking for the voice pipeline.

Complements middleware/metrics.py (whole-request HTTP timing) with
per-stage timings inside a turn: ASR, context prep, LLM first token,
TTS, time-to-first-audio. Pure in-memory, no external dependencies.

Usage:
    sw = Stopwatch()
    ...asr...
    sw.mark("asr")            # delta since previous mark
    ...llm first token...
    sw.stamp("llm_first_token")  # absolute time since turn start
    latency_tracker.record_turn("chat", {**sw.stages, "total": sw.since_start_ms()})
"""

import time
from collections import deque

_MAX_TURNS = 500  # rolling window per route


class Stopwatch:
    """Collects named stage timings (ms) within a single pipeline turn."""

    def __init__(self):
        self._t0 = time.monotonic()
        self._last = self._t0
        self.stages: dict[str, float] = {}

    def mark(self, stage: str) -> float:
        """Record elapsed ms since the previous mark (or start) as `stage`."""
        now = time.monotonic()
        ms = (now - self._last) * 1000
        self.stages[stage] = self.stages.get(stage, 0.0) + ms
        self._last = now
        return ms

    def stamp(self, stage: str) -> float:
        """Record absolute ms since turn start as `stage` (first occurrence wins)."""
        ms = (time.monotonic() - self._t0) * 1000
        self.stages.setdefault(stage, ms)
        return self.stages[stage]

    def add(self, stage: str, ms: float) -> None:
        """Accumulate externally-measured ms into `stage` (e.g. per-sentence TTS)."""
        self.stages[stage] = self.stages.get(stage, 0.0) + ms

    def since_start_ms(self) -> float:
        return (time.monotonic() - self._t0) * 1000


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[f]
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


class LatencyTracker:
    """Rolling window of per-turn stage timings, grouped by route."""

    def __init__(self, max_turns: int = _MAX_TURNS):
        self._max_turns = max_turns
        self._turns: dict[str, deque] = {}

    def record_turn(self, route: str, stages: dict[str, float | None]) -> None:
        turns = self._turns.setdefault(route, deque(maxlen=self._max_turns))
        turns.append({k: round(float(v), 1) for k, v in stages.items() if v is not None})

    def snapshot(self) -> dict:
        out = {}
        for route, turns in self._turns.items():
            values_by_stage: dict[str, list[float]] = {}
            for turn in turns:
                for stage, ms in turn.items():
                    values_by_stage.setdefault(stage, []).append(ms)

            stages_ms = {}
            for stage, values in values_by_stage.items():
                sorted_v = sorted(values)
                stages_ms[stage] = {
                    "avg": round(sum(sorted_v) / len(sorted_v), 1),
                    "p50": round(_percentile(sorted_v, 0.50), 1),
                    "p95": round(_percentile(sorted_v, 0.95), 1),
                    "p99": round(_percentile(sorted_v, 0.99), 1),
                    "max": round(sorted_v[-1], 1),
                    "count": len(sorted_v),
                }

            out[route] = {
                "turns": len(turns),
                "stages_ms": stages_ms,
                "last_turn": dict(turns[-1]) if turns else {},
            }
        return out

    def reset(self) -> None:
        self._turns.clear()


latency_tracker = LatencyTracker()
