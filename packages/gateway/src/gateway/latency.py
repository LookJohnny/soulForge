"""Voice-turn latency tracking at the device boundary.

Measures what the user actually feels: time from end-of-speech (VAD
endpoint) to the first Opus frame sent to the device ("first word").
Stage breakdowns from ai-core (asr/context/llm_first_token/tts/first_audio)
are merged in with a `core_` prefix. Pure in-memory, exposed via
`GET /metrics/latency`.
"""

from collections import deque

_MAX_TURNS = 500  # rolling window per route


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

    def record_turn(self, route: str, stages: dict) -> None:
        turns = self._turns.setdefault(route, deque(maxlen=self._max_turns))
        turns.append(
            {
                k: round(float(v), 1)
                for k, v in stages.items()
                if isinstance(v, (int, float)) and v is not None
            }
        )

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
