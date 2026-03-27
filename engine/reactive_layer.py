"""Reactive Layer — immediate sensor-driven responses.

Ref: Olaf Sec. VII-C, joystick-driven control (adapted for sensors).

Maps real-time sensor inputs to instant reactions:
  - touch_head → head tilt + warm emotion
  - proximity < 0.3m → lean back (personal space)
  - loud noise → surprised jump
  - pick up (IMU) → grab reaction
  - shake (IMU) → dizzy reaction

Each rule has a cooldown to prevent repeated triggering.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReactiveRule:
    sensor_id: str
    threshold_min: float
    threshold_max: float
    channel_outputs: dict[str, float]  # direct channel values
    trigger_behavior: str | None = None  # optional triggered behavior ID
    cooldown_s: float = 1.0
    _last_trigger: float = -999.0


# Default reactive rules (configurable via YAML)
DEFAULT_RULES: list[dict] = [
    {
        "sensor_id": "touch_head", "threshold_min": 0.5, "threshold_max": 999,
        "channel_outputs": {"head_pitch": -5.0},
        "trigger_behavior": None, "cooldown_s": 0.5,
    },
    {
        "sensor_id": "touch_belly", "threshold_min": 0.5, "threshold_max": 999,
        "channel_outputs": {},
        "trigger_behavior": "happy_wiggle", "cooldown_s": 2.0,
    },
    {
        "sensor_id": "proximity_front", "threshold_min": 0.0, "threshold_max": 0.3,
        "channel_outputs": {"body_pitch": -5.0, "head_pitch": 8.0},
        "trigger_behavior": None, "cooldown_s": 1.0,
    },
    {
        "sensor_id": "imu_shake", "threshold_min": 2.0, "threshold_max": 999,
        "channel_outputs": {},
        "trigger_behavior": "surprised_jump", "cooldown_s": 3.0,
    },
]


class ReactiveLayer:
    """Sensor input → immediate reaction mapping."""

    def __init__(self, rules_config: list[dict] | None = None):
        configs = rules_config or DEFAULT_RULES
        self.rules: list[ReactiveRule] = []
        for rc in configs:
            self.rules.append(ReactiveRule(
                sensor_id=rc["sensor_id"],
                threshold_min=rc.get("threshold_min", 0),
                threshold_max=rc.get("threshold_max", 999),
                channel_outputs=rc.get("channel_outputs", {}),
                trigger_behavior=rc.get("trigger_behavior"),
                cooldown_s=rc.get("cooldown_s", 1.0),
            ))

    def process(self, sensor_inputs: dict[str, float], t: float) -> tuple[dict[str, float], list[str]]:
        """Process sensor inputs, return direct channel values and triggered behavior IDs.

        Args:
            sensor_inputs: {sensor_id: value}
            t: current time (seconds)

        Returns:
            (direct_channel_values, triggered_behavior_ids)
        """
        channels: dict[str, float] = {}
        triggers: list[str] = []

        for rule in self.rules:
            val = sensor_inputs.get(rule.sensor_id)
            if val is None:
                continue

            if rule.threshold_min <= val <= rule.threshold_max:
                if t - rule._last_trigger < rule.cooldown_s:
                    continue  # cooldown active

                rule._last_trigger = t
                channels.update(rule.channel_outputs)

                if rule.trigger_behavior:
                    triggers.append(rule.trigger_behavior)

        return channels, triggers
