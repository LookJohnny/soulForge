"""PAD emotion math — pure, dependency-free (moved from ai-core pad_model).

PAD dimensions (each -1.0..1.0): P pleasure, A arousal, D dominance.
Baselines derive from the five numeric personality traits; anchors map discrete
emotions / touch gestures / user moods into PAD space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ──────────────────────────────────────────────
# PAD State
# ──────────────────────────────────────────────


@dataclass
class PADState:
    """3D emotion point in PAD space."""

    p: float = 0.0
    a: float = 0.0
    d: float = 0.0

    def clamp(self) -> PADState:
        self.p = max(-1.0, min(1.0, self.p))
        self.a = max(-1.0, min(1.0, self.a))
        self.d = max(-1.0, min(1.0, self.d))
        return self

    def distance_to(self, other: PADState) -> float:
        return math.sqrt(
            (self.p - other.p) ** 2 + (self.a - other.a) ** 2 + (self.d - other.d) ** 2
        )

    def magnitude(self) -> float:
        """Distance from origin — how "intense" the emotion is."""
        return math.sqrt(self.p**2 + self.a**2 + self.d**2)

    def lerp(self, target: PADState, alpha: float) -> PADState:
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
        return cls(0.0, -0.2, 0.0)


# ──────────────────────────────────────────────
# [NEW] Personality → PAD baseline
# ──────────────────────────────────────────────


def personality_to_baseline(personality: dict | None) -> PADState:
    """Convert 5-trait personality to a PAD baseline that the character "rests" at.

    A cheerful character (high warmth+energy) naturally rests at positive P/A.
    A shy character (low extrovert) rests at negative A/D.
    """
    if not personality:
        return PADState.neutral()

    warmth = personality.get("warmth", 50)
    energy = personality.get("energy", 50)
    extrovert = personality.get("extrovert", 50)
    humor = personality.get("humor", 50)

    # Map traits to PAD baseline (trait 50 → 0, trait 100 → offset)
    p = (warmth - 50) * 0.006 + (humor - 50) * 0.003  # warmth/humor → positive pleasure
    a = (energy - 50) * 0.006 + (
        extrovert - 50
    ) * 0.004  # energy/extrovert → higher arousal
    d = (extrovert - 50) * 0.004 - (
        warmth - 50
    ) * 0.002  # extrovert → dominant, warmth → submissive

    return PADState(p=p, a=a, d=d).clamp()


# ──────────────────────────────────────────────
# Emotion ↔ PAD anchor mapping
# ──────────────────────────────────────────────

EMOTION_PAD_ANCHORS: dict[str, PADState] = {
    "happy": PADState(p=0.8, a=0.3, d=0.4),
    "sad": PADState(p=-0.7, a=-0.4, d=-0.5),
    "shy": PADState(p=0.2, a=-0.2, d=-0.6),
    "angry": PADState(p=-0.6, a=0.7, d=0.5),
    "playful": PADState(p=0.5, a=0.8, d=0.1),
    "curious": PADState(p=0.4, a=0.3, d=0.1),
    "worried": PADState(p=-0.3, a=0.2, d=-0.4),
    "calm": PADState(p=0.1, a=-0.5, d=0.0),
}

TOUCH_PAD_IMPULSE: dict[str, PADState] = {
    "pat": PADState(p=0.3, a=0.1, d=0.1),
    "stroke": PADState(p=0.3, a=-0.2, d=0.0),
    "hug": PADState(p=-0.1, a=0.2, d=-0.3),
    "squeeze": PADState(p=-0.2, a=0.3, d=-0.2),
    "poke": PADState(p=0.2, a=0.4, d=0.1),
    "hold": PADState(p=0.2, a=-0.3, d=0.0),
    "shake": PADState(p=0.2, a=0.5, d=0.1),
    "none": PADState(p=0.0, a=0.0, d=0.0),
}

USER_MOOD_PAD: dict[str, PADState] = {
    "happy": PADState(p=0.6, a=0.4, d=0.3),
    "sad": PADState(p=-0.5, a=-0.2, d=-0.4),
    "angry": PADState(p=-0.5, a=0.6, d=0.4),
    "worried": PADState(p=-0.3, a=0.3, d=-0.3),
    "excited": PADState(p=0.6, a=0.7, d=0.3),
    "tired": PADState(p=-0.1, a=-0.6, d=-0.2),
    "lonely": PADState(p=-0.4, a=-0.3, d=-0.5),
    "neutral": PADState(p=0.0, a=0.0, d=0.0),
}

# ──────────────────────────────────────────────
# [NEW] Relationship stage → weight multipliers
# ──────────────────────────────────────────────

RELATIONSHIP_WEIGHTS: dict[str, dict[str, float]] = {
    "COMPANION": {"touch": 0.6, "empathy": 0.25, "transition": 0.4},
    "STRANGER": {"touch": 0.3, "empathy": 0.1, "transition": 0.3},
    "ACQUAINTANCE": {"touch": 0.5, "empathy": 0.15, "transition": 0.35},
    "FAMILIAR": {
        "touch": 0.7,
        "empathy": 0.2,
        "transition": 0.4,
    },  # legacy alias of FRIEND
    "FRIEND": {"touch": 0.8, "empathy": 0.25, "transition": 0.42},
    "BESTFRIEND": {"touch": 1.0, "empathy": 0.35, "transition": 0.47},  # legacy alias
    "CLOSE_FRIEND": {"touch": 1.0, "empathy": 0.35, "transition": 0.47},
    "ROMANTIC_INTEREST": {"touch": 1.1, "empathy": 0.4, "transition": 0.5},
    "DATING": {"touch": 1.2, "empathy": 0.45, "transition": 0.52},
    "COMMITTED": {"touch": 1.3, "empathy": 0.5, "transition": 0.55},
    "SOULMATE": {"touch": 1.4, "empathy": 0.55, "transition": 0.6},
}

_DEFAULT_REL_WEIGHTS = {"touch": 0.5, "empathy": 0.2, "transition": 0.4}


def pad_to_emotion(state: PADState) -> str:
    best_emotion = "calm"
    best_dist = float("inf")
    for emotion, anchor in EMOTION_PAD_ANCHORS.items():
        dist = state.distance_to(anchor)
        if dist < best_dist:
            best_dist = dist
            best_emotion = emotion
    return best_emotion


def emotion_to_pad(emotion: str) -> PADState:
    anchor = EMOTION_PAD_ANCHORS.get(emotion)
    if anchor:
        return PADState(p=anchor.p, a=anchor.a, d=anchor.d)
    return PADState.neutral()


# ──────────────────────────────────────────────
# Transition dynamics (v2)
# ──────────────────────────────────────────────

# Base rates (modified by relationship + inertia)
BASE_TRANSITION_SPEED = 0.4
BASE_DECAY_RATE = 0.12
BASE_TOUCH_STRENGTH = 0.5
BASE_EMPATHY_WEIGHT = 0.2


def transition_pad(
    current: PADState,
    text_target: PADState | None = None,
    touch_impulse: PADState | None = None,
    user_mood_pad: PADState | None = None,
    baseline: PADState | None = None,
    relationship_stage: str | None = None,
) -> PADState:
    """Compute the next PAD state with personality-aware dynamics.

    v2 improvements:
    1. Decay toward personality baseline (not fixed neutral)
    2. Emotional inertia — strong emotions resist change
    3. Diminishing touch impulse near extremes
    4. Relationship-scaled weights
    """
    # Use personality baseline or default neutral
    rest_point = baseline or PADState.neutral()

    # Get relationship-adjusted weights
    rw = RELATIONSHIP_WEIGHTS.get(relationship_stage or "", _DEFAULT_REL_WEIGHTS)
    transition_speed = rw["transition"]
    touch_strength = rw["touch"]
    empathy_weight = rw["empathy"]

    # ── Step 1: Non-linear decay toward baseline ──
    # Strong emotions decay slower (inertia = magnitude * 0.3)
    intensity = current.magnitude()
    inertia = min(0.3, intensity * 0.2)  # max 30% resistance
    effective_decay = BASE_DECAY_RATE * (1.0 - inertia)
    result = current.lerp(rest_point, effective_decay)

    # ── Step 2: Text emotion target ──
    if text_target:
        # Emotional inertia: if current emotion is far from target and strong,
        # transition is slower (harder to shift a strong emotion)
        distance = current.distance_to(text_target)
        # Close emotions (distance < 0.5) transition faster
        # Distant emotions (distance > 1.0) transition slower
        speed_modifier = 1.0 / (1.0 + distance * 0.3)
        effective_speed = transition_speed * speed_modifier

        # But if current emotion is weak (near baseline), accept new emotion faster
        if intensity < 0.3:
            effective_speed = min(1.0, effective_speed * 1.5)

        result = result.lerp(text_target, effective_speed)

    # ── Step 3: Touch impulse (diminishing + relationship-scaled) ──
    if touch_impulse:

        def _dampen(val: float, delta: float) -> float:
            headroom = 1.0 - abs(val)
            damping = max(0.1, headroom)
            return delta * touch_strength * damping

        result.p += _dampen(result.p, touch_impulse.p)
        result.a += _dampen(result.a, touch_impulse.a)
        result.d += _dampen(result.d, touch_impulse.d)

    # ── Step 4: User mood empathy (relationship-scaled) ──
    if user_mood_pad:
        result.p += user_mood_pad.p * empathy_weight
        result.a += user_mood_pad.a * empathy_weight * 0.5

    return result.clamp()


# ──────────────────────────────────────────────
# PAD → TTS parameter computation
# ──────────────────────────────────────────────


def pad_to_tts_offsets(state: PADState) -> dict[str, float]:
    pitch_offset = state.p * 0.06 + state.a * 0.04
    rate_offset = state.a * 0.05 + state.d * 0.02
    pitch_offset = max(-0.12, min(0.12, pitch_offset))
    rate_offset = max(-0.12, min(0.12, rate_offset))
    return {
        "pitch_offset": round(pitch_offset, 4),
        "rate_offset": round(rate_offset, 4),
    }


# ──────────────────────────────────────────────
# PAD → Prompt description (v2 — more granular)
# ──────────────────────────────────────────────


def pad_to_prompt_description(state: PADState) -> str:
    """Generate nuanced emotion description from PAD values."""
    parts = []

    # Pleasure — 5 levels instead of 4
    if state.p > 0.6:
        parts.append("你现在非常开心，语气轻快愉悦，忍不住想笑")
    elif state.p > 0.3:
        parts.append("你现在心情不错，语气温暖愉快")
    elif state.p > -0.3:
        pass  # neutral — say nothing about pleasure
    elif state.p > -0.6:
        parts.append("你现在心情有点低落，语气柔和沉静")
    else:
        parts.append("你现在很难过，声音低沉，语速放慢")

    # Arousal
    if state.a > 0.5:
        parts.append("精力充沛，说话有活力")
    elif state.a > 0.2:
        parts.append("有些兴奋")
    elif state.a < -0.5:
        parts.append("很安静，语速偏慢")
    elif state.a < -0.2:
        parts.append("比较平静放松")

    # Dominance
    if state.d < -0.4:
        parts.append("有点小心翼翼，声音轻轻的")
    elif state.d > 0.4:
        parts.append("比较有主见和自信")

    if not parts:
        return "你现在很平静，语气沉稳温和"

    return "，".join(parts)


# ──────────────────────────────────────────────
# PAD Engine (v2)
# ──────────────────────────────────────────────

_PAD_TTL = 1800
# Mood causality ring ("why am I feeling this") — last N reasons, same TTL as PAD.
_CAUSES_TTL = 1800
_MAX_CAUSES = 5
# Wall-clock decay: PAD stored with a timestamp; on read, hours elapsed pull the
# state toward the personality baseline (turn-driven decay alone never runs
# while the user is away).
_WALL_DECAY_PER_HOUR = 0.15

# Cache key for personality baseline
_BASELINE_TTL = 3600
