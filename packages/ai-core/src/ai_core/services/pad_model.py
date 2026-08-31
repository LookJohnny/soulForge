"""PAD engine (session state, cache, relationship weighting).

The pure math moved to soulforge_harness.persona.pad; this module keeps the
stateful engine and re-exports everything for compatibility.
"""

from __future__ import annotations

import math  # noqa: F401  (kept for engine internals)
import time  # noqa: F401

import structlog
from soulforge_harness.persona.pad import (  # noqa: F401
    _BASELINE_TTL,
    _CAUSES_TTL,
    _DEFAULT_REL_WEIGHTS,
    _MAX_CAUSES,
    _PAD_TTL,
    _WALL_DECAY_PER_HOUR,
    BASE_DECAY_RATE,
    BASE_EMPATHY_WEIGHT,
    BASE_TOUCH_STRENGTH,
    BASE_TRANSITION_SPEED,
    EMOTION_PAD_ANCHORS,
    RELATIONSHIP_WEIGHTS,
    TOUCH_PAD_IMPULSE,
    USER_MOOD_PAD,
    PADState,
    emotion_to_pad,
    pad_to_emotion,
    pad_to_prompt_description,
    pad_to_tts_offsets,
    personality_to_baseline,
    transition_pad,
)

from ai_core.services.cache import CacheService

logger = structlog.get_logger()


class PADEngine:
    """Manage PAD emotional state with personality-aware dynamics."""

    def __init__(self, cache: CacheService):
        self.cache = cache

    async def get_pad(self, session_id: str, now: float | None = None) -> PADState:
        if not session_id:
            return PADState.neutral()
        data = await self.cache.get_json(f"pad:{session_id}")
        if not data:
            return PADState.neutral()
        state = PADState.from_dict(data)
        ts = data.get("ts")
        if ts is None:
            return state
        now = time.time() if now is None else now
        hours = max(0.0, (now - float(ts)) / 3600)
        if hours < 1.0:
            return state
        baseline = await self.get_baseline(session_id) or PADState.neutral()
        decayed = state.lerp(baseline, min(1.0, _WALL_DECAY_PER_HOUR * hours))
        await self.set_pad(session_id, decayed, now=now)
        return decayed

    async def set_pad(self, session_id: str, state: PADState, now: float | None = None) -> None:
        if not session_id:
            return
        payload = {**state.to_dict(), "ts": time.time() if now is None else now}
        await self.cache.set_json(f"pad:{session_id}", payload, ttl=_PAD_TTL)

    # ── causality ─────────────────────────────

    async def get_causes(self, session_id: str) -> list[str]:
        if not session_id:
            return []
        data = await self.cache.get_json(f"pad_causes:{session_id}")
        return list(data) if isinstance(data, list) else []

    async def push_cause(self, session_id: str, cause: str | None) -> list[str]:
        """Remember why the mood is what it is (last N, newest last)."""
        cause = (cause or "").strip()
        if not session_id or not cause:
            return await self.get_causes(session_id)
        causes = await self.get_causes(session_id)
        if causes and causes[-1] == cause:
            return causes
        causes = (causes + [cause[:80]])[-_MAX_CAUSES:]
        await self.cache.set_json(f"pad_causes:{session_id}", causes, ttl=_CAUSES_TTL)
        return causes

    async def get_baseline(self, session_id: str) -> PADState | None:
        """Get cached personality baseline for this session."""
        data = await self.cache.get_json(f"pad_baseline:{session_id}")
        if data:
            return PADState.from_dict(data)
        return None

    async def set_baseline(self, session_id: str, baseline: PADState) -> None:
        await self.cache.set_json(
            f"pad_baseline:{session_id}", baseline.to_dict(), ttl=_BASELINE_TTL
        )

    async def update(
        self,
        session_id: str,
        text_emotion: str | None = None,
        touch_gesture: str | None = None,
        user_mood: str | None = None,
        personality: dict | None = None,
        relationship_stage: str | None = None,
        cause: str | None = None,
    ) -> tuple[PADState, str]:
        """Update PAD state with full context.

        Args:
            session_id: Session ID for state persistence.
            text_emotion: Discrete emotion detected from LLM text.
            touch_gesture: Touch gesture name.
            user_mood: Detected user mood.
            personality: Character's 5-trait personality dict (for baseline).
            relationship_stage: STRANGER→BESTFRIEND (scales touch/empathy weights).
        """
        current = await self.get_pad(session_id)

        # Get or compute personality baseline
        baseline = await self.get_baseline(session_id)
        if baseline is None and personality:
            baseline = personality_to_baseline(personality)
            await self.set_baseline(session_id, baseline)

        # Convert inputs
        text_target = emotion_to_pad(text_emotion) if text_emotion else None
        touch_impulse = TOUCH_PAD_IMPULSE.get(touch_gesture) if touch_gesture else None
        mood_pad = USER_MOOD_PAD.get(user_mood) if user_mood and user_mood != "neutral" else None

        # Transition
        new_state = transition_pad(
            current=current,
            text_target=text_target,
            touch_impulse=touch_impulse,
            user_mood_pad=mood_pad,
            baseline=baseline,
            relationship_stage=relationship_stage,
        )

        await self.set_pad(session_id, new_state)
        if cause:
            await self.push_cause(session_id, cause)
        discrete = pad_to_emotion(new_state)

        logger.debug(
            "pad.updated",
            session_id=session_id,
            pad=new_state.to_dict(),
            emotion=discrete,
            baseline=baseline.to_dict() if baseline else None,
            relationship=relationship_stage,
            inputs={"text": text_emotion, "touch": touch_gesture, "mood": user_mood},
        )

        return new_state, discrete

    async def apply_touch_only(
        self,
        session_id: str,
        touch_gesture: str,
    ) -> tuple[PADState, str]:
        return await self.update(session_id=session_id, touch_gesture=touch_gesture)

    def get_tts_offsets(self, state: PADState) -> dict[str, float]:
        return pad_to_tts_offsets(state)

    def get_prompt_description(self, state: PADState) -> str:
        return pad_to_prompt_description(state)
