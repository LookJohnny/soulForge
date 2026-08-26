"""Event trigger conditions — the 21-variant vocabulary from aikeya, evaluated
against SoulForge's relationship state + current PAD emotion + the message.

All conditions on an event are AND-ed. ``EventContext`` is assembled once per
turn by the engine so every condition is a pure function.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime

from ai_core.services.relationship import days_known, normalize_stage, stage_index

# Emotion labels we produce (pad_to_emotion) — condition values are matched
# against these, and a list value means "any of".
EMOTION_LABELS = ("happy", "sad", "shy", "angry", "playful", "curious", "worried", "calm")


def time_of_day(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 21:
        return "evening"
    return "night"


@dataclass
class EventContext:
    state: dict  # relationship state (five axes, stage, streak, timestamps …)
    completed: list[str] = field(default_factory=list)
    emotion: str | None = None  # current discrete PAD emotion
    emotion_intensity: float = 0.0  # PAD magnitude 0..~1.7 mapped to 0..100 by caller
    message: str = ""
    now: datetime = field(default_factory=datetime.now)
    hours_since_last: float | None = None
    rng: random.Random | None = None

    def roll(self) -> float:
        return (self.rng or random).random()


def check_condition(cond: dict, ctx: EventContext) -> bool:
    t = cond.get("type")
    v = cond.get("value")
    st = ctx.state
    if t == "min_affection":
        return st.get("affection", 0) >= v
    if t == "min_trust":
        return st.get("trust", 0) >= v
    if t == "min_intimacy":
        return st.get("intimacy", 0) >= v
    if t == "min_comfort":
        return st.get("comfort", 0) >= v
    if t == "min_respect":
        return st.get("respect", 0) >= v
    if t == "max_energy":
        return st.get("energy", 100) <= v
    if t == "relationship_stage":
        return normalize_stage(st.get("stage")) == normalize_stage(v)
    if t == "relationship_stage_min":
        cur = stage_index(st.get("stage"))
        return cur >= 0 and cur >= stage_index(v)
    if t == "days_known":
        return days_known(st, ctx.now) >= v
    if t == "total_interactions":
        return st.get("total_interactions", 0) >= v
    if t == "max_total_interactions":  # SoulForge addition: "only while still new"
        return st.get("total_interactions", 0) <= v
    if t == "event_completed":
        return v in ctx.completed
    if t == "event_not_completed":
        return v not in ctx.completed
    if t == "time_of_day":
        return time_of_day(ctx.now) == v
    if t == "day_of_week":
        # aikeya: 0 = Sunday … 6 = Saturday
        return (ctx.now.weekday() + 1) % 7 == v
    if t == "random_chance":
        return ctx.roll() < float(v)
    if t == "keyword_mentioned":
        return bool(ctx.message) and str(v).lower() in ctx.message.lower()
    if t == "mood_is":
        wanted = v if isinstance(v, (list, tuple, set)) else [v]
        return ctx.emotion in wanted
    if t == "mood_intensity_min":
        return ctx.emotion_intensity >= v
    if t == "consecutive_days":
        return st.get("streak_days", 0) >= v
    if t == "hours_since_last_interaction_min":
        return ctx.hours_since_last is None or ctx.hours_since_last >= v
    if t == "hours_since_last_interaction_max":
        return ctx.hours_since_last is not None and ctx.hours_since_last <= v
    return False


def describe_condition(cond: dict) -> str:
    """Human-readable (Chinese) label for UI hints."""
    t, v = cond.get("type"), cond.get("value")
    if isinstance(v, (list, tuple, set)):
        v = "/".join(str(x) for x in v)
    labels = {
        "min_affection": f"好感 ≥ {v}",
        "min_trust": f"信任 ≥ {v}",
        "min_intimacy": f"亲密 ≥ {v}",
        "min_comfort": f"自在 ≥ {v}",
        "min_respect": f"尊重 ≥ {v}",
        "max_energy": f"精力 ≤ {v}",
        "relationship_stage": f"关系阶段 = {v}",
        "relationship_stage_min": f"关系阶段 ≥ {v}",
        "days_known": f"相识 ≥ {v} 天",
        "total_interactions": f"对话 ≥ {v} 次",
        "max_total_interactions": f"对话 ≤ {v} 次",
        "event_completed": f"已经历「{v}」",
        "event_not_completed": f"尚未经历「{v}」",
        "time_of_day": {
            "morning": "早上",
            "afternoon": "下午",
            "evening": "傍晚",
            "night": "夜里",
        }.get(str(v), str(v)),
        "day_of_week": "周六" if v == 6 else "周日" if v == 0 else f"周{v}",
        "random_chance": "看缘分",
        "keyword_mentioned": f"提到「{v}」",
        "mood_is": f"心情是 {v}",
        "mood_intensity_min": f"情绪强度 ≥ {v}",
        "consecutive_days": f"连续 {v} 天",
        "hours_since_last_interaction_min": f"离开 ≥ {v} 小时",
        "hours_since_last_interaction_max": f"离开 ≤ {v} 小时",
    }
    return labels.get(t, str(cond))
