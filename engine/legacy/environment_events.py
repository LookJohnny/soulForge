"""External environment event interface.

Computer simulations, robots, and games can all feed events into the physical
AI engine by normalizing their state changes into EnvironmentEvent objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EnvironmentEvent:
    t: float
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "environment"


class EnvironmentAdapter(Protocol):
    def events_between(self, start_s: float, end_s: float) -> list[EnvironmentEvent]:
        """Return external events in [start_s, end_s]."""


class ScriptedEnvironmentAdapter:
    """Deterministic adapter useful for tests, games, and scenario playback."""

    def __init__(self, events: list[EnvironmentEvent] | None = None):
        self.events = sorted(events or [], key=lambda event: event.t)

    def events_between(self, start_s: float, end_s: float) -> list[EnvironmentEvent]:
        return [event for event in self.events if start_s <= event.t <= end_s]


EVENT_TEMPLATE_MAP = {
    "user_detected": "look_at_user",
    "user_interrupt": "look_at_user",
    "voice": "look_at_user",
    "touch": "look_at_user",
    "greeting": "greeting_wave",
    "game_reward": "happy_wiggle",
    "achievement": "happy_wiggle",
    "question": "thinking_idle",
    "boredom": "curious_scan",
    "fatigue": "sleep_breathing",
}


def event_to_template(event: EnvironmentEvent) -> str:
    explicit = event.payload.get("action_template_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    return EVENT_TEMPLATE_MAP.get(event.event_type, "look_at_user")
