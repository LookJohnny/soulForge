"""Fixed behavior templates.

Complex activities are never free-formed by the LLM. The LLM selects, parameterizes
and chains these templates; each template already knows its animation clips, servo
poses, Unity/MuJoCo bindings, interruptibility and recovery behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BehaviorTemplate:
    template_id: str
    description: str
    preconditions: list[str]                      # e.g. "at:kitchen", "prop:pan"
    duration_range_s: tuple[float, float]
    required_props: list[str]
    animation_clips: list[str]                    # renderer / Unity clip names
    servo_channels: list[str] = field(default_factory=list)
    unity_command: str = ""
    mujoco_control: str = ""
    interruptible: bool = True
    soft_interrupt_points: str = "between_clips"  # where a pause is allowed
    recovery: str = "resume_last_clip"            # how to continue after interruption
    dialogue_slots: list[str] = field(default_factory=list)
    micro_steps: list[str] = field(default_factory=list)

    def check_preconditions(self, available_props: list[str], location: str) -> list[str]:
        missing: list[str] = []
        for condition in self.preconditions:
            key, _, value = condition.partition(":")
            if key == "prop" and value not in available_props:
                missing.append(condition)
            if key == "at" and value != location:
                missing.append(condition)
        return missing


TEMPLATE_REGISTRY: dict[str, BehaviorTemplate] = {
    template.template_id: template
    for template in [
        BehaviorTemplate(
            template_id="cooking",
            description="Prepare a meal at the kitchen counter",
            preconditions=["at:kitchen", "prop:pan", "prop:stove"],
            duration_range_s=(300, 2400),
            required_props=["pan", "stove"],
            animation_clips=["walk_to_kitchen", "chop", "stir_pan", "taste", "plate_up"],
            servo_channels=["arm_l", "arm_r", "torso_pitch", "head_yaw"],
            unity_command="Activity.Cooking",
            mujoco_control="ctrl_cooking_cycle",
            interruptible=True,
            soft_interrupt_points="between_clips",
            recovery="stir_pan",  # a safe holding clip: food never burns unattended
            dialogue_slots=["offer_taste", "ask_preference", "announce_ready"],
            micro_steps=["walk_to_kitchen", "prep_ingredients", "stir_pan", "wait", "plate_up", "invite_user"],
        ),
        BehaviorTemplate(
            template_id="drawing",
            description="Sketch or paint at the desk",
            preconditions=["at:desk", "prop:tablet"],
            duration_range_s=(300, 5400),
            required_props=["tablet", "pen"],
            animation_clips=["sit_desk", "draw_stroke", "lean_back_review", "pen_tap_think"],
            servo_channels=["arm_r", "head_pitch", "head_yaw"],
            unity_command="Activity.Drawing",
            mujoco_control="ctrl_arm_stroke",
            interruptible=True,
            recovery="draw_stroke",
            dialogue_slots=["share_progress", "ask_opinion"],
            micro_steps=["sit_desk", "draw_stroke", "adjust_pose", "lean_back_review"],
        ),
        BehaviorTemplate(
            template_id="chatting",
            description="Face-to-face companionship talk",
            preconditions=[],
            duration_range_s=(30, 1800),
            required_props=[],
            animation_clips=["look_at_target", "talk_gesture", "listening_nod", "smile"],
            servo_channels=["head_yaw", "head_pitch", "arm_l", "arm_r"],
            unity_command="Activity.Chat",
            mujoco_control="ctrl_idle_gesture",
            interruptible=True,
            soft_interrupt_points="any",
            recovery="look_at_target",
            dialogue_slots=["opener", "empathy", "follow_up", "closing"],
            micro_steps=["look_at_user", "speak_line", "wait_for_response", "listening_nod"],
        ),
        BehaviorTemplate(
            template_id="plant_care",
            description="Inspect and water the plants",
            preconditions=["at:plants", "prop:watering_can"],
            duration_range_s=(60, 600),
            required_props=["watering_can"],
            animation_clips=["scan_leaves", "probe_soil", "water_plant", "report_pose"],
            servo_channels=["head_pitch", "arm_r", "base_wheels"],
            unity_command="Activity.PlantCare",
            mujoco_control="ctrl_scan_water",
            interruptible=True,
            recovery="scan_leaves",
            dialogue_slots=["humidity_report", "care_suggestion"],
            micro_steps=["walk_to_plants", "scan_leaves", "probe_soil", "water_plant", "report"],
        ),
        BehaviorTemplate(
            template_id="repair",
            description="Small household fix with tools",
            preconditions=["prop:toolbox"],
            duration_range_s=(120, 1800),
            required_props=["toolbox"],
            animation_clips=["kneel_inspect", "turn_wrench", "test_part", "pack_tools"],
            servo_channels=["arm_l", "arm_r", "torso_pitch"],
            unity_command="Activity.Repair",
            mujoco_control="ctrl_wrench_cycle",
            interruptible=False,          # torque mid-turn: finish the unit first
            soft_interrupt_points="between_clips",
            recovery="kneel_inspect",
            dialogue_slots=["status_note"],
            micro_steps=["kneel_inspect", "turn_wrench", "test_part", "pack_tools"],
        ),
        BehaviorTemplate(
            template_id="rest",
            description="Wind down on the sofa",
            preconditions=["at:sofa"],
            duration_range_s=(300, 28800),
            required_props=[],
            animation_clips=["sit_sofa", "idle_breathing", "stretch", "browse_phone"],
            unity_command="Activity.Rest",
            mujoco_control="ctrl_rest_pose",
            interruptible=True,
            soft_interrupt_points="any",
            recovery="sit_sofa",
            dialogue_slots=["small_talk"],
            micro_steps=["walk_to_sofa", "sit_sofa", "idle_breathing"],
        ),
        BehaviorTemplate(
            template_id="cleaning",
            description="Tidy a zone of the apartment",
            preconditions=["prop:cloth"],
            duration_range_s=(180, 1800),
            required_props=["cloth"],
            animation_clips=["pick_item", "wipe_surface", "place_item"],
            unity_command="Activity.Cleaning",
            mujoco_control="ctrl_wipe_cycle",
            interruptible=True,
            recovery="pick_item",
            dialogue_slots=["found_item_note"],
            micro_steps=["walk_to_zone", "pick_item", "wipe_surface", "place_item"],
        ),
        BehaviorTemplate(
            template_id="study",
            description="Read or take an online lesson at the desk",
            preconditions=["at:desk", "prop:book"],
            duration_range_s=(600, 7200),
            required_props=["book"],
            animation_clips=["sit_desk", "read_page", "take_note", "think_pose"],
            unity_command="Activity.Study",
            mujoco_control="ctrl_read_pose",
            interruptible=True,
            recovery="read_page",
            dialogue_slots=["share_fact"],
            micro_steps=["sit_desk", "read_page", "take_note"],
        ),
        BehaviorTemplate(
            template_id="idle",
            description="Ambient presence between activities",
            preconditions=[],
            duration_range_s=(5, 600),
            required_props=[],
            animation_clips=["idle_breathing", "idle_scan", "shift_weight"],
            unity_command="Activity.Idle",
            mujoco_control="ctrl_idle",
            interruptible=True,
            soft_interrupt_points="any",
            recovery="idle_breathing",
            dialogue_slots=[],
            micro_steps=["idle_breathing", "look_around"],
        ),
    ]
}


def resolve_template(template_id: str) -> BehaviorTemplate:
    if template_id not in TEMPLATE_REGISTRY:
        raise KeyError(f"unknown behavior template: {template_id}")
    return TEMPLATE_REGISTRY[template_id]
