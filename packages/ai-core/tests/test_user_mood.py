"""Tests for user mood detection and time awareness."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, date, timedelta

from ai_core.services.emotion import EmotionEngine, USER_MOOD_RESPONSES
from ai_core.services.time_awareness import get_time_context, get_absence_context, build_time_prompt


class TestUserMoodDetection:
    def setup_method(self):
        self.engine = EmotionEngine(cache=MagicMock())

    def test_detect_happy(self):
        assert self.engine.detect_user_mood("太好了！我考了100分！") == "happy"

    def test_detect_sad(self):
        assert self.engine.detect_user_mood("呜呜，我好难过") == "sad"

    def test_detect_angry(self):
        assert self.engine.detect_user_mood("气死了！太过分了！") == "angry"

    def test_detect_worried(self):
        assert self.engine.detect_user_mood("明天要考试，好紧张怎么办") == "worried"

    def test_detect_excited(self):
        assert self.engine.detect_user_mood("好期待！明天就要去旅行了！") == "excited"

    def test_detect_tired(self):
        assert self.engine.detect_user_mood("好累啊，困死了") == "tired"

    def test_detect_lonely(self):
        assert self.engine.detect_user_mood("没人陪我玩，好孤单") == "lonely"

    def test_detect_neutral(self):
        assert self.engine.detect_user_mood("今天天气不错") == "neutral"

    def test_all_moods_have_response(self):
        moods = ["happy", "sad", "angry", "worried", "excited", "tired", "lonely"]
        for mood in moods:
            prompt = self.engine.get_user_mood_prompt(mood)
            assert len(prompt) > 5, f"No response for mood: {mood}"

    def test_neutral_returns_empty(self):
        assert self.engine.get_user_mood_prompt("neutral") == ""


class TestUserMoodState:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.get = AsyncMock(return_value=None)
        self.cache.set = AsyncMock()
        self.engine = EmotionEngine(cache=self.cache)

    @pytest.mark.asyncio
    async def test_get_default(self):
        result = await self.engine.get_user_mood("session-1")
        assert result == "neutral"

    @pytest.mark.asyncio
    async def test_get_from_cache(self):
        self.cache.get = AsyncMock(return_value="sad")
        result = await self.engine.get_user_mood("session-1")
        assert result == "sad"

    @pytest.mark.asyncio
    async def test_set_mood(self):
        await self.engine.set_user_mood("session-1", "happy")
        self.cache.set.assert_called_once()


class TestTimeOfDay:
    def test_morning(self):
        ctx = get_time_context(datetime(2026, 3, 18, 7, 0))
        assert "清晨" in ctx or "早" in ctx

    def test_noon(self):
        ctx = get_time_context(datetime(2026, 3, 18, 12, 0))
        assert "中午" in ctx

    def test_evening(self):
        ctx = get_time_context(datetime(2026, 3, 18, 20, 0))
        assert "晚上" in ctx

    def test_late_night(self):
        ctx = get_time_context(datetime(2026, 3, 18, 22, 0))
        assert "晚" in ctx or "休息" in ctx

    def test_midnight(self):
        ctx = get_time_context(datetime(2026, 3, 18, 2, 0))
        assert "睡觉" in ctx or "晚" in ctx


class TestAbsenceContext:
    def test_first_time(self):
        ctx = get_absence_context(None)
        assert "第一次" in ctx

    def test_same_day(self):
        today = date(2026, 3, 18)
        ctx = get_absence_context("2026-03-18", today)
        assert ctx == ""

    def test_yesterday(self):
        today = date(2026, 3, 18)
        ctx = get_absence_context("2026-03-17", today)
        assert "昨天" in ctx

    def test_few_days(self):
        today = date(2026, 3, 18)
        ctx = get_absence_context("2026-03-15", today)
        assert "两三天" in ctx or "没聊" in ctx

    def test_week(self):
        today = date(2026, 3, 18)
        ctx = get_absence_context("2026-03-10", today)
        assert "一周" in ctx or "好久" in ctx

    def test_month(self):
        today = date(2026, 3, 18)
        ctx = get_absence_context("2026-02-10", today)
        assert "很久" in ctx or "想念" in ctx

    def test_invalid_date(self):
        ctx = get_absence_context("not-a-date")
        assert ctx == ""


class TestBuildTimePrompt:
    def test_returns_string(self):
        result = build_time_prompt("2026-03-17")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_first_visit(self):
        result = build_time_prompt(None)
        assert "第一次" in result
