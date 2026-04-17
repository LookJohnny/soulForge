"""Proactive Trigger Service — character initiates topics based on memories.

On the first message of a new session, the character may proactively bring up
a past topic, interest, or event. Probability depends on relationship stage.

Trigger types:
- memory_recall: "上次你说要考试，考完了吗？"
- interest_prompt: "你不是喜欢恐龙吗？今天想聊恐龙吗？"
- greeting_variation: relationship-stage-appropriate greeting
"""

import random

import structlog

from ai_core.services.cache import CacheService
from ai_core.services.relationship import STAGE_TRIGGER_PROB

logger = structlog.get_logger()

# Greeting templates per stage — variety so greeting doesn't feel scripted.
# These are *seeds* for the LLM, not literal lines it must say.
_GREETINGS: dict[str, list[str]] = {
    "FAMILIAR": [
        "今天过得怎么样？",
        "诶，你来了",
        "又见面啦",
        "今天有空聊会儿吗",
    ],
    "FRIEND": [
        "来啦——今天有什么事想说",
        "等你好久了",
        "嘿，想我了没",
        "正准备找你呢，你就来了",
    ],
    "BESTFRIEND": [
        "你来啦！我刚还在想你",
        "终于等到你了",
        "好想你呀，快说说最近",
        "哎——你怎么才来",
    ],
}

# Memory-based trigger templates — varied, softer phrasings so recall
# feels like a stray thought, not a database lookup.
_MEMORY_TRIGGERS: dict[str, list[str]] = {
    "PREFERENCE": [
        "你不是{content}吗？今天想聊这个吗",
        "突然想到——你好像{content}？",
        "对了，{content}的事今天还算数吗",
    ],
    "EVENT": [
        "上次你说{content}，后来怎么样了",
        "你之前提到{content}，想起来问一下",
        "{content}的事……过得还顺吗",
    ],
    "TOPIC": [
        "我们上次聊了{content}，今天还想继续吗",
        "想起来上次在聊{content}",
        "上回没说完{content}的事呢",
    ],
}

# Priority order for selecting memory type
_TYPE_PRIORITY = ["PREFERENCE", "EVENT", "TOPIC"]

# Mid-session nudges — fire when user has gone quiet or flipped mood.
# These are prompt *hints*, not lines to speak verbatim.
_MID_SESSION_NUDGES = {
    "long_silence": "你想主动开口——不用打破气氛，一句轻声的话就好。",
    "mood_darken": "你察觉到对方的情绪沉下来了，靠近一点，但别追问原因。",
    "mood_lighten": "对方的心情好像松开了，你可以悄悄陪着这份轻快。",
}


class ProactiveTriggerService:
    """Generate proactive conversation openers based on memories and relationship."""

    def __init__(self, cache: CacheService):
        self.cache = cache

    async def maybe_generate_trigger(
        self,
        end_user_id: str,
        character_id: str,
        session_id: str,
        relationship_stage: str,
        memories: list[dict],
    ) -> str | None:
        """Generate a proactive trigger for the first message of a session.

        Returns a trigger string or None if no trigger should fire.
        """
        if not end_user_id or not session_id:
            return None

        # Only fire on first message of session
        session_key = f"session_started:{session_id}"
        existing = await self.cache.get(session_key)
        if existing:
            return None  # Not first message
        await self.cache.set(session_key, "1", ttl=1800)

        # Check stage eligibility
        prob = STAGE_TRIGGER_PROB.get(relationship_stage, 0.0)
        if prob <= 0:
            return None

        # Roll probability
        if random.random() > prob:
            return None

        # Try memory-based trigger first
        if memories:
            trigger = self._select_memory_trigger(memories, end_user_id, character_id)
            if trigger:
                return trigger

        # Fallback to greeting
        return self._random_greeting(relationship_stage)

    def _select_memory_trigger(
        self, memories: list[dict], end_user_id: str, character_id: str
    ) -> str | None:
        """Select the best memory to reference, prioritizing by type."""
        # Group by type
        by_type: dict[str, list[dict]] = {}
        for m in memories:
            mt = m.get("type", "TOPIC")
            by_type.setdefault(mt, []).append(m)

        # Pick by priority
        for ptype in _TYPE_PRIORITY:
            candidates = by_type.get(ptype, [])
            if candidates:
                chosen = candidates[0]  # Newest first (already sorted)
                templates = _MEMORY_TRIGGERS.get(ptype) or ["我们上次聊了{content}，你还记得吗？"]
                template = random.choice(templates)
                return template.format(content=chosen["content"])

        return None

    def _random_greeting(self, stage: str) -> str | None:
        """Pick a random greeting appropriate for the relationship stage."""
        greetings = _GREETINGS.get(stage)
        if not greetings:
            return None
        return random.choice(greetings)

    def mid_session_nudge(
        self,
        *,
        silence_seconds: float,
        user_mood: str | None,
        prev_user_mood: str | None,
    ) -> str | None:
        """Return a mid-session inner-thought hint (or None).

        Fires on long silence or noticeable mood shift within the session —
        gives the character permission to proactively adjust its approach
        instead of mechanically answering the last message.
        """
        if prev_user_mood and user_mood and prev_user_mood != user_mood:
            darkening = {"sad", "worried", "lonely", "angry", "tired"}
            lightening = {"happy", "excited"}
            if user_mood in darkening and prev_user_mood in lightening | {"neutral"}:
                return _MID_SESSION_NUDGES["mood_darken"]
            if user_mood in lightening and prev_user_mood in darkening:
                return _MID_SESSION_NUDGES["mood_lighten"]

        if silence_seconds >= 90:
            return _MID_SESSION_NUDGES["long_silence"]

        return None
