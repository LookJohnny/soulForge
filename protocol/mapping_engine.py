"""Performance Primitive → Hardware Command Mapping Engine.

Translates abstract performance primitives into concrete hardware instructions,
with a Degradation Matrix that gracefully falls back when hardware lacks capabilities.

Inspired by Disney Olaf paper Sec. VII-C: runtime mapping from animation to actuators.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Hardware Command (output to actuators) ────────

class CommandType(Enum):
    POSITION = "position"
    COLOR = "color"
    AUDIO = "audio"
    VIBRATION = "vibration"
    BRIGHTNESS = "brightness"


class Easing(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"


@dataclass
class HardwareCommand:
    actuator_id: str
    command_type: CommandType
    value: float | list[float]
    duration_ms: int
    easing: Easing = Easing.EASE_IN_OUT

    def to_dict(self) -> dict:
        return {
            "actuator_id": self.actuator_id,
            "command_type": self.command_type.value,
            "value": self.value,
            "duration_ms": self.duration_ms,
            "easing": self.easing.value,
        }


# ── Degradation Chain Definition ──────────────────

# Each primitive type has an ordered list of "expression strategies".
# The engine tries them top-down; the first one whose required actuators exist wins.

# Strategy format: {"requires": [actuator_types], "body_parts": [parts], "generate": callable}

def _gen_servo_position(actuator_id: str, angle: float, duration: int, easing: Easing = Easing.EASE_IN_OUT) -> HardwareCommand:
    return HardwareCommand(actuator_id, CommandType.POSITION, angle, duration, easing)

def _gen_led_color(actuator_id: str, r: int, g: int, b: int, duration: int) -> HardwareCommand:
    return HardwareCommand(actuator_id, CommandType.COLOR, [r, g, b], duration)

def _gen_led_brightness(actuator_id: str, brightness: float, duration: int) -> HardwareCommand:
    return HardwareCommand(actuator_id, CommandType.BRIGHTNESS, brightness, duration)

def _gen_vibration(actuator_id: str, intensity: float, duration: int) -> HardwareCommand:
    return HardwareCommand(actuator_id, CommandType.VIBRATION, intensity, duration)


# ── Emotion expression degradation chains ─────────

# Maps EmotionType enum values to degradation strategies
EMOTION_DEGRADATION = {
    # JOY = 1
    1: [
        # Best: LED warm + head up + body bounce + voice up
        {"name": "full_joy", "requires": ["led_rgb|led_matrix", "servo@neck", "servo@body"], "weight": 1.0},
        # Good: LED warm + head up + voice up
        {"name": "mid_joy", "requires": ["led_rgb|led_matrix", "servo@neck"], "weight": 0.75},
        # Okay: LED warm + voice up
        {"name": "led_joy", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.5},
        # Minimal: vibration pulse
        {"name": "vib_joy", "requires": ["vibration"], "weight": 0.25},
    ],
    # SADNESS = 2
    2: [
        {"name": "full_sad", "requires": ["led_rgb|led_matrix", "servo@neck"], "weight": 1.0},
        {"name": "led_sad", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.5},
        {"name": "vib_sad", "requires": ["vibration"], "weight": 0.2},
    ],
    # SURPRISE = 3
    3: [
        {"name": "full_surprise", "requires": ["servo@neck", "led_rgb|led_matrix"], "weight": 1.0},
        {"name": "led_surprise", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.5},
        {"name": "vib_surprise", "requires": ["vibration"], "weight": 0.3},
    ],
    # ANGER = 4
    4: [
        {"name": "full_anger", "requires": ["led_rgb|led_matrix", "servo@neck", "vibration"], "weight": 1.0},
        {"name": "led_anger", "requires": ["led_rgb|led_matrix"], "weight": 0.5},
        {"name": "vib_anger", "requires": ["vibration"], "weight": 0.3},
    ],
    # FEAR = 5
    5: [
        {"name": "full_fear", "requires": ["servo@neck", "vibration", "led_rgb|led_matrix"], "weight": 1.0},
        {"name": "vib_fear", "requires": ["vibration"], "weight": 0.4},
        {"name": "led_fear", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.3},
    ],
    # CURIOSITY = 7
    7: [
        {"name": "full_curious", "requires": ["servo@neck", "led_rgb|led_matrix"], "weight": 1.0},
        {"name": "led_curious", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.45},
    ],
    # AFFECTION = 8
    8: [
        {"name": "full_affection", "requires": ["servo@neck", "led_rgb|led_matrix", "vibration"], "weight": 1.0},
        {"name": "led_affection", "requires": ["led_rgb|led_matrix"], "weight": 0.5},
        {"name": "vib_affection", "requires": ["vibration"], "weight": 0.3},
    ],
    # SLEEPY = 9
    9: [
        {"name": "full_sleepy", "requires": ["servo@neck", "led_rgb|led_matrix"], "weight": 0.9},
        {"name": "led_sleepy", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.4},
    ],
    # EXCITED = 10
    10: [
        {"name": "full_excited", "requires": ["servo@neck", "servo@left_arm|servo@right_arm", "led_rgb|led_matrix", "vibration"], "weight": 1.0},
        {"name": "servo_excited", "requires": ["servo@neck", "vibration"], "weight": 0.7},
        {"name": "vib_excited", "requires": ["vibration"], "weight": 0.35},
        {"name": "led_excited", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.25},
    ],
}

# Gesture degradation chains (GestureType enum values)
GESTURE_DEGRADATION = {
    1: [  # WAVE
        {"name": "arm_wave", "requires": ["servo@left_arm|servo@right_arm"], "weight": 1.0},
        {"name": "body_wave", "requires": ["servo@body|servo@neck"], "weight": 0.5},
        {"name": "led_wave", "requires": ["led_rgb|led_matrix|led_single"], "weight": 0.3},
        {"name": "vib_wave", "requires": ["vibration"], "weight": 0.15},
    ],
    2: [  # NOD
        {"name": "head_nod", "requires": ["servo@neck"], "weight": 1.0},
        {"name": "body_nod", "requires": ["servo@body"], "weight": 0.5},
        {"name": "vib_nod", "requires": ["vibration"], "weight": 0.2},
    ],
    3: [  # SHAKE_HEAD
        {"name": "head_shake", "requires": ["servo@neck"], "weight": 1.0},
        {"name": "vib_shake", "requires": ["vibration"], "weight": 0.2},
    ],
    4: [  # TILT_HEAD
        {"name": "head_tilt", "requires": ["servo@neck"], "weight": 1.0},
        {"name": "led_tilt", "requires": ["led_rgb|led_matrix"], "weight": 0.3},
    ],
    6: [  # BOUNCE
        {"name": "body_bounce", "requires": ["servo@body|servo@left_leg|servo@right_leg"], "weight": 1.0},
        {"name": "vib_bounce", "requires": ["vibration"], "weight": 0.4},
    ],
    7: [  # WIGGLE
        {"name": "body_wiggle", "requires": ["servo@body"], "weight": 1.0},
        {"name": "vib_wiggle", "requires": ["vibration"], "weight": 0.35},
    ],
}

# ── Emotion → concrete hardware values ────────────

EMOTION_PARAMS: dict[int, dict] = {
    1:  {"led_r": 255, "led_g": 210, "led_b": 90,  "head_pitch": 10, "brightness": 0.85, "vib_intensity": 0.3, "vib_dur": 300},
    2:  {"led_r": 100, "led_g": 140, "led_b": 210, "head_pitch": -12, "brightness": 0.35, "vib_intensity": 0.15, "vib_dur": 600},
    3:  {"led_r": 255, "led_g": 255, "led_b": 200, "head_pitch": 15, "brightness": 0.9, "vib_intensity": 0.5, "vib_dur": 200},
    4:  {"led_r": 240, "led_g": 80,  "led_b": 80,  "head_pitch": -5, "brightness": 0.7, "vib_intensity": 0.6, "vib_dur": 400},
    5:  {"led_r": 180, "led_g": 160, "led_b": 220, "head_pitch": -8, "brightness": 0.4, "vib_intensity": 0.4, "vib_dur": 500},
    7:  {"led_r": 140, "led_g": 200, "led_b": 255, "head_pitch": 8, "brightness": 0.7, "vib_intensity": 0.0, "vib_dur": 0},
    8:  {"led_r": 255, "led_g": 180, "led_b": 200, "head_pitch": 5, "brightness": 0.65, "vib_intensity": 0.2, "vib_dur": 400},
    9:  {"led_r": 150, "led_g": 150, "led_b": 180, "head_pitch": -10, "brightness": 0.25, "vib_intensity": 0.0, "vib_dur": 0},
    10: {"led_r": 255, "led_g": 220, "led_b": 80,  "head_pitch": 12, "brightness": 0.95, "vib_intensity": 0.7, "vib_dur": 350},
}


# ── Mapping Engine ────────────────────────────────

class MappingEngine:
    """Maps abstract performance primitives to concrete hardware commands.

    Core design: Degradation Matrix.
    Each primitive defines an ordered list of expression strategies.
    The engine picks the best one that the hardware supports.

    Example: GestureType.WAVE degradation chain:
    1. Arm servo continuous motion (best)
    2. Body servo sway + LED blink (degraded)
    3. LED blink pattern (further degraded)
    4. Vibration pulse (minimal)
    """

    def __init__(self, manifest: dict):
        self.manifest = manifest
        self._actuator_index = self._build_actuator_index()
        self._capability_cache = self._analyze_capabilities()

    def _build_actuator_index(self) -> dict[str, dict]:
        """Index actuators by type and body_part for fast lookup."""
        index: dict[str, list[dict]] = {}
        for act in self.manifest.get("actuators", []):
            key_type = act["type"]
            key_part = f"{act['type']}@{act['body_part']}"
            index.setdefault(key_type, []).append(act)
            index.setdefault(key_part, []).append(act)
        return index

    def _has_actuator(self, requirement: str) -> dict | None:
        """Check if hardware has an actuator matching the requirement.

        Requirement format: "type" or "type@body_part", with | for alternatives.
        Returns the first matching actuator or None.
        """
        for alt in requirement.split("|"):
            matches = self._actuator_index.get(alt, [])
            if matches:
                return matches[0]
        return None

    def _check_strategy(self, strategy: dict) -> tuple[bool, list[dict]]:
        """Check if all requirements of a strategy are met.

        Returns: (all_met, matched_actuators)
        """
        matched = []
        for req in strategy["requires"]:
            act = self._has_actuator(req)
            if act is None:
                return False, []
            matched.append(act)
        return True, matched

    def _analyze_capabilities(self) -> dict:
        """Analyze hardware capabilities, cache results."""
        caps = {
            "has_servo": bool(self._actuator_index.get("servo")),
            "has_led_rgb": bool(self._actuator_index.get("led_rgb") or self._actuator_index.get("led_matrix")),
            "has_led_any": bool(self._actuator_index.get("led_single") or self._actuator_index.get("led_rgb") or self._actuator_index.get("led_matrix")),
            "has_vibration": bool(self._actuator_index.get("vibration")),
            "has_speaker": bool(self._actuator_index.get("speaker")),
            "servo_count": len(self._actuator_index.get("servo", [])),
            "led_count": sum(len(v) for k, v in self._actuator_index.items() if k.startswith("led")),
        }
        return caps

    def map_emotion(self, emotion_type: int, intensity: float, duration_ms: int = 500) -> list[HardwareCommand]:
        """Map an emotion primitive to hardware commands."""
        chain = EMOTION_DEGRADATION.get(emotion_type, EMOTION_DEGRADATION.get(1, []))
        params = EMOTION_PARAMS.get(emotion_type, EMOTION_PARAMS.get(1, {}))

        for strategy in chain:
            met, actuators = self._check_strategy(strategy)
            if not met:
                continue

            commands = []
            name = strategy["name"]

            # Generate commands based on strategy name pattern
            if "full" in name or "mid" in name or "servo" in name:
                # LED color
                led = self._has_actuator("led_rgb|led_matrix")
                if led:
                    r = int(params["led_r"] * intensity)
                    g = int(params["led_g"] * intensity)
                    b = int(params["led_b"] * intensity)
                    commands.append(_gen_led_color(led["id"], r, g, b, duration_ms))

                # Head pitch
                neck = self._has_actuator("servo@neck")
                if neck:
                    angle = params["head_pitch"] * intensity
                    commands.append(_gen_servo_position(neck["id"], angle, duration_ms))

                # Vibration
                vib = self._has_actuator("vibration")
                if vib and params.get("vib_intensity", 0) > 0:
                    commands.append(_gen_vibration(vib["id"], params["vib_intensity"] * intensity, int(params["vib_dur"])))

            elif "led" in name:
                led = self._has_actuator("led_rgb|led_matrix|led_single")
                if led:
                    if led["type"] in ("led_rgb", "led_matrix"):
                        commands.append(_gen_led_color(led["id"], int(params["led_r"] * intensity), int(params["led_g"] * intensity), int(params["led_b"] * intensity), duration_ms))
                    else:
                        commands.append(_gen_led_brightness(led["id"], params["brightness"] * intensity, duration_ms))

            elif "vib" in name:
                vib = self._has_actuator("vibration")
                if vib:
                    vi = params.get("vib_intensity", 0.3) * intensity
                    commands.append(_gen_vibration(vib["id"], vi, int(params.get("vib_dur", 300))))

            if commands:
                return commands

        # Absolute fallback: speaker is always there
        return []

    def map_gesture(self, gesture_type: int, amplitude: float, speed: float, duration_ms: int = 800) -> list[HardwareCommand]:
        """Map a gesture primitive to hardware commands."""
        chain = GESTURE_DEGRADATION.get(gesture_type, [])

        for strategy in chain:
            met, actuators = self._check_strategy(strategy)
            if not met:
                continue

            commands = []
            name = strategy["name"]

            if "arm" in name:
                arm = self._has_actuator("servo@left_arm") or self._has_actuator("servo@right_arm")
                if arm:
                    angle = 45 * amplitude
                    commands.append(_gen_servo_position(arm["id"], angle, duration_ms))

            elif "head" in name or "body" in name:
                servo = self._has_actuator("servo@neck") or self._has_actuator("servo@body")
                if servo:
                    if "nod" in name:
                        commands.append(_gen_servo_position(servo["id"], 8 * amplitude, int(duration_ms * 0.5), Easing.EASE_OUT))
                    elif "shake" in name:
                        commands.append(_gen_servo_position(servo["id"], 15 * amplitude, int(duration_ms * 0.5)))
                    elif "tilt" in name:
                        commands.append(_gen_servo_position(servo["id"], 12 * amplitude, duration_ms))
                    else:
                        commands.append(_gen_servo_position(servo["id"], 10 * amplitude, duration_ms))

            elif "led" in name:
                led = self._has_actuator("led_rgb|led_matrix|led_single")
                if led:
                    commands.append(_gen_led_brightness(led["id"], amplitude * 0.8, int(duration_ms * 0.3)))

            elif "vib" in name:
                vib = self._has_actuator("vibration")
                if vib:
                    commands.append(_gen_vibration(vib["id"], amplitude * 0.5, int(duration_ms * 0.4)))

            if commands:
                return commands

        return []

    def map(self, primitive: Any) -> list[HardwareCommand]:
        """Map a CompositePrimitive to hardware commands.

        Args:
            primitive: A CompositePrimitive protobuf message.

        Returns:
            List of HardwareCommand for all actuators.
        """
        commands: list[HardwareCommand] = []

        # Emotion
        if primitive.HasField("emotion") and primitive.emotion.type != 0:
            commands.extend(self.map_emotion(
                primitive.emotion.type, primitive.emotion.intensity,
                primitive.emotion.duration_ms or 500,
            ))

        # Gesture
        if primitive.HasField("gesture") and primitive.gesture.type != 0:
            commands.extend(self.map_gesture(
                primitive.gesture.type, primitive.gesture.amplitude,
                primitive.gesture.speed, 800,
            ))

        return commands

    def get_believability_score(self, primitive: Any) -> float:
        """Estimate believability score for a primitive on this hardware.

        Scoring dimensions:
        - Channel completeness: how many expression channels can be activated
        - Continuity: servos (continuous) score higher than LEDs (discrete)
        - Synchrony: can multiple channels execute simultaneously

        Returns: 0.0-1.0
        """
        bp = self.manifest.get("believability_profile", {})
        max_channels = bp.get("max_emotion_channels", 1)
        fluidity = bp.get("gesture_fluidity_score", 0)

        # Count how many commands this primitive generates
        commands = self.map(primitive)
        if not commands:
            return 0.05  # can still produce audio

        # Channel completeness: how many unique actuators are used
        unique_actuators = len(set(c.actuator_id for c in commands))
        completeness = min(1.0, unique_actuators / max(max_channels, 1))

        # Continuity: servo commands score higher
        servo_cmds = sum(1 for c in commands if c.command_type == CommandType.POSITION)
        continuity = fluidity * (0.5 + 0.5 * min(1.0, servo_cmds / max(len(commands), 1)))

        # Synchrony bonus
        sync = 1.0 if bp.get("audio_visual_sync_capable", False) else 0.7

        score = completeness * 0.4 + continuity * 0.35 + sync * 0.25
        return round(max(0.0, min(1.0, score)), 3)
