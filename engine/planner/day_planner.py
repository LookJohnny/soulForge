"""24h day-plan generation from persona, goals, relationships and energy.

The day plan is high-level intent only; hour and minute planners own the detail.
"""

from __future__ import annotations

from typing import Any

from engine.planner.models import DayBlock, DayPlan, Persona, WorldState


def generate_day_plan(persona: Persona, world: WorldState,
                      archetypes: dict[str, Any] | None = None,
                      day: int | None = None) -> DayPlan:
    """Archetype profiles come from configs/characters.json; unknown archetypes
    fall back to `default`, so a new character never crashes planning."""
    if archetypes is None:
        from engine.planner.characters import load_archetypes  # lazy: avoid cycle
        archetypes = load_archetypes()
    profile = archetypes.get(persona.archetype) or archetypes["default"]
    focus = [tuple(f) for f in profile.get("focus", [])] or [("study", "自由学习")]
    primary = focus[0]
    secondary = focus[1] if len(focus) > 1 else focus[0]
    evening = profile.get("evening", "chatting")
    cooks_meals = bool(profile.get("meals"))

    low_energy = persona.energy < 0.4
    afternoon = ("rest", "能量偏低，先休息回血") if low_energy else primary

    blocks = [
        DayBlock(0, 7 * 60, "rest", "夜间休息/低功耗", persona.agent_id),
        DayBlock(7 * 60, 8 * 60, "idle", "醒来、整理自己和房间", persona.agent_id),
        DayBlock(8 * 60, 9 * 60, "cooking" if cooks_meals else "idle", "早餐时段", persona.agent_id),
        DayBlock(9 * 60, 12 * 60, "study", "上午学习/资料整理", persona.agent_id),
        DayBlock(12 * 60, 13 * 60, "cooking" if cooks_meals else "rest", "午餐与午休", persona.agent_id),
        DayBlock(13 * 60, 17 * 60, afternoon[0], afternoon[1], persona.agent_id),
        DayBlock(17 * 60, 19 * 60, secondary[0], secondary[1], persona.agent_id),
        DayBlock(19 * 60, 21 * 60, evening, "晚餐时段：做饭/收尾一天的创作/照料环境", persona.agent_id),
        DayBlock(21 * 60, 22 * 60 + 30, "chatting", "和用户与家人一起复盘今天、聊聊天", persona.agent_id),
        DayBlock(22 * 60 + 30, 24 * 60, "rest", "熄灯休息/低功耗待机", persona.agent_id),
    ]

    rationale = (
        f"{persona.name}({persona.archetype}) energy={persona.energy:.2f} mood={persona.mood_word()}; "
        f"goals={persona.daily_goals}; 用户在家={world.user_present} -> 晚上预留共同时段"
    )
    plan_day = world.day_index() if day is None else day
    return DayPlan(agent_id=persona.agent_id, blocks=blocks, rationale=rationale, day=plan_day)
