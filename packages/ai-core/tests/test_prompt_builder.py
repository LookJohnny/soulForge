"""Tests for the Prompt Builder service."""

from ai_core.services.prompt_builder import (
    _merge_personality,
    _personality_to_text,
)


def test_merge_personality_no_offsets():
    base = {"extrovert": 80, "humor": 70, "warmth": 90, "curiosity": 50, "energy": 60}
    result = _merge_personality(base, None)
    assert result == base


def test_merge_personality_with_offsets():
    base = {"extrovert": 80, "humor": 70}
    offsets = {"extrovert": 10, "humor": -30}
    result = _merge_personality(base, offsets)
    assert result["extrovert"] == 90
    assert result["humor"] == 40


def test_merge_personality_clamp():
    base = {"extrovert": 95}
    offsets = {"extrovert": 20}
    result = _merge_personality(base, offsets)
    assert result["extrovert"] == 100


def test_personality_to_text_high_traits():
    traits = {"extrovert": 85, "humor": 75, "warmth": 90, "curiosity": 80, "energy": 72}
    text = _personality_to_text(traits)
    assert "活泼外向" in text
    assert "幽默风趣" in text
    assert "温暖贴心" in text


def test_personality_to_text_low_traits():
    traits = {"extrovert": 20, "humor": 25, "warmth": 10, "curiosity": 15, "energy": 28}
    text = _personality_to_text(traits)
    assert "安静内敛" in text
    assert "认真严肃" in text


def test_personality_to_text_mid_traits():
    traits = {"extrovert": 50, "humor": 50, "warmth": 50, "curiosity": 50, "energy": 50}
    text = _personality_to_text(traits)
    assert text == "性格平和，随和友善"
