"""Action templates and ActionUnit compilation.

Action templates are authored in degrees and are split at safe breakpoints.
Each ActionUnit is small enough to serve as a soft-interrupt boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.intent import Intent


Pose = dict[str, float]
Keyframe = tuple[float, Pose]


@dataclass(frozen=True)
class ActionTemplate:
    template_id: str
    keyframes: list[Keyframe]
    safe_breakpoints: list[int]
    channels: list[str] = field(default_factory=list)
    loop: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if len(self.keyframes) < 2:
            raise ValueError(f"{self.template_id} needs at least two keyframes")
        if self.safe_breakpoints[-1] != len(self.keyframes) - 1:
            raise ValueError(f"{self.template_id} must end at the final keyframe")
        if any(bp <= 0 or bp >= len(self.keyframes) for bp in self.safe_breakpoints):
            raise ValueError(f"{self.template_id} has invalid safe breakpoint")


@dataclass
class ActionUnit:
    template_id: str
    keyframes: list[Keyframe]
    end_pose: Pose
    duration_s: float
    intent_id: str
    source: str
    unit_index: int
    total_units: int
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_ACTION_TEMPLATES: dict[str, ActionTemplate] = {
    "idle_scan": ActionTemplate(
        template_id="idle_scan",
        channels=["head_yaw", "head_pitch", "head_roll"],
        keyframes=[
            (
                0.00,
                {
                    "head_yaw": 0.0,
                    "head_pitch": 0.0,
                    "head_roll": 0.0,
                    "body_roll": 0.0,
                },
            ),
            (
                0.30,
                {
                    "head_yaw": 14.0,
                    "head_pitch": 2.0,
                    "head_roll": 1.0,
                    "body_roll": 1.5,
                },
            ),
            (
                0.60,
                {
                    "head_yaw": 5.0,
                    "head_pitch": 4.5,
                    "head_roll": -1.0,
                    "body_roll": -1.0,
                },
            ),
            (
                0.90,
                {
                    "head_yaw": -9.0,
                    "head_pitch": 1.5,
                    "head_roll": 1.5,
                    "body_roll": 1.0,
                },
            ),
            (
                1.20,
                {
                    "head_yaw": 0.0,
                    "head_pitch": 0.0,
                    "head_roll": 0.0,
                    "body_roll": 0.0,
                },
            ),
        ],
        safe_breakpoints=[1, 2, 3, 4],
        loop=True,
    ),
    "look_at_user": ActionTemplate(
        template_id="look_at_user",
        channels=["head_yaw", "head_pitch", "head_roll"],
        keyframes=[
            (0.00, {"head_yaw": 0.0, "head_pitch": 0.0, "head_roll": 0.0}),
            (0.25, {"head_yaw": 12.0, "head_pitch": -3.0, "head_roll": 0.0}),
            (0.55, {"head_yaw": 24.0, "head_pitch": -6.0, "head_roll": 0.0}),
            (1.20, {"head_yaw": 24.0, "head_pitch": -6.0, "head_roll": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3],
    ),
    "listening_nod": ActionTemplate(
        template_id="listening_nod",
        channels=["head_pitch"],
        keyframes=[
            (0.00, {"head_pitch": 0.0}),
            (0.20, {"head_pitch": 8.0}),
            (0.40, {"head_pitch": -2.0}),
            (0.65, {"head_pitch": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3],
    ),
    "happy_wiggle": ActionTemplate(
        template_id="happy_wiggle",
        channels=["head_roll", "head_yaw"],
        keyframes=[
            (0.00, {"head_roll": 0.0, "head_yaw": 0.0}),
            (0.18, {"head_roll": -5.0, "head_yaw": 5.0}),
            (0.36, {"head_roll": 5.0, "head_yaw": -5.0}),
            (0.54, {"head_roll": -3.0, "head_yaw": 3.0}),
            (0.80, {"head_roll": 0.0, "head_yaw": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3, 4],
    ),
    "greeting_wave": ActionTemplate(
        template_id="greeting_wave",
        channels=["right_arm_pitch", "head_yaw", "body_roll"],
        keyframes=[
            (0.00, {"right_arm_pitch": 0.0, "head_yaw": 0.0, "body_roll": 0.0}),
            (0.35, {"right_arm_pitch": 45.0, "head_yaw": 8.0, "body_roll": -2.0}),
            (0.70, {"right_arm_pitch": 20.0, "head_yaw": -6.0, "body_roll": 2.0}),
            (1.05, {"right_arm_pitch": 50.0, "head_yaw": 6.0, "body_roll": -2.0}),
            (1.40, {"right_arm_pitch": 0.0, "head_yaw": 0.0, "body_roll": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3, 4],
    ),
    "daily_stretch": ActionTemplate(
        template_id="daily_stretch",
        channels=["left_arm_pitch", "right_arm_pitch", "head_pitch", "body_yaw"],
        keyframes=[
            (
                0.00,
                {
                    "left_arm_pitch": 0.0,
                    "right_arm_pitch": 0.0,
                    "head_pitch": 0.0,
                    "body_yaw": 0.0,
                },
            ),
            (
                0.60,
                {
                    "left_arm_pitch": 45.0,
                    "right_arm_pitch": 45.0,
                    "head_pitch": 8.0,
                    "body_yaw": -5.0,
                },
            ),
            (
                1.20,
                {
                    "left_arm_pitch": 60.0,
                    "right_arm_pitch": 60.0,
                    "head_pitch": 5.0,
                    "body_yaw": 5.0,
                },
            ),
            (
                1.80,
                {
                    "left_arm_pitch": 0.0,
                    "right_arm_pitch": 0.0,
                    "head_pitch": 0.0,
                    "body_yaw": 0.0,
                },
            ),
        ],
        safe_breakpoints=[1, 2, 3],
    ),
    "sleep_breathing": ActionTemplate(
        template_id="sleep_breathing",
        channels=["head_pitch", "body_roll"],
        keyframes=[
            (0.00, {"head_pitch": -3.0, "body_roll": 0.0}),
            (0.60, {"head_pitch": -4.5, "body_roll": 0.8}),
            (1.20, {"head_pitch": -3.0, "body_roll": -0.8}),
            (1.80, {"head_pitch": -3.0, "body_roll": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3],
        loop=True,
    ),
    "curious_scan": ActionTemplate(
        template_id="curious_scan",
        channels=["head_yaw", "head_pitch", "body_yaw"],
        keyframes=[
            (0.00, {"head_yaw": 0.0, "head_pitch": 0.0, "body_yaw": 0.0}),
            (0.35, {"head_yaw": -18.0, "head_pitch": 4.0, "body_yaw": -3.0}),
            (0.70, {"head_yaw": 18.0, "head_pitch": 3.0, "body_yaw": 3.0}),
            (1.05, {"head_yaw": 0.0, "head_pitch": 0.0, "body_yaw": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3],
    ),
    "thinking_idle": ActionTemplate(
        template_id="thinking_idle",
        channels=["head_pitch", "head_yaw"],
        keyframes=[
            (0.00, {"head_pitch": 0.0, "head_yaw": 0.0}),
            (0.45, {"head_pitch": 10.0, "head_yaw": -4.0}),
            (1.20, {"head_pitch": 8.0, "head_yaw": 4.0}),
            (1.65, {"head_pitch": 0.0, "head_yaw": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3],
    ),
    "micro_nod": ActionTemplate(
        template_id="micro_nod",
        channels=["head_pitch"],
        keyframes=[
            (0.00, {"head_pitch": 0.0}),
            (0.16, {"head_pitch": 4.0}),
            (0.32, {"head_pitch": -1.0}),
            (0.50, {"head_pitch": 0.0}),
        ],
        safe_breakpoints=[1, 2, 3],
    ),
}


def compile_to_units(
    intent: Intent,
    templates: dict[str, ActionTemplate] | None = None,
) -> list[ActionUnit]:
    """Compile an Intent into interruptible ActionUnits."""
    template_map = templates or DEFAULT_ACTION_TEMPLATES
    template_id = intent.action_template_id or intent.payload.get("action_template_id")
    if not template_id:
        raise ValueError("Intent needs action_template_id")

    template = template_map.get(template_id)
    if template is None:
        raise KeyError(f"Unknown action template: {template_id}")

    units: list[ActionUnit] = []
    start_idx = 0
    for unit_idx, breakpoint_idx in enumerate(template.safe_breakpoints):
        segment = template.keyframes[start_idx : breakpoint_idx + 1]
        offset = segment[0][0]
        normalized = [(round(t - offset, 6), dict(pose)) for t, pose in segment]
        duration = normalized[-1][0]
        units.append(
            ActionUnit(
                template_id=template.template_id,
                keyframes=normalized,
                end_pose=dict(normalized[-1][1]),
                duration_s=duration,
                intent_id=intent.intent_id,
                source=intent.source,
                unit_index=unit_idx,
                total_units=len(template.safe_breakpoints),
                metadata=dict(template.metadata),
            )
        )
        start_idx = breakpoint_idx
    return units


def sample_pose(keyframes: list[Keyframe], elapsed_s: float) -> Pose:
    """Linearly interpolate an action-unit pose at elapsed seconds."""
    if not keyframes:
        return {}
    if elapsed_s <= keyframes[0][0]:
        return dict(keyframes[0][1])
    if elapsed_s >= keyframes[-1][0]:
        return dict(keyframes[-1][1])

    for idx in range(len(keyframes) - 1):
        t0, p0 = keyframes[idx]
        t1, p1 = keyframes[idx + 1]
        if t0 <= elapsed_s <= t1:
            alpha = (elapsed_s - t0) / max(t1 - t0, 1e-9)
            channels = set(p0) | set(p1)
            return {
                ch: float(p0.get(ch, p1.get(ch, 0.0)))
                + (
                    float(p1.get(ch, p0.get(ch, 0.0)))
                    - float(p0.get(ch, p1.get(ch, 0.0)))
                )
                * alpha
                for ch in channels
            }
    return dict(keyframes[-1][1])
