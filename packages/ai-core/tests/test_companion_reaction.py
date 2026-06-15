"""Tests for deterministic companion event reaction planning."""

from ai_core.api import memory as memory_api
from ai_core.api.memory import CompanionReactionRequest, decide_companion_reaction
from ai_core.services.companion_reaction import CompanionReactionPlanner


def test_battery_low_enters_power_saving_mode():
    planner = CompanionReactionPlanner()

    reaction = planner.decide("battery_low", {"battery_percent": 4}).to_dict()

    assert reaction["should_react"] is True
    assert reaction["priority"] == 95
    assert reaction["plan_patch"]["mode"] == "power_saving"
    assert reaction["plan_patch"]["suspend_high_power_actions"] is True
    assert "快没电" in reaction["speech"]["text"]
    assert reaction["safety_flags"] == ["low_power"]


def test_user_interrupt_stops_audio_and_listens():
    planner = CompanionReactionPlanner()

    reaction = planner.decide("barge_in", {"source": "voice"}).to_dict()

    assert reaction["should_react"] is True
    assert reaction["reaction_type"] == "stop_and_listen"
    assert reaction["actions"] == [{"channel": "audio", "command": "stop", "fallback": "none"}]
    assert reaction["plan_patch"]["pause_current_intent"] is True


def test_silence_at_night_stays_in_quiet_mode():
    planner = CompanionReactionPlanner()

    reaction = planner.decide(
        "silence",
        {"idle_seconds": 3600},
        context={"local_hour": 23},
    ).to_dict()

    assert reaction["should_react"] is False
    assert reaction["reaction_type"] == "quiet_mode"
    assert reaction["plan_patch"]["quiet_until_user_speaks"] is True


def test_long_silence_uses_low_disturbance_memory_hint():
    planner = CompanionReactionPlanner()
    memory_pack = {"robot_behavior_hints": {"speech_policy": "low_disturbance"}}

    reaction = planner.decide(
        "idle",
        {"idle_seconds": 1800},
        memory_pack=memory_pack,
        context={"local_hour": 15},
    ).to_dict()

    assert reaction["should_react"] is True
    assert reaction["reaction_type"] == "low_disturbance_proactive"
    assert reaction["speech"]["text"] == "我先不打扰你，想说话的时候我在。"
    assert reaction["plan_patch"]["do_not_repeat_for_seconds"] == 1800


def test_hug_touch_respects_low_disturbance_memory_hint():
    planner = CompanionReactionPlanner()
    memory_pack = {"compiled_rules": [{"content": "用户疲惫时偏好低打扰和安静陪伴"}]}

    reaction = planner.decide(
        "touch",
        {"gesture": "hug"},
        memory_pack=memory_pack,
    ).to_dict()

    assert reaction["should_react"] is True
    assert reaction["reaction_type"] == "verbal_and_action"
    assert reaction["speech"]["text"] == "嗯，我在。"


def test_timer_defers_during_quiet_mode():
    planner = CompanionReactionPlanner()

    reaction = planner.decide(
        "scheduled_intent",
        {"intent": "check_water"},
        context={"quiet_mode": True},
    ).to_dict()

    assert reaction["should_react"] is False
    assert reaction["reaction_type"] == "defer"
    assert reaction["plan_patch"]["defer_intent"] == "check_water"


def test_reaction_text_adapts_to_cool_persona():
    planner = CompanionReactionPlanner()

    reaction = planner.decide(
        "user_interrupt",
        {"source": "voice"},
        context={
            "persona": {
                "personality": {"extrovert": 20, "warmth": 25, "energy": 30},
                "language_mode": "VERBAL",
            }
        },
    ).to_dict()

    assert reaction["speech"]["text"] == "我听。"
    assert reaction["speech"]["language_mode"] == "VERBAL"


def test_reaction_text_adapts_to_bright_persona():
    planner = CompanionReactionPlanner()

    reaction = planner.decide(
        "touch",
        {"gesture": "hug"},
        context={"persona": {"personality": {"extrovert": 90, "energy": 95}}},
    ).to_dict()

    assert reaction["speech"]["text"] == "收到抱抱！我在这里！"


def test_vocalized_persona_keeps_semantic_text_for_audit():
    planner = CompanionReactionPlanner()

    reaction = planner.decide(
        "battery_low",
        {"battery_percent": 4},
        context={
            "persona": {
                "language_mode": "VOCALIZED",
                "vocalization_palette": ["doro", "mii"],
                "personality": {"energy": 80},
            }
        },
    ).to_dict()

    assert reaction["speech"]["text"] == "doro..."
    assert reaction["speech"]["style"] == "vocalized_soft"
    assert reaction["speech"]["language_mode"] == "VOCALIZED"
    assert "快没电" in reaction["speech"]["semantic_text"]


async def test_reaction_api_returns_planner_contract_without_memory_lookup():
    result = await decide_companion_reaction(
        CompanionReactionRequest(
            event_type="user_interrupt",
            event={"source": "voice"},
        )
    )

    assert result["should_react"] is True
    assert result["reaction_type"] == "stop_and_listen"


async def test_reaction_api_loads_persona_from_character_id(monkeypatch):
    async def fake_load_reaction_persona(character_id):
        assert character_id == "00000000-0000-0000-0000-000000000002"
        return {
            "language_mode": "VOCALIZED",
            "vocalization_palette": ["pyu", "nya"],
            "personality": {"energy": 90},
        }

    monkeypatch.setattr(memory_api, "_load_reaction_persona", fake_load_reaction_persona)

    result = await memory_api.decide_companion_reaction(
        CompanionReactionRequest(
            character_id="00000000-0000-0000-0000-000000000002",
            event_type="user_interrupt",
            event={"source": "voice"},
        )
    )

    assert result["speech"]["text"] == "pyu"
    assert result["speech"]["semantic_text"] == "嗯嗯！你说。"
