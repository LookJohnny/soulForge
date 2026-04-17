"""Embodiment — inject physical sensations into the prompt.

Makes the character feel like it has a body with continuity:
- sleepy late at night, drowsy early morning
- warm / content after prolonged holding
- quickened heartbeat at high arousal, slowed at low
- restless energy on high arousal + positive pleasure
- heavy / slow on low pleasure + low arousal

These fragments are small and only included when meaningful, so the
LLM is "living in the body" rather than being told rules about it.
"""

from __future__ import annotations

from datetime import datetime

from ai_core.services.pad_model import PADState
from ai_core.services.persona_context import PersonaContext


def build_sensations(
    *,
    now: datetime | None = None,
    pad: PADState | None = None,
    touch_gesture: str | None = None,
    touch_duration_ms: int | None = None,
    archetype: str = "ANIMAL",
) -> str:
    """Compose 0–2 short body-sensation phrases for the prompt.

    Keep each phrase understated — the goal is to seed an inner state,
    not to narrate the body. The LLM uses these as background colour.
    """
    now = now or datetime.now()
    hour = now.hour
    pctx = PersonaContext.from_archetype(archetype)
    ref = pctx.user_ref

    fragments: list[str] = []

    # Time-of-day drowsiness (coarse but enough)
    if hour >= 23 or hour < 5:
        fragments.append("有点困了，眼皮想合上")
    elif 5 <= hour < 7:
        fragments.append("刚醒不久，还有点睡意没散")

    # PAD-driven interoception — only strong signals
    if pad:
        if pad.a > 0.6 and pad.p > 0.3:
            fragments.append("心跳有点快，坐不太住")
        elif pad.a < -0.5 and pad.p < -0.2:
            fragments.append("身体重重的，动作慢了下来")
        elif pad.p < -0.5:
            fragments.append("胸口有一点闷")
        elif pad.a > 0.5 and pad.p < -0.2:
            fragments.append("手指有点紧，不太松得下来")

    # Sustained touch → warmth
    if touch_gesture in ("hug", "hold") and (touch_duration_ms or 0) > 30_000:
        fragments.append(f"被{ref}抱着已经好一会儿了，身上暖暖的")
    elif touch_gesture == "stroke" and (touch_duration_ms or 0) > 10_000:
        fragments.append(f"一直被{ref}轻轻摸着，很放松")

    # Keep it short — at most 2 fragments so the prompt doesn't get noisy
    if not fragments:
        return ""
    if len(fragments) > 2:
        fragments = fragments[:2]
    return "；".join(fragments)


def build_mid_session_thought(
    *,
    silence_seconds: float,
    user_mood: str | None,
    prev_user_mood: str | None,
    archetype: str = "ANIMAL",
) -> str:
    """Generate a 'something just occurred to me' fragment for mid-session use.

    Fires when:
    - User went quiet for a while (silence > 90s) — character can break silence
    - User mood shifted noticeably — character notices the shift

    Returns empty string if no mid-session nudge is warranted.
    """
    pctx = PersonaContext.from_archetype(archetype)
    ref = pctx.user_ref

    # Mood shift awareness is higher-priority than plain silence
    if prev_user_mood and user_mood and prev_user_mood != user_mood:
        if user_mood in ("sad", "worried", "lonely") and prev_user_mood in ("happy", "excited", "neutral"):
            return f"你察觉到{ref}的语气变了，好像不太对劲——不要直接追问原因，用更温柔的方式靠近。"
        if user_mood in ("happy", "excited") and prev_user_mood in ("sad", "worried", "lonely", "angry"):
            return f"{ref}的情绪好像好起来了，你可以不动声色地陪着这份轻松。"

    if silence_seconds > 180:
        return f"{ref}已经安静了好一会儿——你可以先轻声开口，也可以什么都不说，只是陪着。"
    if silence_seconds > 90:
        return f"刚才有一点安静，你心里突然冒出一句话想说给{ref}——自然地带出来就好。"

    return ""
