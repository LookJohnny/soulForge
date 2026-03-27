"""Channel Blender — mixes multi-layer behavior outputs per channel.

Ref: Olaf paper Sec. VII-C, path frame alignment & strategy switching.

Each actuator is a "channel". Multiple behavior layers (Ambient, Triggered,
Reactive) write to channels. The blender resolves conflicts and produces
a single output value per channel per frame.

Channel modes:
  EXCLUSIVE: higher-priority layer fully overrides lower (servo angles)
  ADDITIVE:  layer outputs stack (LED brightness offsets)
  BLENDED:   weighted mix (colors)

Transition curves control how layer switches feel:
  LINEAR, EASE_IN, EASE_OUT, EASE_IN_OUT, SPRING, CRITICAL_DAMP
"""

from __future__ import annotations

import math
from enum import Enum
from dataclasses import dataclass, field


class TransitionCurve(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    SPRING = "spring"
    CRITICAL_DAMP = "critical_damp"


class ChannelMode(Enum):
    EXCLUSIVE = "exclusive"
    ADDITIVE = "additive"
    BLENDED = "blended"


def _eval_curve(t: float, curve: TransitionCurve) -> float:
    """Evaluate transition curve at normalized time t ∈ [0, 1]."""
    t = max(0.0, min(1.0, t))

    if curve == TransitionCurve.LINEAR:
        return t
    elif curve == TransitionCurve.EASE_IN:
        return t * t
    elif curve == TransitionCurve.EASE_OUT:
        return 1.0 - (1.0 - t) ** 2
    elif curve == TransitionCurve.EASE_IN_OUT:
        return 3 * t * t - 2 * t * t * t  # smoothstep
    elif curve == TransitionCurve.SPRING:
        # Underdamped spring: slight overshoot then settle
        if t >= 1.0:
            return 1.0
        omega = 2.0 * math.pi * 1.5  # frequency
        zeta = 0.4  # damping ratio (< 1 = underdamped)
        decay = math.exp(-zeta * omega * t)
        osc = math.cos(omega * math.sqrt(1 - zeta * zeta) * t)
        return 1.0 - decay * osc
    elif curve == TransitionCurve.CRITICAL_DAMP:
        # Critically damped: fastest without overshoot
        omega = 8.0
        return 1.0 - (1.0 + omega * t) * math.exp(-omega * t)
    return t


@dataclass
class _LayerState:
    """State of one layer's claim on one channel."""
    value: float = 0.0
    weight: float = 1.0  # for BLENDED mode
    active: bool = False
    # Transition tracking
    transitioning: bool = False
    trans_from: float = 0.0
    trans_to: float = 0.0
    trans_elapsed_ms: float = 0.0
    trans_duration_ms: float = 100.0
    trans_curve: TransitionCurve = TransitionCurve.EASE_IN_OUT


@dataclass
class _ChannelState:
    mode: ChannelMode
    layers: dict[int, _LayerState] = field(default_factory=dict)
    output: float = 0.0


class ChannelBlender:
    """Mixes multi-layer behavior outputs into final channel values.

    Usage:
        blender = ChannelBlender({"head_yaw": ChannelMode.EXCLUSIVE, ...})
        blender.set_layer_output(layer=1, channel_id="head_yaw", value=10.0)
        blender.set_layer_output(layer=2, channel_id="head_yaw", value=30.0)
        result = blender.tick(dt_ms=20)  # → {"head_yaw": 30.0}  (layer 2 wins)
    """

    def __init__(self, channels: dict[str, ChannelMode]):
        self._channels: dict[str, _ChannelState] = {
            cid: _ChannelState(mode=mode) for cid, mode in channels.items()
        }

    def set_layer_output(self, layer: int, channel_id: str, value: float,
                         transition_ms: int = 100,
                         curve: TransitionCurve = TransitionCurve.EASE_IN_OUT,
                         weight: float = 1.0):
        """Set a layer's output for a channel (with optional transition)."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return

        ls = ch.layers.get(layer)
        if ls is None:
            ls = _LayerState()
            ch.layers[layer] = ls

        if ls.active and abs(ls.value - value) > 1e-6 and transition_ms > 0:
            # Start transition from current effective value to new value
            ls.trans_from = self._get_effective_layer_value(ls)
            ls.trans_to = value
            ls.trans_elapsed_ms = 0.0
            ls.trans_duration_ms = float(transition_ms)
            ls.trans_curve = curve
            ls.transitioning = True
        else:
            ls.value = value
            ls.transitioning = False

        ls.active = True
        ls.weight = weight

    def release_channel(self, layer: int, channel_id: str, fade_ms: int = 200):
        """Release a layer's control over a channel (smooth fade out)."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return

        ls = ch.layers.get(layer)
        if ls is None or not ls.active:
            return

        # Transition to 0 then deactivate
        ls.trans_from = self._get_effective_layer_value(ls)
        ls.trans_to = 0.0
        ls.trans_elapsed_ms = 0.0
        ls.trans_duration_ms = float(fade_ms)
        ls.trans_curve = TransitionCurve.EASE_OUT
        ls.transitioning = True
        # Mark for deactivation after transition completes
        ls._pending_release = True

    def tick(self, dt_ms: float) -> dict[str, float]:
        """Advance one frame. Returns all channel output values."""
        result: dict[str, float] = {}

        for cid, ch in self._channels.items():
            # Update transitions
            for layer_id, ls in list(ch.layers.items()):
                if ls.transitioning:
                    ls.trans_elapsed_ms += dt_ms
                    if ls.trans_elapsed_ms >= ls.trans_duration_ms:
                        ls.value = ls.trans_to
                        ls.transitioning = False
                        if getattr(ls, "_pending_release", False):
                            ls.active = False
                            ls._pending_release = False

            # Mix active layers
            active_layers = sorted(
                [(lid, ls) for lid, ls in ch.layers.items() if ls.active],
                key=lambda x: x[0],
            )

            if not active_layers:
                result[cid] = 0.0
                continue

            if ch.mode == ChannelMode.EXCLUSIVE:
                # Highest layer wins
                _, top = active_layers[-1]
                result[cid] = self._get_effective_layer_value(top)

            elif ch.mode == ChannelMode.ADDITIVE:
                total = sum(self._get_effective_layer_value(ls) for _, ls in active_layers)
                result[cid] = max(-1.0, min(1.0, total))

            elif ch.mode == ChannelMode.BLENDED:
                total_weight = sum(ls.weight for _, ls in active_layers)
                if total_weight > 0:
                    result[cid] = sum(
                        self._get_effective_layer_value(ls) * ls.weight / total_weight
                        for _, ls in active_layers
                    )
                else:
                    result[cid] = 0.0

            ch.output = result[cid]

        return result

    def get_channel_values(self) -> dict[str, float]:
        """Get current output values without advancing time."""
        return {cid: ch.output for cid, ch in self._channels.items()}

    def _get_effective_layer_value(self, ls: _LayerState) -> float:
        """Get current value accounting for in-progress transition."""
        if not ls.transitioning:
            return ls.value
        t = ls.trans_elapsed_ms / max(ls.trans_duration_ms, 1.0)
        alpha = _eval_curve(t, ls.trans_curve)
        return ls.trans_from + (ls.trans_to - ls.trans_from) * alpha
