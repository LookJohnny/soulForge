"""Hierarchical companion planner: day -> hour -> minute with event-driven replanning."""

from engine.planner.models import (
    DayBlock,
    DayPlan,
    Event,
    EventKind,
    HourPlan,
    ImpactLevel,
    MinuteAction,
    Persona,
    PlanDelta,
    PlannedActivity,
    WorldState,
)
from engine.planner.templates import BehaviorTemplate, TEMPLATE_REGISTRY
from engine.planner.characters import (
    CharacterConfigError,
    character_entry,
    load_archetypes,
    load_characters,
    load_personas,
)
from engine.planner.llm_interface import BehaviorDecision, MockBehaviorLLM, build_llm
from engine.planner.day_planner import generate_day_plan
from engine.planner.hour_planner import expand_hour
from engine.planner.minute_planner import plan_minute
from engine.planner.replanner import Replanner
from engine.planner.runtime import CompanionRuntime

__all__ = [
    "BehaviorDecision",
    "BehaviorTemplate",
    "CharacterConfigError",
    "character_entry",
    "load_archetypes",
    "load_characters",
    "load_personas",
    "CompanionRuntime",
    "DayBlock",
    "DayPlan",
    "Event",
    "EventKind",
    "HourPlan",
    "ImpactLevel",
    "MinuteAction",
    "MockBehaviorLLM",
    "Persona",
    "PlanDelta",
    "PlannedActivity",
    "Replanner",
    "TEMPLATE_REGISTRY",
    "WorldState",
    "build_llm",
    "expand_hour",
    "generate_day_plan",
    "plan_minute",
]
