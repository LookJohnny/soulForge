"""Touch Perception Engine — classifies touch gestures and maps them to emotional signals.

Processes touch sensor data (e.g. MPR121 capacitive sensor arrays) into:
1. Touch gesture classification (pat, stroke, hug, squeeze, poke, hold)
2. Touch intent / emotional meaning
3. Influence on character emotion and relationship affinity
"""

import time

import structlog

from ai_core.services.cache import CacheService

logger = structlog.get_logger()

# ──────────────────────────────────────────────
# Touch gesture definitions
# ──────────────────────────────────────────────

TOUCH_GESTURES = ("pat", "stroke", "hug", "squeeze", "poke", "hold", "shake", "none")

# Zone names on the plush toy body
TOUCH_ZONES = ("head", "back", "belly", "hand_left", "hand_right", "cheek")

# Gesture → emotional meaning and character response hint
TOUCH_INTENT: dict[str, dict] = {
    "pat": {
        "intent": "安慰/鼓励",
        "prompt": "主人在轻轻拍你，像是在安慰你或鼓励你",
        "mood_hint": "happy",
        "affinity_bonus": 3,
    },
    "stroke": {
        "intent": "亲近/放松",
        "prompt": "主人在温柔地摸你，很享受和你在一起的感觉",
        "mood_hint": "happy",
        "affinity_bonus": 4,
    },
    "hug": {
        "intent": "寻求安慰",
        "prompt": "主人把你抱紧了，可能需要你的陪伴和安慰",
        "mood_hint": "lonely",
        "affinity_bonus": 6,
    },
    "squeeze": {
        "intent": "焦虑/发泄",
        "prompt": "主人用力捏着你，可能心情不太好，需要发泄一下",
        "mood_hint": "angry",
        "affinity_bonus": 2,
    },
    "poke": {
        "intent": "引起注意/玩耍",
        "prompt": "主人在戳你，想引起你的注意或者想逗你玩",
        "mood_hint": "excited",
        "affinity_bonus": 2,
    },
    "hold": {
        "intent": "安静陪伴",
        "prompt": "主人安静地握着你，享受默默的陪伴",
        "mood_hint": "neutral",
        "affinity_bonus": 3,
    },
    "shake": {
        "intent": "玩耍/兴奋",
        "prompt": "主人在摇晃你，很兴奋的样子",
        "mood_hint": "excited",
        "affinity_bonus": 2,
    },
    "none": {
        "intent": "",
        "prompt": "",
        "mood_hint": "neutral",
        "affinity_bonus": 0,
    },
}

# Zone-specific response modifiers
ZONE_MODIFIERS: dict[str, str] = {
    "head": "摸头杀！你感觉很舒服",
    "back": "主人在摸你的背，很放松",
    "belly": "肚肚被摸到了，有点痒痒的",
    "hand_left": "主人牵住了你的小手",
    "hand_right": "主人牵住了你的小手",
    "cheek": "脸蛋被揉了，有点害羞",
}

# Gesture → suggested character emotion shift
TOUCH_EMOTION_MAP: dict[str, str] = {
    "pat": "happy",
    "stroke": "calm",
    "hug": "worried",     # character senses user needs comfort → show concern
    "squeeze": "worried",
    "poke": "playful",
    "hold": "calm",
    "shake": "playful",
    "none": "calm",
}

_TOUCH_TTL = 300  # 5 min — touch context expires faster than emotion


class TouchEngine:
    """Process touch sensor data into emotional signals."""

    def __init__(self, cache: CacheService):
        self.cache = cache

    async def process_touch(
        self,
        session_id: str,
        gesture: str,
        zone: str | None = None,
        pressure: float | None = None,
        duration_ms: int | None = None,
        archetype: str = "ANIMAL",
    ) -> dict:
        """Process a touch event and return emotional signals.

        Args:
            session_id: Current session ID.
            gesture: Classified touch gesture (pat/stroke/hug/squeeze/poke/hold/shake).
            zone: Body zone where touch occurred (head/back/belly/hand_left/hand_right/cheek).
            pressure: Normalized pressure value 0.0-1.0 (optional).
            duration_ms: Duration of touch in milliseconds (optional).

        Returns:
            {
                "gesture": str,
                "zone": str|None,
                "intent": str,
                "prompt": str,            # context to inject into system prompt
                "mood_hint": str,          # suggested user mood
                "emotion_hint": str,       # suggested character emotion
                "affinity_bonus": int,     # relationship points to award
                "intensity": str,          # "gentle" | "normal" | "firm"
            }
        """
        if gesture not in TOUCH_GESTURES:
            gesture = "none"

        touch_info = TOUCH_INTENT.get(gesture, TOUCH_INTENT["none"])

        # Determine intensity from pressure
        intensity = "normal"
        if pressure is not None:
            if pressure < 0.3:
                intensity = "gentle"
            elif pressure > 0.7:
                intensity = "firm"

        # Build touch prompt with zone modifier (archetype-adaptive)
        from ai_core.services.persona_context import PersonaContext
        pctx = PersonaContext.from_archetype(archetype)

        prompt_parts = []
        adaptive_prompt = pctx.touch_prompt(gesture)
        if adaptive_prompt:
            prompt_parts.append(adaptive_prompt)
        elif touch_info["prompt"]:
            prompt_parts.append(touch_info["prompt"])  # fallback to static
        if zone:
            zone_prompt = pctx.touch_zone(zone)
            if zone_prompt:
                prompt_parts.append(zone_prompt)
            elif zone in ZONE_MODIFIERS:
                prompt_parts.append(ZONE_MODIFIERS[zone])
        if intensity == "gentle":
            prompt_parts.append("力度很轻柔")
        elif intensity == "firm":
            prompt_parts.append("力度比较大")

        prompt = "，".join(prompt_parts)

        # Adjust affinity bonus by intensity
        affinity_bonus = touch_info["affinity_bonus"]
        if intensity == "firm" and gesture in ("pat", "stroke"):
            affinity_bonus += 1
        if duration_ms and duration_ms > 3000:
            affinity_bonus += 1  # long touch bonus

        result = {
            "gesture": gesture,
            "zone": zone,
            "intent": touch_info["intent"],
            "prompt": prompt,
            "mood_hint": touch_info["mood_hint"],
            "emotion_hint": TOUCH_EMOTION_MAP.get(gesture, "calm"),
            "affinity_bonus": affinity_bonus,
            "intensity": intensity,
        }

        # Store in cache for session context
        if session_id:
            await self.cache.set_json(
                f"touch:{session_id}",
                result,
                ttl=_TOUCH_TTL,
            )

        logger.info(
            "touch.processed",
            gesture=gesture,
            zone=zone,
            intensity=intensity,
            session_id=session_id,
        )

        return result

    async def get_touch_context(self, session_id: str) -> dict | None:
        """Retrieve the most recent touch context for a session."""
        if not session_id:
            return None
        return await self.cache.get_json(f"touch:{session_id}")

    async def clear_touch_context(self, session_id: str) -> None:
        """Clear touch context after it has been consumed."""
        if session_id:
            await self.cache.delete(f"touch:{session_id}")
