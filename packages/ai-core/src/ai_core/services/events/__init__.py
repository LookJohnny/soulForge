"""Visual-novel style events: milestones, random moments, romance arc, time-of-day."""

from ai_core.services.events.conditions import EventContext, check_condition
from ai_core.services.events.definitions import ALL_EVENTS, EVENTS_BY_ID, EventDef
from ai_core.services.events.engine import (
    EventEngine,
    TriggeredEvent,
    check_all_events,
    near_trigger_events,
)

__all__ = [
    "ALL_EVENTS",
    "EVENTS_BY_ID",
    "EventContext",
    "EventDef",
    "EventEngine",
    "TriggeredEvent",
    "check_all_events",
    "check_condition",
    "near_trigger_events",
]
