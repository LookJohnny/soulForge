"""PAD Emotion Model — continuous 3D emotional space underlying discrete emotions.

PAD dimensions (each -1.0 to 1.0):
  P (Pleasure)  — happy ↔ unhappy
  A (Arousal)   — excited ↔ calm
  D (Dominance) — dominant ↔ submissive

This module provides:
1. PAD anchor points for each discrete emotion
2. Smooth PAD state transitions with inertia and decay
3. Multi-modal fusion (text + touch → blended PAD)
4. PAD → nearest discrete emotion mapping
5. PAD → TTS parameter computation (more nuanced than per-emotion lookup)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict

import structlog

from ai_core.services.cache import CacheService

logger = structlog.get_logger()


# ──────────────────────────────────────────────
# PAD State
# ──────────────────────────────────────────────

@dataclass
class PADState:
    """3D emotion point in PAD space."""
    p: float = 0.0  # Pleasure:  -1 (unhappy) → +1 (happy)
    a: float = 0.0  # Arousal:   -1 (calm)    → +1 (excited)
    d: float = 0.0  # Dominance: -1 (submissive) → +1 (dominant)

    def clamp(self) -> PADState:
        """Clamp all values to [-1, 1]."""
        self.p = max(-1.0, min(1.0, self.p))
        self.a = max(-1.0, min(1.0, self.a))
        self.d = max(-1.0, min(1.0, self.d))
        return self

    def distance_to(self, other: PADState) -> float:
        """Euclidean distance to another PAD point."""
        return math.sqrt(
            (self.p - other.p) ** 2
            + (self.a - other.a) ** 2
            + (self.d - other.d) ** 2
        )

    def lerp(self, target: PADState, alpha: float) -> PADState:
        """Linear interpolation toward target. alpha=0 → self, alpha=1 → target."""
        alpha = max(0.0, min(1.0, alpha))
        return PADState(
            p=self.p + alpha * (target.p - self.p),
            a=self.a + alpha * (target.a - self.a),
            d=self.d + alpha * (target.d - self.d),
        ).clamp()

    def to_dict(self) -> dict:
        return {"p": round(self.p, 3), "a": round(self.a, 3), "d": round(self.d, 3)}

    @classmethod
    def from_dict(cls, d: dict) -> PADState:
        return cls(p=d.get("p", 0.0), a=d.get("a", 0.0), d=d.get("d", 0.0))

    @classmethod
    def neutral(cls) -> PADState:
        return cls(0.0, -0.2, 0.0)  # slightly calm, not dead-center


# ──────────────────────────────────────────────
# Emotion ↔ PAD anchor mapping
# ──────────────────────────────────────────────

# Based on Mehrabian's PAD model with adjustments for plush toy context
EMOTION_PAD_ANCHORS: dict[str, PADState] = {
    "happy":    PADState(p=0.8,  a=0.3,  d=0.4),   # lower arousal to separate from playful
    "sad":      PADState(p=-0.7, a=-0.4, d=-0.5),
    "shy":      PADState(p=0.2,  a=-0.2, d=-0.6),
    "angry":    PADState(p=-0.6, a=0.7,  d=0.5),
    "playful":  PADState(p=0.5,  a=0.8,  d=0.1),   # lower pleasure, higher arousal, lower dominance
    "curious":  PADState(p=0.4,  a=0.3,  d=0.1),
    "worried":  PADState(p=-0.3, a=0.2,  d=-0.4),
    "calm":     PADState(p=0.1,  a=-0.5, d=0.0),
}

# Touch gesture → PAD impulse (additive delta, not absolute position)
TOUCH_PAD_IMPULSE: dict[str, PADState] = {
    "pat":     PADState(p=0.3,  a=0.1,  d=0.1),
    "stroke":  PADState(p=0.3,  a=-0.2, d=0.0),
    "hug":     PADState(p=-0.1, a=0.2,  d=-0.3),   # concern for user
    "squeeze": PADState(p=-0.2, a=0.3,  d=-0.2),
    "poke":    PADState(p=0.2,  a=0.4,  d=0.1),
    "hold":    PADState(p=0.2,  a=-0.3, d=0.0),
    "shake":   PADState(p=0.2,  a=0.5,  d=0.1),
    "none":    PADState(p=0.0,  a=0.0,  d=0.0),
}

# User mood → PAD interpretation (what the character "reads" from user)
USER_MOOD_PAD: dict[str, PADState] = {
    "happy":   PADState(p=0.6,  a=0.4,  d=0.3),
    "sad":     PADState(p=-0.5, a=-0.2, d=-0.4),
    "angry":   PADState(p=-0.5, a=0.6,  d=0.4),
    "worried": PADState(p=-0.3, a=0.3,  d=-0.3),
    "excited": PADState(p=0.6,  a=0.7,  d=0.3),
    "tired":   PADState(p=-0.1, a=-0.6, d=-0.2),
    "lonely":  PADState(p=-0.4, a=-0.3, d=-0.5),
    "neutral": PADState(p=0.0,  a=0.0,  d=0.0),
}


def pad_to_emotion(state: PADState) -> str:
    """Map a PAD state to the nearest discrete emotion label."""
    best_emotion = "calm"
    best_dist = float("inf")
    for emotion, anchor in EMOTION_PAD_ANCHORS.items():
        dist = state.distance_to(anchor)
        if dist < best_dist:
            best_dist = dist
            best_emotion = emotion
    return best_emotion


def emotion_to_pad(emotion: str) -> PADState:
    """Get the PAD anchor for a discrete emotion."""
    anchor = EMOTION_PAD_ANCHORS.get(emotion)
    if anchor:
        return PADState(p=anchor.p, a=anchor.a, d=anchor.d)
    return PADState.neutral()


# ──────────────────────────────────────────────
# Transition dynamics
# ──────────────────────────────────────────────

# How fast PAD transitions toward a new target (0 = no change, 1 = instant)
TRANSITION_SPEED = 0.4

# How fast PAD decays toward neutral when no input (per turn)
DECAY_RATE = 0.15

# Touch impulse strength multiplier
TOUCH_IMPULSE_STRENGTH = 0.5

# User mood influence on character (empathetic mirroring)
MOOD_EMPATHY_WEIGHT = 0.2


def transition_pad(
    current: PADState,
    text_target: PADState | None = None,
    touch_impulse: PADState | None = None,
    user_mood_pad: PADState | None = None,
) -> PADState:
    """Compute the next PAD state by blending multiple input signals.

    The update follows:
      1. Decay current state slightly toward neutral
      2. Blend toward text-detected emotion target (strongest signal)
      3. Add touch impulse (additive, scaled)
      4. Add empathetic response to user mood (weak influence)
      5. Clamp result to [-1, 1]

    Args:
        current: Current PAD state.
        text_target: PAD anchor of LLM-detected emotion (strongest signal).
        touch_impulse: PAD delta from touch gesture.
        user_mood_pad: PAD interpretation of detected user mood.

    Returns:
        New PAD state after transition.
    """
    neutral = PADState.neutral()

    # Step 1: Decay toward neutral
    result = current.lerp(neutral, DECAY_RATE)

    # Step 2: Blend toward text target (primary signal)
    if text_target:
        result = result.lerp(text_target, TRANSITION_SPEED)

    # Step 3: Add touch impulse with diminishing returns near extremes
    if touch_impulse:
        # Impulse weakens as PAD approaches ±1 (logistic-style saturation)
        def _dampen(current: float, delta: float) -> float:
            headroom = 1.0 - abs(current)  # 0 at extremes, 1 at center
            damping = max(0.1, headroom)  # at least 10% of impulse gets through
            return delta * TOUCH_IMPULSE_STRENGTH * damping

        result.p += _dampen(result.p, touch_impulse.p)
        result.a += _dampen(result.a, touch_impulse.a)
        result.d += _dampen(result.d, touch_impulse.d)

    # Step 4: Empathetic mirroring of user mood
    if user_mood_pad:
        # Character mirrors user mood slightly (empathy)
        # High P from user → character gets happier; low P → character gets concerned
        result.p += user_mood_pad.p * MOOD_EMPATHY_WEIGHT
        # Mirror arousal lightly
        result.a += user_mood_pad.a * MOOD_EMPATHY_WEIGHT * 0.5

    return result.clamp()


# ──────────────────────────────────────────────
# PAD → TTS parameter computation
# ──────────────────────────────────────────────

def pad_to_tts_offsets(state: PADState) -> dict[str, float]:
    """Compute TTS pitch/rate offsets directly from PAD values.

    More nuanced than discrete emotion lookup:
    - Pleasure → pitch (happy = higher pitch)
    - Arousal → rate (excited = faster) + pitch boost
    - Dominance → rate reduction when submissive (quieter/slower)
    """
    pitch_offset = state.p * 0.06 + state.a * 0.04
    rate_offset = state.a * 0.05 + state.d * 0.02

    # Clamp offsets to reasonable range
    pitch_offset = max(-0.12, min(0.12, pitch_offset))
    rate_offset = max(-0.12, min(0.12, rate_offset))

    return {
        "pitch_offset": round(pitch_offset, 4),
        "rate_offset": round(rate_offset, 4),
    }


# ──────────────────────────────────────────────
# PAD → Prompt description
# ──────────────────────────────────────────────

def pad_to_prompt_description(state: PADState) -> str:
    """Generate a nuanced Chinese emotion description from PAD values.

    Instead of fixed per-emotion descriptions, this generates blended text
    that captures the subtle emotional state.
    """
    parts = []

    # Pleasure axis
    if state.p > 0.5:
        parts.append("你现在心情很好，语气轻快愉悦")
    elif state.p > 0.2:
        parts.append("你现在心情不错")
    elif state.p < -0.5:
        parts.append("你现在心情低落")
    elif state.p < -0.2:
        parts.append("你现在心情有点沉重")

    # Arousal axis
    if state.a > 0.5:
        parts.append("精力充沛，很活跃")
    elif state.a > 0.2:
        parts.append("有些兴奋")
    elif state.a < -0.5:
        parts.append("很安静平和，语速偏慢")
    elif state.a < -0.2:
        parts.append("比较平静")

    # Dominance axis
    if state.d < -0.4:
        parts.append("有点小心翼翼，声音轻轻的")
    elif state.d > 0.4:
        parts.append("比较有主见")

    if not parts:
        return "你现在很平静，语气沉稳温和"

    return "，".join(parts)


# ──────────────────────────────────────────────
# PAD Engine (with persistence)
# ──────────────────────────────────────────────

_PAD_TTL = 1800  # 30 min, same as emotion TTL


class PADEngine:
    """Manage PAD emotional state with persistence and multi-modal fusion."""

    def __init__(self, cache: CacheService):
        self.cache = cache

    async def get_pad(self, session_id: str) -> PADState:
        """Load PAD state from cache, or return neutral."""
        if not session_id:
            return PADState.neutral()
        data = await self.cache.get_json(f"pad:{session_id}")
        if data:
            return PADState.from_dict(data)
        return PADState.neutral()

    async def set_pad(self, session_id: str, state: PADState) -> None:
        """Persist PAD state to cache."""
        if not session_id:
            return
        await self.cache.set_json(f"pad:{session_id}", state.to_dict(), ttl=_PAD_TTL)

    async def update(
        self,
        session_id: str,
        text_emotion: str | None = None,
        touch_gesture: str | None = None,
        user_mood: str | None = None,
    ) -> tuple[PADState, str]:
        """Update PAD state from multi-modal inputs and return (new_pad, discrete_emotion).

        This is the main entry point for the pipeline. It:
        1. Loads current PAD state
        2. Converts inputs to PAD signals
        3. Blends them via transition_pad()
        4. Persists the new state
        5. Returns both PAD state and nearest discrete emotion

        Args:
            session_id: Session ID for state persistence.
            text_emotion: Discrete emotion detected from LLM text (e.g. "happy").
            touch_gesture: Touch gesture name (e.g. "hug").
            user_mood: Detected user mood (e.g. "sad").

        Returns:
            (new_pad_state, discrete_emotion_label)
        """
        current = await self.get_pad(session_id)

        # Convert inputs to PAD signals
        text_target = emotion_to_pad(text_emotion) if text_emotion else None
        touch_impulse = TOUCH_PAD_IMPULSE.get(touch_gesture) if touch_gesture else None
        mood_pad = USER_MOOD_PAD.get(user_mood) if user_mood and user_mood != "neutral" else None

        # Compute transition
        new_state = transition_pad(
            current=current,
            text_target=text_target,
            touch_impulse=touch_impulse,
            user_mood_pad=mood_pad,
        )

        # Persist
        await self.set_pad(session_id, new_state)

        # Map to discrete emotion
        discrete = pad_to_emotion(new_state)

        logger.debug(
            "pad.updated",
            session_id=session_id,
            pad=new_state.to_dict(),
            emotion=discrete,
            inputs={"text": text_emotion, "touch": touch_gesture, "mood": user_mood},
        )

        return new_state, discrete

    async def apply_touch_only(
        self,
        session_id: str,
        touch_gesture: str,
    ) -> tuple[PADState, str]:
        """Apply touch impulse without text signal (for touch-only events)."""
        return await self.update(
            session_id=session_id,
            touch_gesture=touch_gesture,
        )

    def get_tts_offsets(self, state: PADState) -> dict[str, float]:
        """Get TTS offsets from PAD state."""
        return pad_to_tts_offsets(state)

    def get_prompt_description(self, state: PADState) -> str:
        """Get emotion description for system prompt from PAD state."""
        return pad_to_prompt_description(state)
