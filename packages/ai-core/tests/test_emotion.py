"""Tests for the Emotion State Machine."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ai_core.services.emotion import (
    EmotionEngine, EMOTIONS, DEFAULT_EMOTION,
    EMOTION_DESCRIPTIONS, EMOTION_TTS_OFFSETS,
)


class TestEmotionDetection:
    def setup_method(self):
        self.engine = EmotionEngine(cache=MagicMock())

    def test_detect_happy(self):
        assert self.engine.detect_emotion("太好了！好开心呀！") == "happy"

    def test_detect_sad(self):
        assert self.engine.detect_emotion("呜呜，好难过啊") == "sad"

    def test_detect_shy(self):
        assert self.engine.detect_emotion("哎呀，人家害羞嘛") == "shy"

    def test_detect_angry(self):
        assert self.engine.detect_emotion("哼！讨厌，不理你了") == "angry"

    def test_detect_playful(self):
        assert self.engine.detect_emotion("嘿嘿，猜猜我藏在哪里") == "playful"

    def test_detect_curious(self):
        assert self.engine.detect_emotion("真的吗？为什么呢？讲讲") == "curious"

    def test_detect_worried(self):
        assert self.engine.detect_emotion("你还好吗？没事吧？我好担心") == "worried"

    def test_no_keywords_retains_previous(self):
        """When no emotion keywords match, retain previous emotion."""
        assert self.engine.detect_emotion("今天天气不错", previous="happy") == "happy"

    def test_no_keywords_default_calm(self):
        assert self.engine.detect_emotion("今天天气不错") == DEFAULT_EMOTION

    def test_multiple_emotions_picks_strongest(self):
        """When multiple emotions match, the one with more keywords wins."""
        # "好开心 太好了 耶" has 3 happy keywords vs 1 curious "为什么"
        result = self.engine.detect_emotion("好开心！太好了！耶！为什么呢？")
        assert result == "happy"


class TestEmotionState:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.get = AsyncMock(return_value=None)
        self.cache.set = AsyncMock()
        self.engine = EmotionEngine(cache=self.cache)

    @pytest.mark.asyncio
    async def test_get_emotion_default(self):
        result = await self.engine.get_emotion("session-1")
        assert result == DEFAULT_EMOTION

    @pytest.mark.asyncio
    async def test_get_emotion_from_cache(self):
        self.cache.get = AsyncMock(return_value="happy")
        result = await self.engine.get_emotion("session-1")
        assert result == "happy"

    @pytest.mark.asyncio
    async def test_get_emotion_invalid_cached_value(self):
        self.cache.get = AsyncMock(return_value="invalid_emotion")
        result = await self.engine.get_emotion("session-1")
        assert result == DEFAULT_EMOTION

    @pytest.mark.asyncio
    async def test_get_emotion_no_session(self):
        result = await self.engine.get_emotion("")
        assert result == DEFAULT_EMOTION

    @pytest.mark.asyncio
    async def test_set_emotion(self):
        await self.engine.set_emotion("session-1", "happy")
        self.cache.set.assert_called_once_with("emotion:session-1", "happy", ttl=1800)

    @pytest.mark.asyncio
    async def test_set_emotion_invalid_skipped(self):
        await self.engine.set_emotion("session-1", "invalid")
        self.cache.set.assert_not_called()


class TestEmotionTTS:
    def setup_method(self):
        self.engine = EmotionEngine(cache=MagicMock())

    def test_happy_increases_pitch_and_rate(self):
        pitch, rate = self.engine.apply_tts_offsets("happy", 1.0, 1.0)
        assert pitch > 1.0
        assert rate > 1.0

    def test_sad_decreases_pitch_and_rate(self):
        pitch, rate = self.engine.apply_tts_offsets("sad", 1.0, 1.0)
        assert pitch < 1.0
        assert rate < 1.0

    def test_calm_no_change(self):
        pitch, rate = self.engine.apply_tts_offsets("calm", 1.0, 1.0)
        assert pitch == 1.0
        assert rate == 1.0

    def test_clamped_to_valid_range(self):
        pitch, rate = self.engine.apply_tts_offsets("happy", 1.98, 1.98)
        assert pitch <= 2.0
        assert rate <= 2.0

    def test_clamped_floor(self):
        pitch, rate = self.engine.apply_tts_offsets("sad", 0.52, 0.52)
        assert pitch >= 0.5
        assert rate >= 0.5


class TestEmotionPrompt:
    def setup_method(self):
        self.engine = EmotionEngine(cache=MagicMock())

    def test_all_emotions_have_descriptions(self):
        for emotion in EMOTIONS:
            text = self.engine.get_prompt_text(emotion)
            assert text
            assert len(text) > 5

    def test_all_emotions_have_tts_offsets(self):
        for emotion in EMOTIONS:
            offsets = self.engine.get_tts_offsets(emotion)
            assert "pitch_offset" in offsets
            assert "rate_offset" in offsets
