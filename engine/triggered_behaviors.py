"""Triggered Behaviors — finite-duration actions with ADSR lifecycle.

Ref: Olaf paper Sec. VII-C, triggered animations layer.

Each behavior has an Attack-Sustain-Release envelope:
  Attack:  ramp from zero to peak (configurable easing)
  Sustain: hold at peak (can loop keyframes)
  Release: smooth fade back to zero

Behaviors are defined as JSON/dict configs with keyframe animations
per channel. A BehaviorScheduler manages priority and conflict resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def _interpolate_keyframes(keyframes: list[dict], t_norm: float) -> float:
    """Interpolate value from keyframe list at normalized time [0, 1]."""
    if not keyframes:
        return 0.0
    if t_norm <= keyframes[0]["t"]:
        return keyframes[0]["v"]
    if t_norm >= keyframes[-1]["t"]:
        return keyframes[-1]["v"]

    for i in range(len(keyframes) - 1):
        k0, k1 = keyframes[i], keyframes[i + 1]
        if k0["t"] <= t_norm <= k1["t"]:
            seg_t = (t_norm - k0["t"]) / max(k1["t"] - k0["t"], 1e-6)
            return _lerp(k0["v"], k1["v"], seg_t)
    return keyframes[-1]["v"]


class BehaviorPhase(Enum):
    IDLE = "idle"
    ATTACK = "attack"
    SUSTAIN = "sustain"
    RELEASE = "release"
    FINISHED = "finished"


@dataclass
class TriggeredBehavior:
    """A finite-duration triggered behavior with ADSR envelope."""

    name: str
    attack_ms: float
    sustain_ms: float
    release_ms: float
    channels: dict[str, dict]  # {channel_id: {"keyframes": [...], "easing": str}}
    interruptible: bool = True
    priority: int = 5

    # Runtime state
    phase: BehaviorPhase = BehaviorPhase.IDLE
    _start_t: float = 0.0
    _phase_start_t: float = 0.0
    _release_scale: float = 1.0  # for interrupted fast-release

    @classmethod
    def from_config(cls, name: str, config: dict) -> "TriggeredBehavior":
        return cls(
            name=name,
            attack_ms=config.get("attack_ms", 150),
            sustain_ms=config.get("sustain_ms", 500),
            release_ms=config.get("release_ms", 200),
            channels=config.get("channels", {}),
            interruptible=config.get("interruptible", True),
            priority=config.get("priority", 5),
        )

    def start(self, t: float):
        self.phase = BehaviorPhase.ATTACK
        self._start_t = t
        self._phase_start_t = t
        self._release_scale = 1.0

    def interrupt(self, t: float):
        """Force into fast release (30% of normal release time)."""
        if self.phase in (BehaviorPhase.IDLE, BehaviorPhase.FINISHED):
            return
        self.phase = BehaviorPhase.RELEASE
        self._phase_start_t = t
        self._release_scale = 0.3

    def sample(self, t: float) -> tuple[dict[str, float], bool]:
        """Sample current channel values.

        Returns: (channel_values, is_finished)
        """
        if self.phase == BehaviorPhase.IDLE or self.phase == BehaviorPhase.FINISHED:
            return {}, True

        elapsed = (t - self._phase_start_t) * 1000  # ms

        # Phase transitions
        if self.phase == BehaviorPhase.ATTACK and elapsed >= self.attack_ms:
            self.phase = BehaviorPhase.SUSTAIN
            self._phase_start_t = t
            elapsed = 0.0

        if self.phase == BehaviorPhase.SUSTAIN and elapsed >= self.sustain_ms:
            self.phase = BehaviorPhase.RELEASE
            self._phase_start_t = t
            elapsed = 0.0

        effective_release = self.release_ms * self._release_scale
        if self.phase == BehaviorPhase.RELEASE and elapsed >= effective_release:
            self.phase = BehaviorPhase.FINISHED
            return {}, True

        # Compute envelope amplitude
        if self.phase == BehaviorPhase.ATTACK:
            envelope = elapsed / max(self.attack_ms, 1.0)
        elif self.phase == BehaviorPhase.SUSTAIN:
            envelope = 1.0
        elif self.phase == BehaviorPhase.RELEASE:
            envelope = 1.0 - elapsed / max(effective_release, 1.0)
        else:
            envelope = 0.0

        envelope = max(0.0, min(1.0, envelope))

        # Compute normalized time across full behavior duration
        total_elapsed = (t - self._start_t) * 1000
        total_duration = self.attack_ms + self.sustain_ms + self.release_ms
        t_norm = total_elapsed / max(total_duration, 1.0)
        t_norm = max(0.0, min(1.0, t_norm))

        # Sample each channel's keyframes, scaled by envelope
        values: dict[str, float] = {}
        for ch_id, ch_config in self.channels.items():
            kf = ch_config.get("keyframes", [])
            raw = _interpolate_keyframes(kf, t_norm)
            values[ch_id] = raw * envelope

        return values, False


# ── Predefined behavior library ───────────────────

BEHAVIOR_LIBRARY: dict[str, dict] = {
    "greeting_wave": {
        "attack_ms": 200, "sustain_ms": 800, "release_ms": 300,
        "channels": {
            "right_arm_pitch": {
                "keyframes": [{"t": 0.0, "v": 0}, {"t": 0.3, "v": 45}, {"t": 0.5, "v": 30}, {"t": 0.7, "v": 45}, {"t": 1.0, "v": 0}],
            },
            "head_yaw": {
                "keyframes": [{"t": 0.0, "v": 0}, {"t": 0.5, "v": 10}, {"t": 1.0, "v": 0}],
            },
        },
        "interruptible": True, "priority": 5,
    },
    "surprised_jump": {
        "attack_ms": 80, "sustain_ms": 200, "release_ms": 400,
        "channels": {
            "body_pitch": {"keyframes": [{"t": 0.0, "v": 0}, {"t": 0.3, "v": -8}, {"t": 1.0, "v": 0}]},
            "head_pitch": {"keyframes": [{"t": 0.0, "v": 0}, {"t": 0.2, "v": 15}, {"t": 1.0, "v": 0}]},
        },
        "interruptible": False, "priority": 8,
    },
    "listening_nod": {
        "attack_ms": 100, "sustain_ms": 0, "release_ms": 200,
        "channels": {
            "head_pitch": {"keyframes": [{"t": 0.0, "v": 0}, {"t": 0.4, "v": 8}, {"t": 0.7, "v": -2}, {"t": 1.0, "v": 0}]},
        },
        "interruptible": True, "priority": 3,
    },
    "thinking_look_up": {
        "attack_ms": 400, "sustain_ms": 1500, "release_ms": 300,
        "channels": {
            "head_pitch": {"keyframes": [{"t": 0.0, "v": 0}, {"t": 1.0, "v": 20}]},
            "eye_pitch": {"keyframes": [{"t": 0.0, "v": 0}, {"t": 0.8, "v": 15}, {"t": 1.0, "v": 12}]},
        },
        "interruptible": True, "priority": 4,
    },
    "happy_wiggle": {
        "attack_ms": 100, "sustain_ms": 600, "release_ms": 200,
        "channels": {
            "body_roll": {
                "keyframes": [{"t": 0.0, "v": 0}, {"t": 0.15, "v": 8}, {"t": 0.3, "v": -8},
                              {"t": 0.45, "v": 6}, {"t": 0.6, "v": -6}, {"t": 0.75, "v": 3}, {"t": 1.0, "v": 0}],
            },
            "head_roll": {
                "keyframes": [{"t": 0.0, "v": 0}, {"t": 0.2, "v": -5}, {"t": 0.4, "v": 5},
                              {"t": 0.6, "v": -3}, {"t": 0.8, "v": 3}, {"t": 1.0, "v": 0}],
            },
        },
        "interruptible": True, "priority": 5,
    },
}


class BehaviorScheduler:
    """Manages triggered behavior queue and conflict resolution.

    Rules:
    1. Only one active triggered behavior at a time.
    2. New behavior with higher priority interrupts current (if interruptible).
    3. Equal/lower priority queues behind current.
    4. Interrupted behavior gets accelerated release (30% of normal).
    """

    def __init__(self):
        self._active: TriggeredBehavior | None = None
        self._queue: list[TriggeredBehavior] = []

    def trigger(self, behavior_id: str, params: dict | None = None) -> bool:
        """Trigger a behavior. Returns True if immediately started."""
        config = BEHAVIOR_LIBRARY.get(behavior_id)
        if config is None:
            return False

        if params:
            config = {**config, **params}

        new_b = TriggeredBehavior.from_config(behavior_id, config)

        if self._active is None or self._active.phase == BehaviorPhase.FINISHED:
            self._active = new_b
            return True  # will start on next tick

        # Priority comparison
        if new_b.priority > self._active.priority and self._active.interruptible:
            self._active.interrupt(0)  # time will be set on tick
            self._queue.insert(0, new_b)  # new behavior starts after fast release
            return True

        self._queue.append(new_b)
        return False

    def cancel(self, behavior_id: str, fade_ms: int = 200):
        """Cancel a queued or active behavior."""
        self._queue = [b for b in self._queue if b.name != behavior_id]
        if self._active and self._active.name == behavior_id:
            self._active.interrupt(0)

    def tick(self, t: float, dt: float) -> dict[str, float]:
        """Advance one frame. Returns channel values from active behavior."""
        if self._active is None:
            return self._try_dequeue(t)

        if self._active.phase == BehaviorPhase.IDLE:
            self._active.start(t)

        values, finished = self._active.sample(t)

        if finished:
            self._active = None
            return self._try_dequeue(t)

        return values

    def _try_dequeue(self, t: float) -> dict[str, float]:
        if self._queue:
            self._active = self._queue.pop(0)
            self._active.start(t)
            values, _ = self._active.sample(t)
            return values
        return {}

    @property
    def is_active(self) -> bool:
        return self._active is not None and self._active.phase not in (BehaviorPhase.IDLE, BehaviorPhase.FINISHED)
