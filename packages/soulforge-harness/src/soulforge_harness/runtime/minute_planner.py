"""Resolve the current minute into concrete MicroActions via the active template."""

from __future__ import annotations

from soulforge_harness.runtime.models import (
    HourPlan,
    MicroAction,
    MinuteAction,
    Persona,
)
from soulforge_harness.runtime.templates import resolve_template

# micro-step name -> default adapter command payload
_ADAPTER_HINTS = {
    "walk_to_kitchen": {
        "unity": "MoveTo(kitchen)",
        "mujoco": "base_goto",
        "robot": "nav.goto kitchen",
    },
    "walk_to_plants": {
        "unity": "MoveTo(plants)",
        "mujoco": "base_goto",
        "robot": "nav.goto plants",
    },
    "walk_to_sofa": {
        "unity": "MoveTo(sofa)",
        "mujoco": "base_goto",
        "robot": "nav.goto sofa",
    },
    "stir_pan": {
        "unity": "Anim(stir_pan)",
        "mujoco": "ctrl_arm_stir",
        "robot": "arm.cycle stir",
    },
    "draw_stroke": {
        "unity": "Anim(draw_stroke)",
        "mujoco": "ctrl_arm_stroke",
        "robot": "arm.stroke",
    },
    "water_plant": {
        "unity": "Anim(water_plant)",
        "mujoco": "ctrl_pour",
        "robot": "arm.pour",
    },
    "scan_leaves": {
        "unity": "Anim(scan)",
        "mujoco": "ctrl_head_scan",
        "robot": "sensor.scan",
    },
    "look_at_user": {
        "unity": "LookAt(user)",
        "mujoco": "ctrl_head_track",
        "robot": "head.track user",
    },
    "speak_line": {"unity": "Speak", "robot": "tts.say"},
    "idle_breathing": {
        "unity": "Anim(idle)",
        "mujoco": "ctrl_idle",
        "robot": "pose.hold",
    },
}


def plan_minute(persona: Persona, hour_plan: HourPlan, minute: float) -> MinuteAction:
    activity = hour_plan.activity_at(minute)
    template_id = activity.template_id if activity else "idle"
    template = resolve_template(template_id)

    # walk the template's micro steps, offset by how deep we are into the activity
    steps: list[MicroAction] = []
    if activity and template.micro_steps:
        progress = (minute - activity.start_min) / max(1, activity.duration_min)
        index = min(
            len(template.micro_steps) - 1, int(progress * len(template.micro_steps))
        )
        preferred = activity.params.get("step")
        step_name = (
            preferred
            if preferred in template.micro_steps
            else template.micro_steps[index]
        )
    else:
        step_name = "idle_breathing"

    steps.append(
        MicroAction(
            name=step_name,
            template_id=template_id,
            params=dict(activity.params) if activity else {},
            duration_s=min(
                60.0,
                template.duration_range_s[0] / max(1, len(template.micro_steps) or 1),
            ),
            adapter_command=_ADAPTER_HINTS.get(
                step_name, {"unity": f"Anim({step_name})"}
            ),
        )
    )
    # ambient continuity so the body never freezes between steps
    steps.append(
        MicroAction(
            name="idle_breathing",
            template_id=template_id,
            duration_s=2.0,
            adapter_command=_ADAPTER_HINTS["idle_breathing"],
        )
    )

    return MinuteAction(
        agent_id=persona.agent_id,
        minute=minute,
        template_id=template_id,
        steps=steps,
        reason=(activity.reason if activity else "no scheduled activity -> idle"),
    )
