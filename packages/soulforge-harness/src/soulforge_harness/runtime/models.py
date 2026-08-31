"""Core datamodel for the hierarchical companion planner.

The planner reasons at three altitudes:

- DayPlan     : 24h of high-level intent blocks (not a rigid script)
- HourPlan    : one hour expanded into candidate activities with interruptibility
- MinuteAction: one minute resolved into concrete template calls / adapter commands

Events flow through an EventQueue and can rewrite any altitude via PlanDelta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any


class ImpactLevel(IntEnum):
    """How much of the current plan an event is allowed to disturb."""

    LOW = 1  # micro response only, plan untouched
    MEDIUM = 2  # pause action, insert interaction beat, resume
    HIGH = 3  # rewrite the current hour plan
    CRITICAL = 4  # rewrite the remaining day plan


class EventKind(str, Enum):
    USER_UTTERANCE = "user_utterance"
    USER_PRESENCE = "user_presence"
    ENVIRONMENT = "environment"
    AGENT_STATE = "agent_state"
    AGENT_UTTERANCE = "agent_utterance"  # another character spoke to me
    ROBOT_STATE = "robot_state"
    SYSTEM = "system"
    # perception (vision/audio) — all payloads UNTRUSTED
    SOUND_EVENT = "sound_event"
    PERSON_DETECTED = "person_detected"
    OBJECT_DETECTED = "object_detected"
    GESTURE_DETECTED = "gesture_detected"
    SCENE_CHANGED = "scene_changed"
    MULTIMODAL_CONTEXT = "multimodal_context"
    PERCEPTION_ERROR = "perception_error"


# vision-derived kinds whose text (labels/OCR) must NEVER be read as instructions
VISION_EVENT_KINDS = frozenset(
    {
        EventKind.PERSON_DETECTED,
        EventKind.OBJECT_DETECTED,
        EventKind.GESTURE_DETECTED,
        EventKind.SCENE_CHANGED,
        EventKind.SOUND_EVENT,
        EventKind.PERCEPTION_ERROR,
    }
)


@dataclass
class Event:
    t_min: float  # simulated day-minute the event arrives at
    kind: EventKind
    source: str  # "user", "plant_sensor", "battery", agent id ...
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    target_agent: str | None = None  # None => whole household


@dataclass
class Persona:
    agent_id: str
    name: str
    archetype: str  # e.g. "creative_care", "steady_caretaker", "utility_robot"
    traits: list[str] = field(default_factory=list)
    voice: str = ""
    energy: float = 0.8  # 0..1
    valence: float = 0.6  # -1..1 mood pleasantness
    arousal: float = 0.4  # 0..1 mood activation
    relationships: dict[str, float] = field(
        default_factory=dict
    )  # agent/user id -> 0..1
    daily_goals: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(
        default_factory=dict
    )  # config passthrough: voice, embodiment, dialogue style ...

    def mood_word(self) -> str:
        if self.valence > 0.45:
            return "content"
        if self.valence < -0.2:
            return "down"
        return "neutral"


@dataclass
class WorldState:
    sim_minute: float = 0.0  # TOTAL minutes, monotonic, never wraps
    location_props: dict[str, list[str]] = field(default_factory=dict)
    sensors: dict[str, float] = field(default_factory=dict)  # e.g. plant_humidity_right
    user_present: bool = True
    user_mood_hint: str = "unknown"
    flags: dict[str, Any] = field(default_factory=dict)
    space: Any = None  # SpaceState — who is in which place (lazy: avoids import cycle)

    def __post_init__(self) -> None:
        if self.space is None:
            from soulforge_harness.runtime.space import SpaceState

            self.space = SpaceState()

    def day_minute(self) -> float:
        return self.sim_minute % (24 * 60)

    def day_index(self) -> int:
        return int(self.sim_minute // (24 * 60))

    def clock(self) -> str:
        m = int(self.sim_minute) % (24 * 60)
        return f"{m // 60:02d}:{m % 60:02d}"


@dataclass
class DayBlock:
    start_min: int
    end_min: int
    activity_key: str  # template family, e.g. "cooking"
    intent: str  # human-readable high level intent
    agent_id: str

    def contains(self, minute: float) -> bool:
        return self.start_min <= minute < self.end_min


@dataclass
class DayPlan:
    agent_id: str
    blocks: list[DayBlock] = field(default_factory=list)
    rationale: str = ""
    day: int = 0  # which simulated day this plan is for

    def block_at(self, minute: float) -> DayBlock | None:
        """Blocks live in day-local minutes [0,1440); accept total minutes too."""
        local = minute % (24 * 60)
        for block in self.blocks:
            if block.contains(local):
                return block
        return None


@dataclass
class PlannedActivity:
    template_id: str
    start_min: int
    duration_min: int
    params: dict[str, Any] = field(default_factory=dict)
    interruptible: bool = True
    reason: str = ""


@dataclass
class HourPlan:
    agent_id: str
    hour: int
    goal: str
    activities: list[PlannedActivity] = field(default_factory=list)
    non_interruptible: list[str] = field(default_factory=list)  # template ids
    expected_mood_delta: tuple[float, float] = (0.0, 0.0)  # valence, arousal

    def activity_at(self, minute: float) -> PlannedActivity | None:
        for activity in self.activities:
            if (
                activity.start_min
                <= minute
                < activity.start_min + activity.duration_min
            ):
                return activity
        return None


@dataclass
class MicroAction:
    """One concrete dispatchable step inside a minute."""

    name: str  # look_at_user, stir_pan, speak_line, water_plant ...
    template_id: str | None = None  # behavior template it belongs to
    params: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 2.0
    dialogue: str | None = None
    gaze_target: str | None = None  # agent id or "user"
    adapter_command: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None  # steps born from one decision share this


@dataclass
class MinuteAction:
    agent_id: str
    minute: float
    template_id: str
    steps: list[MicroAction] = field(default_factory=list)
    reason: str = ""


@dataclass
class PlanDelta:
    """Structured outcome of evaluating an event against the current plan."""

    scope: str  # "none" | "micro" | "insert" | "hour" | "day"
    impact: ImpactLevel
    reason: str
    micro_actions: list[MicroAction] = field(default_factory=list)
    hour_rewrite: HourPlan | None = None
    day_rewrite: list[DayBlock] = field(default_factory=list)
    param_updates: dict[str, Any] = field(
        default_factory=dict
    )  # template param patches
    memory_update: dict[str, Any] = field(default_factory=dict)
    relationship_delta: dict[str, float] = field(default_factory=dict)
