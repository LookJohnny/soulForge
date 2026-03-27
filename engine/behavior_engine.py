"""Behavior Engine — integrates 3 behavior layers into a unified output.

Ref: Olaf paper Sec. VII-C, three-layer animation architecture:
  Layer 1 (Ambient):   Continuous background animations (breathing, saccades)
  Layer 2 (Triggered): Finite-duration actions (wave, nod, wiggle)
  Layer 3 (Reactive):  Immediate sensor responses (touch, proximity)

Data flow:
  Ambient  ──→ ╲
  Triggered ──→ → ChannelBlender → MappingEngine → HardwareCommands
  Reactive  ──→ ╱
"""

from __future__ import annotations

import json
from typing import Any

from engine.blender import ChannelBlender, ChannelMode, TransitionCurve
from engine.ambient_behaviors import AmbientBehaviorComposer
from engine.triggered_behaviors import BehaviorScheduler, BEHAVIOR_LIBRARY
from engine.reactive_layer import ReactiveLayer


# Default channel definitions (can be overridden from hardware manifest)
DEFAULT_CHANNELS: dict[str, ChannelMode] = {
    # Servo channels (exclusive — only one layer controls at a time)
    "head_yaw": ChannelMode.EXCLUSIVE,
    "head_pitch": ChannelMode.EXCLUSIVE,
    "head_roll": ChannelMode.EXCLUSIVE,
    "body_pitch": ChannelMode.EXCLUSIVE,
    "body_roll": ChannelMode.EXCLUSIVE,
    "body_yaw": ChannelMode.EXCLUSIVE,
    "left_arm_pitch": ChannelMode.EXCLUSIVE,
    "right_arm_pitch": ChannelMode.EXCLUSIVE,
    # Eye channels (exclusive)
    "eye_yaw": ChannelMode.EXCLUSIVE,
    "eye_pitch": ChannelMode.EXCLUSIVE,
    "eyelid": ChannelMode.EXCLUSIVE,
    # LED channels (additive — emotion + ambient can stack)
    "led_brightness": ChannelMode.ADDITIVE,
    # Expression channels (exclusive)
    "eyebrow_raise": ChannelMode.EXCLUSIVE,
    "mouth_corner": ChannelMode.EXCLUSIVE,
}

# Layer priorities (higher number = higher priority)
LAYER_AMBIENT = 1
LAYER_TRIGGERED = 2
LAYER_REACTIVE = 3


class BehaviorEngine:
    """Main controller integrating all behavior layers.

    Usage:
        engine = BehaviorEngine(manifest)
        engine.set_persona_mood(emotion_type=1, intensity=0.8)  # JOY

        # Game loop
        output = engine.update(
            dt_ms=20,
            sensor_inputs={"touch_head": 1},
            persona_intent=composite_primitive,
        )
    """

    def __init__(self, hardware_manifest: dict | None = None,
                 behavior_config: dict | None = None):
        channels = dict(DEFAULT_CHANNELS)

        # Build channel list from hardware manifest if available
        if hardware_manifest:
            for act in hardware_manifest.get("actuators", []):
                bp = act["body_part"]
                at = act["type"]
                if at == "servo":
                    channels[f"{bp}_pitch"] = ChannelMode.EXCLUSIVE
                    channels[f"{bp}_yaw"] = ChannelMode.EXCLUSIVE
                elif at in ("led_rgb", "led_matrix", "led_single"):
                    channels[f"{bp}_led"] = ChannelMode.ADDITIVE

        self.blender = ChannelBlender(channels)
        self.ambient = AmbientBehaviorComposer()
        self.scheduler = BehaviorScheduler()
        self.reactive = ReactiveLayer()

        self._time = 0.0
        self._channel_sources: dict[str, str] = {}  # for debugging

    def update(self, dt_ms: float, sensor_inputs: dict | None = None,
               persona_intent: Any = None) -> dict[str, float]:
        """Main frame update.

        Args:
            dt_ms: frame time step in milliseconds
            sensor_inputs: {"touch_head": 1, "proximity_front": 0.3, ...}
            persona_intent: CompositePrimitive from LLM persona engine

        Processing order:
        1. Ambient layer (always runs)
        2. Decode persona_intent → trigger behaviors
        3. Process sensor_inputs → reactive responses
        4. Blend all layers → final channel values
        """
        dt = dt_ms / 1000.0
        self._time += dt

        # 1. Ambient layer
        ambient_out = self.ambient.sample_all(self._time, dt)
        for ch, val in ambient_out.items():
            self.blender.set_layer_output(LAYER_AMBIENT, ch, val, transition_ms=0)

        # 2. Persona intent → triggered behavior
        if persona_intent is not None:
            self._handle_persona_intent(persona_intent)

        # 3. Triggered behavior tick
        triggered_out = self.scheduler.tick(self._time, dt)
        for ch, val in triggered_out.items():
            self.blender.set_layer_output(LAYER_TRIGGERED, ch, val, transition_ms=50)

        # Release triggered channels that are no longer active
        if not self.scheduler.is_active:
            for ch in DEFAULT_CHANNELS:
                self.blender.release_channel(LAYER_TRIGGERED, ch, fade_ms=150)

        # 4. Reactive layer
        if sensor_inputs:
            direct, triggers = self.reactive.process(sensor_inputs, self._time)
            for ch, val in direct.items():
                self.blender.set_layer_output(LAYER_REACTIVE, ch, val, transition_ms=30)
            for trigger_id in triggers:
                self.scheduler.trigger(trigger_id)
        else:
            # Release reactive channels when no sensors active
            for ch in DEFAULT_CHANNELS:
                self.blender.release_channel(LAYER_REACTIVE, ch, fade_ms=100)

        # 5. Blend
        return self.blender.tick(dt_ms)

    def set_persona_mood(self, emotion_type: int, intensity: float):
        """Set emotional context, affects ambient layer parameters."""
        self.ambient.set_emotional_context(emotion_type, intensity)

    def trigger_behavior(self, behavior_id: str) -> bool:
        """Manually trigger a behavior."""
        return self.scheduler.trigger(behavior_id)

    def get_channel_state(self) -> dict[str, dict]:
        """Debug: return each channel's value and controlling layer."""
        result = {}
        values = self.blender.get_channel_values()
        for ch_id, val in values.items():
            ch_state = self.blender._channels.get(ch_id)
            if ch_state is None:
                continue
            active_layers = [
                lid for lid, ls in ch_state.layers.items() if ls.active
            ]
            result[ch_id] = {
                "value": round(val, 4),
                "active_layers": active_layers,
                "controlling": max(active_layers) if active_layers else None,
            }
        return result

    def _handle_persona_intent(self, primitive: Any):
        """Decode CompositePrimitive and trigger appropriate behaviors."""
        # Emotion → mood + optional triggered behavior
        if hasattr(primitive, "emotion") and primitive.emotion.type != 0:
            etype = primitive.emotion.type
            intensity = primitive.emotion.intensity
            self.set_persona_mood(etype, intensity)

            # High-intensity emotions trigger behaviors
            if intensity > 0.6:
                emotion_behavior_map = {
                    1: "happy_wiggle",   # JOY
                    3: "surprised_jump", # SURPRISE
                    10: "happy_wiggle",  # EXCITED
                }
                bid = emotion_behavior_map.get(etype)
                if bid:
                    self.scheduler.trigger(bid)

        # Gesture → triggered behavior
        if hasattr(primitive, "gesture") and primitive.gesture.type != 0:
            gesture_behavior_map = {
                1: "greeting_wave",    # WAVE
                2: "listening_nod",    # NOD
                4: "thinking_look_up", # TILT_HEAD
                6: "happy_wiggle",     # BOUNCE → reuse wiggle
                7: "happy_wiggle",     # WIGGLE
            }
            bid = gesture_behavior_map.get(primitive.gesture.type)
            if bid:
                self.scheduler.trigger(bid)
