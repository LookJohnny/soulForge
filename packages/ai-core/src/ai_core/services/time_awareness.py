"""Time Awareness — character knows time of day and how long since last chat.

Generates natural time-aware context for the system prompt.
Uses PersonaContext for archetype-adaptive language.
"""

from datetime import datetime, date

from ai_core.services.persona_context import PersonaContext

# ──────────────────────────────────────────────
# Time of day context ({R} = user_ref placeholder)
# ──────────────────────────────────────────────

_TIME_PERIODS = [
    (5, 8, "早上", "现在是清晨，{R}可能刚起床，可以说早安"),
    (8, 11, "上午", "现在是上午，{R}可能在上学或工作"),
    (11, 13, "中午", "现在是中午，可以问{R}吃饭了没"),
    (13, 17, "下午", "现在是下午"),
    (17, 19, "傍晚", "现在是傍晚，{R}可能刚放学/下班"),
    (19, 21, "晚上", "现在是晚上，可以聊聊今天发生的事"),
    (21, 23, "深夜", "现在比较晚了，说话轻声一点，提醒{R}早点休息"),
    (23, 5, "凌晨", "现在很晚了，{R}应该去睡觉了，温柔地催{R}睡觉"),
]

# ──────────────────────────────────────────────
# Absence duration context
# ──────────────────────────────────────────────

_ABSENCE_PROMPTS = [
    (0, 0, ""),  # same day, no comment
    (1, 1, "你们昨天聊过，今天又来啦"),
    (2, 3, "你们有两三天没聊了，可以表达一点想念"),
    (4, 7, "你们快一周没聊了，可以说好久不见，我好想你呀"),
    (8, 30, "你们好久没聊了，要热情一点，表达很想念{R}"),
    (31, 9999, "你们已经很久很久没聊了，可以说终于等到你了，我以为你忘了我"),
]


def get_time_context(now: datetime | None = None, archetype: str = "ANIMAL") -> str:
    """Get time-of-day context for system prompt."""
    if now is None:
        now = datetime.now()
    hour = now.hour
    pctx = PersonaContext.from_archetype(archetype)

    for start, end, period, desc in _TIME_PERIODS:
        if start <= end:
            if start <= hour < end:
                return desc.replace("{R}", pctx.user_ref)
        else:  # crosses midnight (23-5)
            if hour >= start or hour < end:
                return desc.replace("{R}", pctx.user_ref)
    return ""


def get_absence_context(
    last_interaction_date: str | None,
    today: date | None = None,
    archetype: str = "ANIMAL",
) -> str:
    """Get absence duration context based on last interaction date."""
    if not last_interaction_date:
        return "这是你们第一次聊天，要友好地自我介绍"

    if today is None:
        today = date.today()

    try:
        last = date.fromisoformat(last_interaction_date)
    except (ValueError, TypeError):
        return ""

    days = (today - last).days
    pctx = PersonaContext.from_archetype(archetype)

    for lo, hi, prompt in _ABSENCE_PROMPTS:
        if lo <= days <= hi:
            return prompt.replace("{R}", pctx.user_ref)
    return ""


def build_time_prompt(
    last_interaction_date: str | None = None,
    archetype: str = "ANIMAL",
) -> str:
    """Build the complete time awareness prompt section."""
    parts = []

    time_ctx = get_time_context(archetype=archetype)
    if time_ctx:
        parts.append(time_ctx)

    absence_ctx = get_absence_context(last_interaction_date, archetype=archetype)
    if absence_ctx:
        parts.append(absence_ctx)

    return "。".join(parts) if parts else ""
