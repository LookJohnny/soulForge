"""Ambient Behaviors — continuous background animations that make the toy feel alive.

Ref: Olaf paper Sec. VII-C, background animations layer.

Each behavior outputs channel *offsets* (not absolute values), so multiple
behaviors can stack without conflict. The AmbientBehaviorComposer sums them.

Key behaviors:
  - Breathing: asymmetric sine wave (inhale fast, exhale slow)
  - Eye saccades: Poisson-triggered micro-jumps (Olaf Sec. VII-C)
  - Idle shift: Perlin-like low-frequency body drift
  - Micro expressions: random subtle facial twitches
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod


class AmbientBehavior(ABC):
    """Base class for ambient behaviors. All output offsets, not absolutes."""

    @abstractmethod
    def sample(self, t: float, dt: float) -> dict[str, float]:
        """Sample current offset values.

        Args:
            t: global time (seconds)
            dt: frame interval (seconds)
        Returns:
            {channel_id: offset_value}
        """
        ...


class BreathingBehavior(AmbientBehavior):
    """Simulates breathing with asymmetric waveform.

    Inhale is faster than exhale (more natural). Uses power-sine:
        offset = A * |sin(2π·f·t)|^p * sign(sin(2π·f·t))
    where p > 1 makes exhale longer than inhale.

    Affects: body_pitch (slight forward/back lean)
    """

    def __init__(self, rate_bpm: float = 15.0, amplitude: float = 0.03,
                 asymmetry: float = 1.3):
        self.frequency = rate_bpm / 60.0  # Hz
        self.amplitude = amplitude
        self.asymmetry = asymmetry  # p > 1 → exhale slower

    def sample(self, t: float, dt: float) -> dict[str, float]:
        phase = 2.0 * math.pi * self.frequency * t
        raw = math.sin(phase)
        # Asymmetric: positive half (inhale) is sharper, negative (exhale) is broader
        if raw >= 0:
            val = raw ** (1.0 / self.asymmetry)
        else:
            val = -((-raw) ** self.asymmetry)
        offset = self.amplitude * val
        return {"body_pitch": offset}


class EyeSaccadeBehavior(AmbientBehavior):
    """Random eye micro-saccades.

    Ref: Olaf Sec. VII-C eye saccades.

    Human eye saccade characteristics:
      - Frequency: 2-3 per second
      - Amplitude: 1-5 degrees
      - Duration: 20-50ms jump + 200-600ms fixation
      - Horizontal bias

    Uses Poisson process for timing, Gaussian for amplitude.

    Affects: eye_yaw, eye_pitch
    """

    def __init__(self, frequency_hz: float = 2.5, max_amplitude_deg: float = 4.0):
        self.frequency = frequency_hz
        self.max_amp = max_amplitude_deg
        self._current_yaw = 0.0
        self._current_pitch = 0.0
        self._target_yaw = 0.0
        self._target_pitch = 0.0
        self._time_to_next = 0.0
        self._transition_progress = 1.0  # 1.0 = settled
        self._transition_duration = 0.04  # 40ms saccade

    def sample(self, t: float, dt: float) -> dict[str, float]:
        self._time_to_next -= dt

        if self._time_to_next <= 0:
            # Poisson inter-arrival: exponential distribution
            interval = random.expovariate(self.frequency)
            self._time_to_next = max(0.1, interval)

            # New target (Gaussian, horizontal bias)
            self._target_yaw = random.gauss(0, self.max_amp * 0.6)
            self._target_pitch = random.gauss(0, self.max_amp * 0.3)
            self._transition_progress = 0.0
            self._transition_duration = random.uniform(0.02, 0.05)

        # Smooth transition to target
        if self._transition_progress < 1.0:
            self._transition_progress = min(1.0, self._transition_progress + dt / self._transition_duration)
            alpha = self._transition_progress
            self._current_yaw += (self._target_yaw - self._current_yaw) * alpha
            self._current_pitch += (self._target_pitch - self._current_pitch) * alpha

        return {
            "eye_yaw": self._current_yaw,
            "eye_pitch": self._current_pitch,
        }


class IdleShiftBehavior(AmbientBehavior):
    """Occasional body weight shifts.

    Humans shift weight every 5-15 seconds when standing.
    Uses layered sine waves at incommensurate frequencies for
    natural non-repeating drift (pseudo Perlin noise).

    Affects: body_yaw, body_roll, head_yaw
    """

    def __init__(self, amplitude: float = 0.02):
        self.amplitude = amplitude
        # Incommensurate frequencies for non-repeating pattern
        self._freqs = [0.07, 0.11, 0.17, 0.23]  # Hz
        self._phases = [random.uniform(0, 2 * math.pi) for _ in range(4)]

    def sample(self, t: float, dt: float) -> dict[str, float]:
        # Sum of sines at different frequencies → pseudo-random drift
        body_yaw = sum(
            math.sin(2 * math.pi * f * t + p) for f, p in zip(self._freqs[:2], self._phases[:2])
        ) * self.amplitude * 0.5

        body_roll = sum(
            math.sin(2 * math.pi * f * t + p) for f, p in zip(self._freqs[1:3], self._phases[1:3])
        ) * self.amplitude * 0.3

        head_yaw = sum(
            math.sin(2 * math.pi * f * t + p) for f, p in zip(self._freqs[2:], self._phases[2:])
        ) * self.amplitude * 0.4

        return {
            "body_yaw": body_yaw,
            "body_roll": body_roll,
            "head_yaw": head_yaw,
        }


class MicroExpressionBehavior(AmbientBehavior):
    """Random micro-expressions: subtle facial twitches.

    Low frequency, small amplitude, but significant for believability.
    Prevents the "frozen face" effect.

    Affects: eyebrow_raise, mouth_corner, eyelid
    """

    def __init__(self, trigger_probability_per_sec: float = 0.15):
        self.trigger_prob = trigger_probability_per_sec
        self._active_channel: str | None = None
        self._active_value = 0.0
        self._decay_rate = 3.0  # per second

    def sample(self, t: float, dt: float) -> dict[str, float]:
        channels = {"eyebrow_raise": 0.0, "mouth_corner": 0.0, "eyelid": 0.0}

        # Decay active expression
        if self._active_channel:
            self._active_value *= max(0, 1.0 - self._decay_rate * dt)
            if abs(self._active_value) < 0.001:
                self._active_channel = None
            else:
                channels[self._active_channel] = self._active_value

        # Random trigger
        if random.random() < self.trigger_prob * dt:
            self._active_channel = random.choice(list(channels.keys()))
            self._active_value = random.gauss(0, 0.15)
            self._active_value = max(-0.3, min(0.3, self._active_value))

        return channels


# ── Emotion-aware parameter modulation ────────────

# Maps emotion type (int) to parameter multipliers
_EMOTION_MODIFIERS: dict[int, dict[str, float]] = {
    0:  {"breathing_rate": 1.0, "saccade_freq": 1.0, "shift_amp": 1.0, "micro_prob": 1.0},  # NEUTRAL
    1:  {"breathing_rate": 1.3, "saccade_freq": 1.2, "shift_amp": 1.4, "micro_prob": 1.5},  # JOY
    2:  {"breathing_rate": 0.7, "saccade_freq": 0.6, "shift_amp": 0.5, "micro_prob": 0.7},  # SADNESS
    3:  {"breathing_rate": 1.5, "saccade_freq": 1.8, "shift_amp": 1.2, "micro_prob": 1.8},  # SURPRISE
    4:  {"breathing_rate": 1.4, "saccade_freq": 1.5, "shift_amp": 1.3, "micro_prob": 0.5},  # ANGER
    5:  {"breathing_rate": 1.6, "saccade_freq": 2.0, "shift_amp": 0.8, "micro_prob": 1.2},  # FEAR
    7:  {"breathing_rate": 1.1, "saccade_freq": 1.4, "shift_amp": 1.1, "micro_prob": 1.3},  # CURIOSITY
    8:  {"breathing_rate": 0.9, "saccade_freq": 0.8, "shift_amp": 0.6, "micro_prob": 1.0},  # AFFECTION
    9:  {"breathing_rate": 0.5, "saccade_freq": 0.3, "shift_amp": 0.3, "micro_prob": 0.4},  # SLEEPY
    10: {"breathing_rate": 1.5, "saccade_freq": 1.6, "shift_amp": 1.5, "micro_prob": 1.6},  # EXCITED
}


class AmbientBehaviorComposer:
    """Combines multiple ambient behaviors, stacks their offsets.

    Supports emotion-based parameter adjustment:
      JOY → faster breathing, more micro-expressions
      SADNESS → slower breathing, less movement
      SLEEPY → everything slows down
    """

    def __init__(self, behaviors: list[AmbientBehavior] | None = None):
        if behaviors is None:
            behaviors = [
                BreathingBehavior(),
                EyeSaccadeBehavior(),
                IdleShiftBehavior(),
                MicroExpressionBehavior(),
            ]
        self.behaviors = behaviors
        self._base_params: dict[str, float] = {}
        # Store original params for emotion modulation
        for b in behaviors:
            if isinstance(b, BreathingBehavior):
                self._base_params["breathing_freq"] = b.frequency
            elif isinstance(b, EyeSaccadeBehavior):
                self._base_params["saccade_freq"] = b.frequency
            elif isinstance(b, IdleShiftBehavior):
                self._base_params["shift_amp"] = b.amplitude
            elif isinstance(b, MicroExpressionBehavior):
                self._base_params["micro_prob"] = b.trigger_prob

    def set_emotional_context(self, emotion_type: int, intensity: float = 1.0):
        """Adjust all behavior parameters based on current emotion."""
        mods = _EMOTION_MODIFIERS.get(emotion_type, _EMOTION_MODIFIERS[0])
        intensity = max(0.0, min(1.0, intensity))

        for b in self.behaviors:
            if isinstance(b, BreathingBehavior):
                base = self._base_params.get("breathing_freq", 0.25)
                mod = 1.0 + (mods["breathing_rate"] - 1.0) * intensity
                b.frequency = base * mod
            elif isinstance(b, EyeSaccadeBehavior):
                base = self._base_params.get("saccade_freq", 2.5)
                mod = 1.0 + (mods["saccade_freq"] - 1.0) * intensity
                b.frequency = base * mod
            elif isinstance(b, IdleShiftBehavior):
                base = self._base_params.get("shift_amp", 0.02)
                mod = 1.0 + (mods["shift_amp"] - 1.0) * intensity
                b.amplitude = base * mod
            elif isinstance(b, MicroExpressionBehavior):
                base = self._base_params.get("micro_prob", 0.15)
                mod = 1.0 + (mods["micro_prob"] - 1.0) * intensity
                b.trigger_prob = base * mod

    def sample_all(self, t: float, dt: float) -> dict[str, float]:
        """Sample and stack all behavior outputs."""
        combined: dict[str, float] = {}
        for b in self.behaviors:
            for ch, val in b.sample(t, dt).items():
                combined[ch] = combined.get(ch, 0.0) + val
        return combined
