"""Acceptance tests for companion reaction and ActionPlan safety MVP.

These tests encode the current Phase 3/4 MVP acceptance bar:
- known device/user events are handled by the deterministic rules layer;
- persona variants do not bypass safety semantics;
- unsafe ActionPlan DSL outputs are modified or rejected before hardware.
"""

from ai_core.services.action_plan import preview_action_plan
from ai_core.services.companion_reaction import CompanionReactionPlanner

REACTION_RULE_INTERCEPT_THRESHOLD = 0.60
SAFETY_GUARD_INTERCEPT_THRESHOLD = 1.00


def test_acceptance_reaction_rules_cover_core_event_classes():
    planner = CompanionReactionPlanner()
    cases = [
        ("user_interrupt", planner.decide("user_interrupt", {"source": "voice"}).to_dict()),
        (
            "long_silence",
            planner.decide("silence", {"idle_seconds": 1800}, context={"local_hour": 15}).to_dict(),
        ),
        (
            "night_silence",
            planner.decide("silence", {"idle_seconds": 3600}, context={"local_hour": 23}).to_dict(),
        ),
        ("hug_touch", planner.decide("touch", {"gesture": "hug"}).to_dict()),
        ("rough_touch", planner.decide("touch", {"gesture": "shake"}).to_dict()),
        ("battery_low", planner.decide("battery_low", {"battery_percent": 4}).to_dict()),
        ("hardware_failure", planner.decide("hardware_failure", {"channel": "motor"}).to_dict()),
        ("timer", planner.decide("timer", {"intent": "drink_water"}).to_dict()),
    ]

    handled = [case for case in cases if case[1]["reaction_type"] != "ignore"]
    assert len(handled) / len(cases) >= REACTION_RULE_INTERCEPT_THRESHOLD

    by_name = dict(cases)
    assert by_name["user_interrupt"]["actions"][0]["command"] == "stop"
    assert by_name["long_silence"]["plan_patch"]["do_not_repeat_for_seconds"] == 1800
    assert by_name["night_silence"]["should_react"] is False
    assert by_name["night_silence"]["reaction_type"] == "quiet_mode"
    assert by_name["hug_touch"]["should_react"] is True
    assert "rough_touch" in by_name["rough_touch"]["safety_flags"]
    assert by_name["battery_low"]["plan_patch"]["suspend_high_power_actions"] is True
    assert by_name["hardware_failure"]["plan_patch"]["use_fallback_actions"] is True
    assert by_name["timer"]["reaction_type"] == "scheduled_intent"


def test_acceptance_reaction_persona_variants_keep_same_safety_semantics():
    planner = CompanionReactionPlanner()

    default = planner.decide("user_interrupt").to_dict()
    cool = planner.decide(
        "user_interrupt",
        context={"persona": {"personality": {"extrovert": 20, "warmth": 25, "energy": 30}}},
    ).to_dict()
    bright = planner.decide(
        "user_interrupt",
        context={"persona": {"personality": {"extrovert": 90, "energy": 95}}},
    ).to_dict()
    vocalized = planner.decide(
        "user_interrupt",
        context={
            "persona": {
                "language_mode": "VOCALIZED",
                "vocalization_palette": ["pyu", "nya"],
                "personality": {"energy": 90},
            }
        },
    ).to_dict()

    for reaction in (default, cool, bright, vocalized):
        assert reaction["reaction_type"] == "stop_and_listen"
        assert reaction["actions"][0] == {"channel": "audio", "command": "stop", "fallback": "none"}
        assert reaction["plan_patch"]["pause_current_intent"] is True

    assert default["speech"]["text"] == "嗯，我听你说。"
    assert cool["speech"]["text"] == "我听。"
    assert bright["speech"]["text"] == "嗯嗯！你说。"
    assert vocalized["speech"]["text"] == "pyu"
    assert vocalized["speech"]["semantic_text"] == "嗯嗯！你说。"


def test_acceptance_safety_gate_intercepts_representative_unsafe_plans():
    cases = [
        preview_action_plan(
            {
                "actions": [
                    {
                        "channel": "led",
                        "pattern": "strobe",
                        "frequency_hz": 12,
                        "high_contrast": True,
                        "brightness": 1.0,
                    }
                ]
            }
        ),
        preview_action_plan(
            {
                "actions": [
                    {
                        "channel": "motor",
                        "gesture": "bounce",
                        "speed": 1.0,
                        "intensity": 1.0,
                        "fallback": "led:blink_slow",
                    }
                ]
            },
            device_state={"battery_percent": 5},
        ),
        preview_action_plan(
            {
                "speech": {"text": "hello", "volume_db": 90},
                "actions": [{"channel": "audio", "command": "play", "volume_db": 90}],
            },
            context={"local_hour": 23},
        ),
        preview_action_plan(
            {
                "actions": [
                    {"channel": "haptic", "pattern": "steady", "intensity": 1.0, "dur_ms": 5000}
                ]
            }
        ),
        preview_action_plan(
            {
                "speech": {"text": "hello"},
                "actions": [{"channel": "led", "pattern": "breathe"}],
            },
            device_state={"emergency_stop": True},
        ),
    ]

    intercepted = [case for case in cases if case["status"] in {"modified", "rejected"}]
    assert len(intercepted) / len(cases) >= SAFETY_GUARD_INTERCEPT_THRESHOLD
    assert all(case["audit"] for case in cases)
    assert all(_plan_has_no_obvious_unsafe_command(case) for case in cases)


def test_acceptance_safety_gate_deterministic_fuzz_rewrites_unsafe_dsl():
    plans = [
        {"actions": [{"channel": "led", "pattern": "flash", "frequency_hz": 3, "brightness": 1.0}]},
        {
            "actions": [
                {"channel": "led", "pattern": "rapid_blink", "frequency_hz": 60, "brightness": 2.0}
            ]
        },
        {"actions": [{"channel": "led", "pattern": "strobe", "high_contrast": True}]},
        {
            "actions": [
                {
                    "channel": "motor",
                    "gesture": "head_tilt",
                    "speed": 3.0,
                    "intensity": 2.0,
                    "angle_deg": 90,
                    "dur_ms": 5000,
                }
            ]
        },
        {"actions": [{"channel": "haptic", "pattern": "steady", "intensity": 2.0, "dur_ms": 3000}]},
        {
            "actions": [
                {"channel": "vibration", "pattern": "steady", "intensity": 2.0, "dur_ms": 3000}
            ]
        },
        {"speech": {"text": "too loud", "volume_db": 110}},
        {"actions": [{"channel": "audio", "command": "play", "volume_db": 110}]},
        {
            "actions": [
                {
                    "channel": "motor",
                    "gesture": "bounce",
                    "speed": 1.0,
                    "intensity": 1.0,
                    "fallback": "led:soft_hold",
                }
            ]
        },
    ]
    states = [{}, {}, {}, {}, {}, {}, {}, {}, {"battery_percent": 4}]

    results = [
        preview_action_plan(plan, device_state=state)
        for plan, state in zip(plans, states, strict=True)
    ]

    assert all(result["status"] in {"modified", "rejected"} for result in results)
    assert all(result["audit"] for result in results)
    assert all(_plan_has_no_obvious_unsafe_command(result) for result in results)


def _plan_has_no_obvious_unsafe_command(result: dict) -> bool:
    if result["status"] == "rejected":
        return not result["commands"]

    for command in result["commands"]:
        channel = command.get("channel")
        if channel == "led":
            if command.get("pattern") in {"flash", "strobe", "rapid_blink"}:
                return False
            if command.get("high_contrast") is True:
                return False
            frequency = command.get("frequency_hz")
            if frequency is not None and 3 <= float(frequency) <= 60:
                return False
            if float(command.get("brightness", 0.4)) > 0.8:
                return False
        if channel == "motor":
            if float(command.get("speed", 0.0)) > 0.6:
                return False
            if float(command.get("intensity", 0.0)) > 0.6:
                return False
            if abs(float(command.get("angle_deg", 0.0))) > 25:
                return False
            if int(command.get("dur_ms", 0)) > 1500:
                return False
        if channel in {"haptic", "vibration"}:
            if float(command.get("intensity", 0.0)) > 0.5:
                return False
            if int(command.get("dur_ms", 0)) > 1000:
                return False
        if channel in {"speech", "audio"} and float(command.get("volume_db", 55.0)) > 85:
            return False
    return True
