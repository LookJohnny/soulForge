"""Small, thread-safe provider telemetry with no credentials or prompt content."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from datetime import datetime, timezone


class ProviderHealthRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._providers: dict[str, dict] = {}

    def configure(self, name: str, model: str = "", *, mock: bool = False) -> None:
        with self._lock:
            self._providers.setdefault(name, {
                "provider": name, "model": model, "status": "mock" if mock else "unknown",
                "calls": 0, "successes": 0, "failures": 0, "fallback_count": 0,
                "consecutive_failures": 0, "fallback_active": mock,
                "last_success_at": None, "last_failure_at": None,
                "last_error": "mock_configured" if mock else None,
                "last_latency_ms": None,
            })

    def record_success(self, name: str, model: str = "", latency_ms: float = 0) -> None:
        self.configure(name, model)
        with self._lock:
            item = self._providers[name]
            item.update(status="ok", model=model, consecutive_failures=0,
                        fallback_active=False, last_error=None,
                        last_success_at=datetime.now(timezone.utc).isoformat(),
                        last_latency_ms=round(latency_ms, 1))
            item["calls"] += 1
            item["successes"] += 1

    def record_failure(self, name: str, model: str = "", error_type: str = "error",
                       *, fallback: bool = True, latency_ms: float = 0) -> None:
        self.configure(name, model)
        # Callers pass exception types / fixed codes, never exception bodies.
        error_type = str(error_type).split(":", 1)[0][:80]
        with self._lock:
            item = self._providers[name]
            item.update(status="degraded", model=model, fallback_active=fallback,
                        last_error=error_type,
                        last_failure_at=datetime.now(timezone.utc).isoformat(),
                        last_latency_ms=round(latency_ms, 1))
            item["calls"] += 1
            item["failures"] += 1
            item["consecutive_failures"] += 1
            item["fallback_count"] += int(fallback)

    def snapshot(self) -> dict:
        with self._lock:
            providers = deepcopy(list(self._providers.values()))
        fallback = any(p["fallback_active"] for p in providers)
        statuses = {p["status"] for p in providers}
        status = "degraded" if fallback or "degraded" in statuses else (
            "unknown" if not providers or "unknown" in statuses else "ok"
        )
        return {"status": status, "fallback_active": fallback,
                "fallback_count": sum(p["fallback_count"] for p in providers),
                "providers": providers, "observed_at": time.time()}
