"""Render real templates without a database, cache, or model provider."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ai_core.services.character_projection import project_character_fields
from ai_core.services.prompt_builder import PromptBuilder, _personality_to_text

PERSONA_INTEREST = "雨天的旧唱片"
USER_INTEREST = "修复自行车"


def _base(mode="default"):
    return {
        "name": "Test Companion",
        "archetype": "HUMAN",
        "personality": {"warmth": 60},
        "relationship": "温柔的恋人" if mode == "idol" else "同住的伙伴",
        "language_mode": "VOCALIZED" if mode == "vocalized" else "VERBAL",
        "topics": [PERSONA_INTEREST],
        "catchphrases": [],
        "voice_id": "test-profile",
    }


async def _render(base, custom=None, **kwargs):
    builder = PromptBuilder(pool=None)
    builder._get_character = AsyncMock(return_value=base)
    builder._get_customization = AsyncMock(return_value=custom)
    builder._get_voice = AsyncMock(return_value={"dashscope_voice_id": "test-voice"})
    result = await builder.build("test-character", "test-brand", "test-user", **kwargs)
    return result["system_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["default", "idol", "vocalized"])
@pytest.mark.parametrize("custom", [None, {}, {"interest_topics": []}])
async def test_character_topics_do_not_become_user_facts(mode, custom):
    prompt = await _render(_base(mode), custom, structured_output=None)

    assert f"你自己在意或感兴趣的是{PERSONA_INTEREST}" in prompt
    assert f"喜欢{PERSONA_INTEREST}" not in prompt
    assert "不要据此编造对方的偏好或经历" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["default", "idol", "vocalized"])
async def test_user_and_character_interests_keep_separate_owners(mode):
    prompt = await _render(
        _base(mode), {"interest_topics": [USER_INTEREST]}, structured_output=None
    )

    assert f"你自己在意或感兴趣的是{PERSONA_INTEREST}" in prompt
    assert f"喜欢{USER_INTEREST}" in prompt
    assert f"喜欢{PERSONA_INTEREST}" not in prompt
    assert f"你自己在意或感兴趣的是{USER_INTEREST}" not in prompt


def _joi():
    roster = json.loads(
        (Path(__file__).resolve().parents[3] / "configs" / "characters.json").read_text()
    )
    return next(entry for entry in roster["characters"] if entry["id"] == "joi")


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_output", [None, False, True])
@pytest.mark.parametrize("jsonb_as_text", [False, True])
async def test_joi_projection_renders_consistent_honest_persona(structured_output, jsonb_as_text):
    entry = _joi()
    projected = project_character_fields(entry)
    config = entry["emotion_config"]
    base = {
        **projected,
        "emotion_config": json.dumps(config) if jsonb_as_text else config,
        "voice_id": "test-profile",
    }
    memory = {"prompt_text": "[可自然提及] 用户说：叫我小林"}
    prompt = await _render(base, memories=[memory], structured_output=structured_output)

    assert entry["backstory"] in prompt
    assert "也是 AI 伴侣。被问及身份时坦诚回答" in prompt
    assert "什么AI呀" not in prompt
    assert "装听不懂" not in prompt
    assert "有明确用户原话依据时直接回应" in prompt
    assert "记不准就说" not in prompt
    assert "用户自愿选择的名字或昵称可以自然沿用" in prompt
    assert "不要把每次回应变成追问" in prompt
    assert "[可自然提及] 用户说：叫我小林" in prompt
    assert "[隐性关系策略]" in prompt
    assert "今天很累吧。过来，什么都不用说。" not in prompt
    assert "经常讲冷笑话" not in _personality_to_text(projected["personality"])
    assert "元气满满" not in _personality_to_text(projected["personality"])
    assert projected["catchphrases"] == []
    assert memory == {"prompt_text": "[可自然提及] 用户说：叫我小林"}


@pytest.mark.asyncio
async def test_identity_disclosure_does_not_change_without_author_opt_in():
    prompt = await _render(
        _base(), memories=[{"prompt_text": "[可自然提及] 用户喜欢看云"}], structured_output=None
    )
    assert "什么AI呀" in prompt
    assert '记不准就说"好像是……对吧？"' in prompt
    assert "被问及身份时坦诚回答" not in prompt


def test_explicit_empty_catchphrases_disable_only_the_authored_fallback():
    entry = {"id": "test", "name": "Test", "comfort_line": "a default comfort phrase"}
    assert project_character_fields(entry)["catchphrases"] == [entry["comfort_line"]]
    assert project_character_fields({**entry, "catchphrases": []})["catchphrases"] == []
    assert project_character_fields({**entry, "catchphrases": ["chosen"]})["catchphrases"] == [
        "chosen"
    ]
