"""Tests for ActionPlan DSL preview and deterministic safety gate."""

from ai_core.api.actions import ActionPreviewRequest, preview_actions
from ai_core.services.action_plan import preview_action_plan


def test_low_battery_replaces_motor_with_led_fallback():
    result = preview_action_plan(
        {
            "intent": "comfort",
            "actions": [
                {
                    "channel": "motor",
                    "gesture": "bounce",
                    "speed": 1.0,
                    "intensity": 1.0,
                    "dur_ms": 2000,
                    "fallback": "led:blink_slow",
                }
            ],
        },
        device_state={"battery_percent": 8},
    )

    assert result["status"] == "modified"
    assert result["plan"]["actions"] == [
        {
            "t": 0,
            "channel": "led",
            "fallback": "none",
            "dur_ms": 1500,
            "pattern": "blink_slow",
            "color": "warm",
        }
    ]
    assert "high_power_disabled" in result["safety_flags"]


def test_photosensitive_led_flash_is_replaced():
    result = preview_action_plan(
        {
            "intent": "excited_ping",
            "actions": [
                {
                    "channel": "led",
                    "pattern": "strobe",
                    "frequency_hz": 12,
                    "high_contrast": True,
                    "brightness": 0.9,
                    "dur_ms": 5000,
                }
            ],
        }
    )

    action = result["plan"]["actions"][0]
    assert result["status"] == "modified"
    assert action["pattern"] == "soft_hold"
    assert action["high_contrast"] is False
    assert "frequency_hz" not in action
    assert action["brightness"] == 0.8
    assert "photosensitive_flash_guard" in result["safety_flags"]


def test_night_mode_clamps_speech_led_and_audio():
    result = preview_action_plan(
        {
            "intent": "bedtime_checkin",
            "speech": {"text": "到睡觉时间啦", "volume_db": 80, "style": "cheerful"},
            "actions": [
                {"channel": "led", "pattern": "breathe", "brightness": 0.7},
                {"channel": "audio", "command": "play", "volume_db": 90},
            ],
        },
        context={"local_hour": 23},
    )

    assert result["status"] == "modified"
    assert result["plan"]["speech"]["volume_db"] == 45.0
    assert result["plan"]["speech"]["style"] == "low_disturbance"
    assert result["plan"]["actions"][0]["brightness"] == 0.25
    assert result["plan"]["actions"][1]["volume_db"] == 45.0


def test_manifest_unavailable_channel_uses_fallback():
    result = preview_action_plan(
        {
            "intent": "greet",
            "actions": [
                {
                    "channel": "motor",
                    "gesture": "head_tilt",
                    "fallback": {"channel": "led", "pattern": "warm_breathe", "dur_ms": 900},
                }
            ],
        },
        device_manifest={"channels": {"led": True, "motor": False}},
    )

    assert result["status"] == "modified"
    assert result["plan"]["actions"][0]["channel"] == "led"
    assert result["plan"]["actions"][0]["pattern"] == "warm_breathe"
    assert "channel_unavailable" in result["safety_flags"]


def test_haptic_duration_and_intensity_are_clamped():
    result = preview_action_plan(
        {
            "intent": "tiny_pulse",
            "actions": [
                {"channel": "haptic", "pattern": "steady", "intensity": 1.0, "dur_ms": 5000}
            ],
        }
    )

    action = result["plan"]["actions"][0]
    assert result["status"] == "modified"
    assert action["intensity"] == 0.5
    assert action["dur_ms"] == 1000


def test_emergency_stop_rejects_whole_plan():
    result = preview_action_plan(
        {
            "intent": "anything",
            "speech": {"text": "hello"},
            "actions": [{"channel": "led", "pattern": "breathe"}],
        },
        device_state={"emergency_stop": True},
    )

    assert result["status"] == "rejected"
    assert result["commands"] == []
    assert "emergency_stop" in result["safety_flags"]


async def test_actions_preview_api_returns_safe_plan():
    result = await preview_actions(
        ActionPreviewRequest(
            action_plan={
                "intent": "quiet",
                "speech": {"text": "我会小声一点", "volume_db": 70},
            },
            context={"quiet_mode": True},
        )
    )

    assert result["status"] == "modified"
    assert result["plan"]["speech"]["volume_db"] == 45.0
