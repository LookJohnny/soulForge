"""24-hour hierarchical autonomy planning.

The planner builds a coarse daily rhythm first, then expands each hour into
minute-level physical actions. It never emits raw servo angles; it only selects
fixed ActionTemplate IDs that the physical executor can safely compile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class ActivityBlock:
    start_minute: int
    end_minute: int
    activity_type: str
    label: str
    energy: float
    social: float
    notes: str = ""

    def contains(self, minute_of_day: int) -> bool:
        minute = minute_of_day % MINUTES_PER_DAY
        if self.start_minute <= self.end_minute:
            return self.start_minute <= minute < self.end_minute
        return minute >= self.start_minute or minute < self.end_minute


@dataclass(frozen=True)
class MinuteAction:
    minute_of_day: int
    activity_type: str
    action_template_id: str
    source: str
    priority: int
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DailyPlan:
    blocks: list[ActivityBlock]
    profile: dict[str, Any] = field(default_factory=dict)

    def block_at(self, minute_of_day: int) -> ActivityBlock:
        for block in self.blocks:
            if block.contains(minute_of_day):
                return block
        raise LookupError(f"No activity block covers minute {minute_of_day}")


class DailyAutonomyPlanner:
    """Plan a full day, then resolve minute-level physical actions."""

    def __init__(self, profile: dict[str, Any] | None = None):
        self.profile = profile or {}

    def build_24h_plan(self) -> DailyPlan:
        """Return default companion-style day rhythm covering all 1440 minutes."""
        blocks = [
            ActivityBlock(0, 420, "sleep", "night sleep", 0.10, 0.05, "low motion"),
            ActivityBlock(420, 540, "wake", "wake up and orient", 0.45, 0.35),
            ActivityBlock(540, 720, "curious", "morning curiosity", 0.70, 0.45),
            ActivityBlock(720, 840, "rest", "midday rest", 0.35, 0.25),
            ActivityBlock(840, 1080, "active", "afternoon active loop", 0.75, 0.55),
            ActivityBlock(
                1080, 1320, "social", "evening social companionship", 0.65, 0.85
            ),
            ActivityBlock(1320, 1440, "quiet", "night quiet mode", 0.20, 0.20),
        ]
        return DailyPlan(blocks=blocks, profile=dict(self.profile))

    def expand_hour(self, plan: DailyPlan, hour: int) -> list[MinuteAction]:
        start = (hour % 24) * 60
        return [self.action_for_minute(plan, start + offset) for offset in range(60)]

    def action_for_elapsed(
        self,
        plan: DailyPlan,
        elapsed_s: float,
        *,
        start_minute_of_day: int = 0,
    ) -> MinuteAction:
        minute = (start_minute_of_day + int(elapsed_s // 60)) % MINUTES_PER_DAY
        return self.action_for_minute(plan, minute)

    def action_for_minute(self, plan: DailyPlan, minute_of_day: int) -> MinuteAction:
        minute = minute_of_day % MINUTES_PER_DAY
        block = plan.block_at(minute)
        minute_in_block = (minute - block.start_minute) % MINUTES_PER_DAY
        template_id, reason = self._template_for(block, minute, minute_in_block)
        source = "idle" if block.activity_type in {"sleep", "quiet", "rest"} else "plan"
        priority = 10 if source == "idle" else 50
        return MinuteAction(
            minute_of_day=minute,
            activity_type=block.activity_type,
            action_template_id=template_id,
            source=source,
            priority=priority,
            reason=reason,
            metadata={
                "block_label": block.label,
                "energy": block.energy,
                "social": block.social,
            },
        )

    def _template_for(
        self,
        block: ActivityBlock,
        minute_of_day: int,
        minute_in_block: int,
    ) -> tuple[str, str]:
        activity = block.activity_type
        minute = minute_of_day % 60

        if activity == "sleep":
            if minute % 10 == 0:
                return "sleep_breathing", "sleep breathing cycle"
            return "idle_scan", "minimal night idle"

        if activity == "quiet":
            if minute % 15 == 0:
                return "sleep_breathing", "night quiet settling"
            return "idle_scan", "low-disturbance scan"

        if activity == "wake":
            if minute_in_block in {0, 1, 30}:
                return "daily_stretch", "wake-up stretch"
            if minute % 7 == 0:
                return "curious_scan", "orient after wake"
            return "idle_scan", "wake idle"

        if activity == "curious":
            if minute % 12 == 0:
                return "curious_scan", "environment curiosity scan"
            if minute % 20 == 5:
                return "thinking_idle", "self-directed thinking"
            return "idle_scan", "curious background motion"

        if activity == "rest":
            if minute % 20 == 0:
                return "sleep_breathing", "midday rest breath"
            return "idle_scan", "rest idle"

        if activity == "active":
            if minute % 15 == 0:
                return "daily_stretch", "periodic active stretch"
            if minute % 10 == 5:
                return "happy_wiggle", "self-initiated playful motion"
            if minute % 7 == 3:
                return "curious_scan", "active environment scan"
            return "idle_scan", "active idle fill"

        if activity == "social":
            if minute % 15 == 0:
                return "greeting_wave", "social availability signal"
            if minute % 10 == 4:
                return "look_at_user", "maintain user attention"
            if minute % 6 == 2:
                return "micro_nod", "small listening cue"
            return "idle_scan", "social idle fill"

        return "idle_scan", "fallback idle"
