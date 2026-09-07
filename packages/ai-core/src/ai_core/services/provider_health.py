"""Process-local observations of actual provider calls; never active probes.

Only provider/model labels, timing, counters and exception *types* are kept.
Provider messages, request data, endpoints and credentials never enter a snapshot.
"""

from __future__ import annotations

import copy
import re
import threading
from datetime import UTC, datetime

from ai_core.config import settings


class EmptyProviderResponse(RuntimeError):
    """A request completed without usable text or audio."""


def _label(value) -> str:
    if not isinstance(value, str) or "://" in value:
        return "unknown"
    return value[:128] if re.fullmatch(r"[A-Za-z0-9_./:+-]{1,128}", value) else "unknown"


def tts_model(provider: str) -> str:
    if provider == "fish":
        return settings.fish_audio_model
    if provider == "edge":
        return "edge-tts"
    return settings.tts_model


class ProviderHealthRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._states: dict[tuple[str, str, str], dict] = {}

    @staticmethod
    def _initial(kind: str, provider: str, model: str) -> dict:
        return {
            "kind": _label(kind),
            "provider": _label(provider),
            "model": _label(model),
            "status": "unknown",
            "success_count": 0,
            "failure_count": 0,
            "consecutive_failures": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "last_latency_ms": None,
            "last_error": None,
        }

    def _record(self, kind, provider, model, latency_ms, error=None):
        key = (_label(kind), _label(provider), _label(model))
        stamp = datetime.now(UTC).isoformat()
        with self._lock:
            state = self._states.setdefault(key, self._initial(*key))
            state["last_latency_ms"] = round(max(0.0, latency_ms), 1)
            if error is None:
                state.update(status="ok", consecutive_failures=0, last_error=None)
                state["success_count"] += 1
                state["last_success_at"] = stamp
            else:
                # Do not call str(error): provider errors frequently contain tokens,
                # URLs, request fragments or identifying user information.
                code = getattr(error, "status_code", None)
                state["last_error"] = {"type": _label(type(error).__name__)}
                if type(code) is int and 100 <= code <= 599:
                    state["last_error"]["status_code"] = code
                state["status"] = "degraded"
                state["failure_count"] += 1
                state["consecutive_failures"] += 1
                state["last_failure_at"] = stamp

    def record_success(self, kind, provider, model, latency_ms):
        self._record(kind, provider, model, latency_ms)

    def record_failure(self, kind, provider, model, latency_ms, error):
        self._record(kind, provider, model, latency_ms, error)

    def snapshot(self) -> dict:
        configured = [
            ("llm", settings.llm_provider, settings.llm_model),
            ("asr", settings.asr_provider, settings.asr_model),
            ("tts", settings.tts_provider, tts_model(settings.tts_provider)),
        ]
        with self._lock:
            states = {tuple(map(_label, key)): self._initial(*key) for key in configured}
            states.update(copy.deepcopy(self._states))
        providers = [states[key] for key in sorted(states)]
        statuses = {item["status"] for item in providers}
        status = (
            "degraded" if "degraded" in statuses else "unknown" if "unknown" in statuses else "ok"
        )
        return {
            "service": "ai-core",
            "status": status,
            "observation_only": True,
            "scope": "current_process",
            "providers": providers,
        }


provider_health = ProviderHealthRegistry()
