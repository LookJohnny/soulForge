"""Tests for the Touch Perception Engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ai_core.services.touch import (
    TouchEngine,
    TOUCH_GESTURES,
    TOUCH_ZONES,
    TOUCH_INTENT,
    TOUCH_EMOTION_MAP,
    ZONE_MODIFIERS,
)
from ai_core.services.emotion import EmotionEngine


class TestTouchGestureProcessing:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.set_json = AsyncMock()
        self.cache.get_json = AsyncMock(return_value=None)
        self.cache.delete = AsyncMock()
        self.engine = TouchEngine(cache=self.cache)

    @pytest.mark.asyncio
    async def test_pat_gesture(self):
        result = await self.engine.process_touch("sess-1", "pat", zone="head")
        assert result["gesture"] == "pat"
        assert result["intent"] == "安慰/鼓励"
        assert result["mood_hint"] == "happy"
        assert result["emotion_hint"] == "happy"
        assert result["affinity_bonus"] >= 3
        assert "摸头杀" in result["prompt"]

    @pytest.mark.asyncio
    async def test_stroke_gesture(self):
        result = await self.engine.process_touch("sess-1", "stroke", zone="back")
        assert result["gesture"] == "stroke"
        assert result["intent"] == "亲近/放松"
        assert result["emotion_hint"] == "calm"

    @pytest.mark.asyncio
    async def test_hug_gesture(self):
        result = await self.engine.process_touch("sess-1", "hug")
        assert result["gesture"] == "hug"
        assert result["intent"] == "寻求安慰"
        assert result["mood_hint"] == "lonely"
        assert result["emotion_hint"] == "worried"
        assert result["affinity_bonus"] >= 6

    @pytest.mark.asyncio
    async def test_squeeze_gesture(self):
        result = await self.engine.process_touch("sess-1", "squeeze")
        assert result["gesture"] == "squeeze"
        assert result["mood_hint"] == "angry"

    @pytest.mark.asyncio
    async def test_poke_gesture(self):
        result = await self.engine.process_touch("sess-1", "poke", zone="belly")
        assert result["gesture"] == "poke"
        assert result["emotion_hint"] == "playful"
        assert "肚肚" in result["prompt"]

    @pytest.mark.asyncio
    async def test_hold_gesture(self):
        result = await self.engine.process_touch("sess-1", "hold", zone="hand_left")
        assert result["gesture"] == "hold"
        assert "小手" in result["prompt"]

    @pytest.mark.asyncio
    async def test_shake_gesture(self):
        result = await self.engine.process_touch("sess-1", "shake")
        assert result["gesture"] == "shake"
        assert result["mood_hint"] == "excited"
        assert result["emotion_hint"] == "playful"

    @pytest.mark.asyncio
    async def test_unknown_gesture_defaults_to_none(self):
        result = await self.engine.process_touch("sess-1", "unknown_gesture")
        assert result["gesture"] == "none"
        assert result["affinity_bonus"] == 0

    @pytest.mark.asyncio
    async def test_no_session_id(self):
        result = await self.engine.process_touch("", "pat")
        assert result["gesture"] == "pat"
        # Should not attempt cache write with empty session
        self.cache.set_json.assert_not_called()


class TestTouchIntensity:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.set_json = AsyncMock()
        self.cache.get_json = AsyncMock(return_value=None)
        self.cache.delete = AsyncMock()
        self.engine = TouchEngine(cache=self.cache)

    @pytest.mark.asyncio
    async def test_gentle_pressure(self):
        result = await self.engine.process_touch("sess-1", "pat", pressure=0.1)
        assert result["intensity"] == "gentle"
        assert "轻柔" in result["prompt"]

    @pytest.mark.asyncio
    async def test_normal_pressure(self):
        result = await self.engine.process_touch("sess-1", "pat", pressure=0.5)
        assert result["intensity"] == "normal"

    @pytest.mark.asyncio
    async def test_firm_pressure(self):
        result = await self.engine.process_touch("sess-1", "pat", pressure=0.9)
        assert result["intensity"] == "firm"
        assert "力度比较大" in result["prompt"]

    @pytest.mark.asyncio
    async def test_firm_pat_extra_affinity(self):
        gentle = await self.engine.process_touch("sess-1", "pat", pressure=0.2)
        firm = await self.engine.process_touch("sess-1", "pat", pressure=0.8)
        assert firm["affinity_bonus"] > gentle["affinity_bonus"]

    @pytest.mark.asyncio
    async def test_long_touch_extra_affinity(self):
        short = await self.engine.process_touch("sess-1", "stroke", duration_ms=1000)
        long = await self.engine.process_touch("sess-1", "stroke", duration_ms=5000)
        assert long["affinity_bonus"] > short["affinity_bonus"]


class TestTouchZones:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.set_json = AsyncMock()
        self.cache.get_json = AsyncMock(return_value=None)
        self.cache.delete = AsyncMock()
        self.engine = TouchEngine(cache=self.cache)

    @pytest.mark.asyncio
    async def test_head_zone(self):
        result = await self.engine.process_touch("sess-1", "pat", zone="head")
        assert "摸头杀" in result["prompt"]

    @pytest.mark.asyncio
    async def test_belly_zone(self):
        result = await self.engine.process_touch("sess-1", "stroke", zone="belly")
        assert "痒痒" in result["prompt"]

    @pytest.mark.asyncio
    async def test_cheek_zone(self):
        result = await self.engine.process_touch("sess-1", "stroke", zone="cheek")
        assert "害羞" in result["prompt"]

    @pytest.mark.asyncio
    async def test_no_zone(self):
        result = await self.engine.process_touch("sess-1", "pat", zone=None)
        assert result["zone"] is None


class TestTouchCache:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.set_json = AsyncMock()
        self.cache.get_json = AsyncMock()
        self.cache.delete = AsyncMock()
        self.engine = TouchEngine(cache=self.cache)

    @pytest.mark.asyncio
    async def test_process_stores_in_cache(self):
        await self.engine.process_touch("sess-1", "hug")
        self.cache.set_json.assert_called_once()
        key = self.cache.set_json.call_args[0][0]
        assert key == "touch:sess-1"

    @pytest.mark.asyncio
    async def test_get_touch_context(self):
        self.cache.get_json.return_value = {"gesture": "hug", "prompt": "test"}
        result = await self.engine.get_touch_context("sess-1")
        assert result["gesture"] == "hug"
        self.cache.get_json.assert_called_once_with("touch:sess-1")

    @pytest.mark.asyncio
    async def test_get_touch_context_empty_session(self):
        result = await self.engine.get_touch_context("")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_touch_context(self):
        await self.engine.clear_touch_context("sess-1")
        self.cache.delete.assert_called_once_with("touch:sess-1")


class TestTouchEmotionInfluence:
    """Test EmotionEngine.apply_touch_influence integration."""

    def setup_method(self):
        self.engine = EmotionEngine(cache=MagicMock())

    def test_calm_adopts_touch_hint(self):
        assert self.engine.apply_touch_influence("calm", "happy") == "happy"
        assert self.engine.apply_touch_influence("calm", "playful") == "playful"
        assert self.engine.apply_touch_influence("calm", "worried") == "worried"

    def test_hug_overrides_light_emotions(self):
        assert self.engine.apply_touch_influence("happy", "worried") == "worried"
        assert self.engine.apply_touch_influence("playful", "worried") == "worried"
        assert self.engine.apply_touch_influence("curious", "worried") == "worried"

    def test_poke_overrides_calm_and_worried(self):
        assert self.engine.apply_touch_influence("calm", "playful") == "playful"
        assert self.engine.apply_touch_influence("worried", "playful") == "playful"

    def test_no_override_for_strong_emotions(self):
        assert self.engine.apply_touch_influence("angry", "happy") == "angry"
        assert self.engine.apply_touch_influence("sad", "playful") == "sad"

    def test_empty_hint_no_change(self):
        assert self.engine.apply_touch_influence("happy", "") == "happy"
        assert self.engine.apply_touch_influence("sad", None) == "sad"

    def test_invalid_hint_no_change(self):
        assert self.engine.apply_touch_influence("happy", "invalid") == "happy"


class TestTouchDefinitions:
    """Verify touch definition data integrity."""

    def test_all_gestures_have_intent(self):
        for gesture in TOUCH_GESTURES:
            assert gesture in TOUCH_INTENT

    def test_all_gestures_have_emotion_map(self):
        for gesture in TOUCH_GESTURES:
            assert gesture in TOUCH_EMOTION_MAP

    def test_all_zones_have_modifiers(self):
        for zone in TOUCH_ZONES:
            assert zone in ZONE_MODIFIERS

    def test_emotion_hints_are_valid_emotions(self):
        from ai_core.services.emotion import EMOTIONS
        for gesture, emotion in TOUCH_EMOTION_MAP.items():
            assert emotion in EMOTIONS, f"{gesture} maps to invalid emotion {emotion}"

    def test_affinity_bonuses_non_negative(self):
        for gesture, info in TOUCH_INTENT.items():
            assert info["affinity_bonus"] >= 0
