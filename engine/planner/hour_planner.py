"""Expand one hour into an HourPlan with interruptibility annotations.

`hour` is a TOTAL hour index (day 2's 07:00 is hour 55). Day-plan blocks are
day-local, so lookups go through the modulo; activity start times stay in
total minutes so the runtime can compare them across midnights.

The hour is split at DayBlock boundaries: a 22:00-23:00 hour with a block edge
at 22:30 yields chatting phases for the first half-hour and rest for the
second — non-top-of-hour boundaries are respected, not rounded away.
"""

from __future__ import annotations

from engine.planner.models import (
    DayPlan,
    HourPlan,
    Persona,
    PlannedActivity,
    WorldState,
)
from engine.planner.templates import TEMPLATE_REGISTRY

MINUTES_PER_DAY = 24 * 60

# how a one-hour block of a given family is typically phased (durations sum to 60)
_PHASING = {
    "cooking": [
        ("cooking", 10, {"step": "prep_ingredients"}),
        ("cooking", 25, {"step": "stir_pan"}),
        ("cooking", 10, {"step": "wait"}),
        ("cooking", 10, {"step": "plate_up"}),
        ("chatting", 5, {"slot": "invite_user"}),
    ],
    "drawing": [
        ("drawing", 40, {"step": "draw_stroke"}),
        ("rest", 5, {}),
        ("drawing", 15, {"step": "lean_back_review"}),
    ],
    "plant_care": [
        ("plant_care", 20, {"step": "scan_leaves"}),
        ("plant_care", 20, {"step": "water_plant"}),
        ("cleaning", 20, {"zone": "shelf"}),
    ],
    "chatting": [("chatting", 60, {"slot": "opener"})],
    "rest": [("rest", 60, {})],
    "study": [("study", 50, {"step": "read_page"}), ("rest", 10, {})],
    "cleaning": [("cleaning", 60, {"zone": "living_room"})],
    "repair": [
        ("repair", 45, {"step": "turn_wrench"}),
        ("cleaning", 15, {"zone": "workbench"}),
    ],
    "idle": [("idle", 60, {})],
}

_MOOD_DELTA = {
    "drawing": (0.15, 0.05),
    "cooking": (0.10, 0.10),
    "chatting": (0.20, 0.05),
    "plant_care": (0.08, 0.0),
    "rest": (0.10, -0.15),
    "repair": (0.05, 0.10),
    "study": (0.05, 0.05),
    "cleaning": (0.03, 0.05),
    "idle": (0.0, -0.05),
}


def _segments_for_hour(
    day_plan: DayPlan, hour_start_total: float, live_minute: float | None
) -> list[tuple[float, float, str, str]]:
    """(seg_start_total, seg_end_total, family, intent) split at block edges."""
    hour_end_total = hour_start_total + 60
    segments: list[tuple[float, float, str, str]] = []
    cursor = hour_start_total
    # mid-hour rewrites (emergency blocks) take over from the live minute onwards
    if live_minute is not None and hour_start_total <= live_minute < hour_end_total:
        cursor_probe = live_minute
    else:
        cursor_probe = cursor
    while cursor < hour_end_total:
        probe = max(cursor, cursor_probe)
        block = day_plan.block_at(probe)
        if block is None:
            family, intent = "idle", "自由时间"
            block_end_local = MINUTES_PER_DAY
        else:
            family, intent = block.activity_key, block.intent
            block_end_local = block.end_min
        # translate the block's day-local end back into total minutes
        day_base = (cursor // MINUTES_PER_DAY) * MINUTES_PER_DAY
        block_end_total = day_base + block_end_local
        if block_end_total <= cursor:  # crossed midnight inside the hour
            block_end_total += MINUTES_PER_DAY
        seg_end = min(hour_end_total, block_end_total)
        segments.append((cursor, seg_end, family, intent))
        cursor = seg_end
    return segments


def expand_hour(
    persona: Persona, day_plan: DayPlan, hour: int, world: WorldState
) -> HourPlan:
    hour_start = hour * 60.0
    live = world.sim_minute if int(world.sim_minute // 60) == hour else None
    segments = _segments_for_hour(day_plan, hour_start, live)

    activities: list[PlannedActivity] = []
    goal = None
    for seg_start, seg_end, family, intent in segments:
        if goal is None:
            goal = intent
        seg_len = seg_end - seg_start
        phases = _PHASING.get(family, _PHASING["idle"])
        scale = seg_len / 60.0
        cursor = seg_start
        for template_id, duration, params in phases:
            scaled = max(1, round(duration * scale))
            if cursor + scaled > seg_end:
                scaled = max(0, int(seg_end - cursor))
            if scaled <= 0:
                continue
            template = TEMPLATE_REGISTRY[template_id]
            activities.append(
                PlannedActivity(
                    template_id=template_id,
                    start_min=int(cursor),
                    duration_min=int(scaled),
                    params=dict(params),
                    interruptible=template.interruptible,
                    reason=f"phase of {family} block ({intent})",
                )
            )
            cursor += scaled
        if activities and cursor < seg_end:  # rounding slack -> extend last
            activities[-1].duration_min += int(seg_end - cursor)

    primary_family = segments[0][2] if segments else "idle"
    return HourPlan(
        agent_id=persona.agent_id,
        hour=hour,
        goal=goal or "自由时间",
        activities=activities,
        non_interruptible=[a.template_id for a in activities if not a.interruptible],
        expected_mood_delta=_MOOD_DELTA.get(primary_family, (0.0, 0.0)),
    )
