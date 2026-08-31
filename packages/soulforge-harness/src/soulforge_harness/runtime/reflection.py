"""End-of-day reflection: memories → insights → tomorrow's goals.

The Generative Agents loop in miniature. Deterministic on purpose (no extra
LLM call, no network): a handful of rules read the day's episodic memory keys
that the runtime already writes (`talked_with_<agent>`, `user_mood`,
`last_user_request`, `critical_event`) and turn them into short first-person
insights. Insights are stored as a `reflective` memory layer, kept on
`persona.meta["reflections"]` for the prompt, and each one may push a goal
into `persona.daily_goals` — which is what makes the next day plan differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soulforge_harness.runtime.models import Persona

MAX_REFLECTIONS = 5
MAX_GOALS = 4
NEGATIVE = (
    "累",
    "难过",
    "伤心",
    "烦",
    "焦虑",
    "孤单",
    "不开心",
    "哭",
    "压力",
    "tired",
    "sad",
)


@dataclass
class Reflection:
    insight: str  # first person, what I now believe
    evidence: list[str]  # memory keys that support it
    goal: str | None = None  # a daily goal to carry into tomorrow
    prefer_template: str | None = None  # a behaviour the planner should make room for


def reflect_day(
    persona: Persona, memories: dict[str, Any], names: dict[str, str] | None = None
) -> list[Reflection]:
    names = names or {}
    out: list[Reflection] = []

    talked = [k for k in memories if k.startswith("talked_with_")]
    for key in talked:
        other = key[len("talked_with_") :]
        name = names.get(other, other)
        close = persona.relationships.get(other, 0.5)
        if close >= 0.7:
            out.append(
                Reflection(
                    f"和{name}聊天很自在，我想明天多和{name}待一会儿。",
                    [key],
                    goal=f"和{name}聊聊",
                    prefer_template="chatting",
                )
            )
        else:
            out.append(Reflection(f"今天和{name}说上话了，我们还不算熟。", [key]))

    mood = str(memories.get("user_mood") or "")
    if any(w in mood for w in NEGATIVE):
        out.append(
            Reflection(
                "用户最近有点累，晚上少安排事情，多陪陪。",
                ["user_mood"],
                goal="多陪用户",
                prefer_template="chatting",
            )
        )
    if memories.get("last_user_request"):
        out.append(
            Reflection(
                f"用户提过想要「{str(memories['last_user_request'])[:24]}」，明天记得。",
                ["last_user_request"],
                goal=f"记得：{str(memories['last_user_request'])[:24]}",
            )
        )
    if memories.get("critical_event"):
        out.append(
            Reflection(
                f"发生过「{str(memories['critical_event'])[:24]}」，之后要多留意。",
                ["critical_event"],
            )
        )
    return out[:MAX_REFLECTIONS]


def apply_reflections(persona: Persona, reflections: list[Reflection]) -> None:
    """Fold insights into the persona: prompt context + tomorrow's goals."""
    if not reflections:
        return
    kept = [r.insight for r in reflections]
    persona.meta["reflections"] = (persona.meta.get("reflections", []) + kept)[
        -MAX_REFLECTIONS:
    ]
    prefer = [r.prefer_template for r in reflections if r.prefer_template]
    if prefer:
        persona.meta["prefer_template"] = prefer[0]
    goals = [r.goal for r in reflections if r.goal]
    for goal in reversed(goals):
        if goal in persona.daily_goals:
            persona.daily_goals.remove(goal)
        persona.daily_goals.insert(0, goal)
    del persona.daily_goals[MAX_GOALS:]
