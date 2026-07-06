"""Intent model for the SoulForge physical AI engine.

Intent is the narrow contract between cognitive systems and physical
scheduling. The payload can keep the existing structured LLM response; the
physical layer only needs source, priority, preemption, TTL, and an action
template reference.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Priority(IntEnum):
    IDLE = 10
    PLAN = 50
    REACTIVE = 90


DEFAULT_PREEMPTIBLE: dict[str, bool] = {
    "idle": True,
    "plan": True,
    "reactive": False,
}


DEFAULT_PRIORITY: dict[str, Priority] = {
    "idle": Priority.IDLE,
    "plan": Priority.PLAN,
    "reactive": Priority.REACTIVE,
}


@dataclass(order=True)
class Intent:
    """A schedulable physical intention.

    `payload` is intentionally untyped. For LLM responses it can be the full
    structured response; for tests and demos it may only carry a label.
    """

    priority: Priority
    source: str = field(compare=False)
    action_template_id: str | None = field(default=None, compare=False)
    payload: dict[str, Any] = field(default_factory=dict, compare=False)
    preemptible: bool = field(default=True, compare=False)
    ttl_ms: int = field(default=8000, compare=False)
    created_at: float = field(default_factory=time.monotonic, compare=False)
    intent_id: str = field(default_factory=lambda: uuid.uuid4().hex, compare=False)

    @classmethod
    def create(
        cls,
        source: str,
        action_template_id: str | None = None,
        payload: dict[str, Any] | None = None,
        priority: Priority | int | None = None,
        preemptible: bool | None = None,
        ttl_ms: int = 8000,
        created_at: float | None = None,
    ) -> "Intent":
        normalized_source = source.lower()
        resolved_priority = (
            Priority(priority)
            if priority is not None
            else DEFAULT_PRIORITY.get(normalized_source, Priority.PLAN)
        )
        resolved_preemptible = (
            preemptible
            if preemptible is not None
            else DEFAULT_PREEMPTIBLE.get(normalized_source, True)
        )
        return cls(
            source=normalized_source,
            priority=resolved_priority,
            action_template_id=action_template_id,
            payload=payload or {},
            preemptible=resolved_preemptible,
            ttl_ms=ttl_ms,
            created_at=time.monotonic() if created_at is None else created_at,
        )

    def is_expired(self, now: float | None = None) -> bool:
        if self.ttl_ms <= 0:
            return False
        current = time.monotonic() if now is None else now
        return (current - self.created_at) * 1000 > self.ttl_ms

    @property
    def resumable(self) -> bool:
        return self.source == "plan"
