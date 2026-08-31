"""Hierarchical companion planner: day -> hour -> minute with event-driven replanning."""

from soulforge_harness.runtime.models import (
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
from soulforge_harness.runtime.templates import BehaviorTemplate, TEMPLATE_REGISTRY
from soulforge_harness.runtime.characters import (
    CharacterConfigError,
    character_entry,
    load_archetypes,
    load_characters,
    load_personas,
)
from soulforge_harness.runtime.llm_interface import (
    BehaviorDecision,
    MockBehaviorLLM,
    RoutedBehaviorLLM,
    build_llm,
)
from soulforge_harness.runtime.day_planner import generate_day_plan
from soulforge_harness.runtime.hour_planner import expand_hour
from soulforge_harness.runtime.minute_planner import plan_minute
from soulforge_harness.runtime.replanner import Replanner
from soulforge_harness.runtime.runtime import CompanionRuntime
from soulforge_harness.runtime.conversation import (
    Conversation,
    ConversationManager,
    SocialPolicy,
)

__all__ = [
    "BehaviorDecision",
    "BehaviorTemplate",
    "CharacterConfigError",
    "character_entry",
    "load_archetypes",
    "load_characters",
    "load_personas",
    "CompanionRuntime",
    "Conversation",
    "ConversationManager",
    "SocialPolicy",
    "DayBlock",
    "DayPlan",
    "Event",
    "EventKind",
    "HourPlan",
    "ImpactLevel",
    "MinuteAction",
    "MockBehaviorLLM",
    "RoutedBehaviorLLM",
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
