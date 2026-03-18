"""Metrics middleware — tracks request count, latency, and errors in-memory.

Exposes a `GET /metrics` endpoint returning JSON with:
- requests_total by path
- request_duration_seconds (avg, p50, p99) by path
- errors_total by path and status code
- uptime_seconds

No external dependencies required (pure in-memory counters).
"""

import time
from collections import defaultdict

from fastapi import APIRouter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# ─── In-memory stores ───────────────────────────────

_start_time: float = time.time()
_request_counts: dict[str, int] = defaultdict(int)
_request_durations: dict[str, list[float]] = defaultdict(list)
_error_counts: dict[str, int] = defaultdict(int)

# Cap duration history to prevent unbounded memory growth
_MAX_DURATION_SAMPLES = 10_000


def _record_request(path: str, duration: float, status_code: int) -> None:
    """Record a completed request's metrics."""
    _request_counts[path] += 1

    durations = _request_durations[path]
    durations.append(duration)
    # Trim to keep only the latest samples
    if len(durations) > _MAX_DURATION_SAMPLES:
        _request_durations[path] = durations[-_MAX_DURATION_SAMPLES:]

    if status_code >= 400:
        key = f"{path}:{status_code}"
        _error_counts[key] += 1


def _percentile(sorted_values: list[float], p: float) -> float:
    """Calculate the p-th percentile from a sorted list."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[f]
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


def get_metrics() -> dict:
    """Build the metrics snapshot."""
    uptime = time.time() - _start_time

    durations_by_path = {}
    for path, durations in _request_durations.items():
        if not durations:
            continue
        sorted_d = sorted(durations)
        durations_by_path[path] = {
            "avg": sum(sorted_d) / len(sorted_d),
            "p50": _percentile(sorted_d, 0.50),
            "p99": _percentile(sorted_d, 0.99),
            "count": len(sorted_d),
        }

    # Parse error counts into {path: {status_code: count}}
    errors_by_path: dict[str, dict[str, int]] = defaultdict(dict)
    for key, count in _error_counts.items():
        path, status = key.rsplit(":", 1)
        errors_by_path[path][status] = count

    return {
        "requests_total": dict(_request_counts),
        "request_duration_seconds": durations_by_path,
        "errors_total": dict(errors_by_path),
        "uptime_seconds": round(uptime, 2),
    }


def reset_metrics() -> None:
    """Reset all metrics (useful for testing)."""
    global _start_time
    _start_time = time.time()
    _request_counts.clear()
    _request_durations.clear()
    _error_counts.clear()


# ─── Middleware ──────────────────────────────────────


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count, duration, and error status for each path."""

    async def dispatch(self, request: Request, call_next):
        # Skip recording the /metrics endpoint itself to avoid recursion noise
        path = request.url.path
        start = time.time()

        response = await call_next(request)

        duration = time.time() - start
        _record_request(path, duration, response.status_code)

        return response


# ─── /metrics endpoint ──────────────────────────────

metrics_router = APIRouter()


@metrics_router.get("/metrics")
async def metrics_endpoint():
    """Return current metrics as JSON."""
    return get_metrics()
