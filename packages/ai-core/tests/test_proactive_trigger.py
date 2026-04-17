"""Tests for Proactive Trigger Service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_core.services.proactive_trigger import ProactiveTriggerService


class TestTriggerEligibility:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.get = AsyncMock(return_value=None)  # first message
        self.cache.set = AsyncMock()
        self.svc = ProactiveTriggerService(cache=self.cache)

    @pytest.mark.asyncio
    async def test_no_user_returns_none(self):
        result = await self.svc.maybe_generate_trigger("", "c1", "s1", "FAMILIAR", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_stranger_returns_none(self):
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "STRANGER", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_acquaintance_returns_none(self):
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "ACQUAINTANCE", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_not_first_message_returns_none(self):
        self.cache.get = AsyncMock(return_value="1")  # already started
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "BESTFRIEND", [
            {"type": "PREFERENCE", "content": "喜欢恐龙"}
        ])
        assert result is None


class TestTriggerGeneration:
    def setup_method(self):
        self.cache = MagicMock()
        self.cache.get = AsyncMock(return_value=None)
        self.cache.set = AsyncMock()
        self.svc = ProactiveTriggerService(cache=self.cache)

    @pytest.mark.asyncio
    @patch("ai_core.services.proactive_trigger.random")
    async def test_bestfriend_with_preference_memory(self, mock_random):
        mock_random.random.return_value = 0.1  # always trigger
        mock_random.choice = lambda x: x[0]
        memories = [{"type": "PREFERENCE", "content": "喜欢恐龙"}]
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "BESTFRIEND", memories)
        assert result is not None
        assert "恐龙" in result

    @pytest.mark.asyncio
    @patch("ai_core.services.proactive_trigger.random")
    async def test_event_memory_trigger(self, mock_random):
        mock_random.random.return_value = 0.1
        mock_random.choice = lambda x: x[0]
        memories = [{"type": "EVENT", "content": "明天要考试"}]
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "FRIEND", memories)
        assert result is not None
        assert "考试" in result

    @pytest.mark.asyncio
    @patch("ai_core.services.proactive_trigger.random")
    async def test_topic_memory_trigger(self, mock_random):
        mock_random.random.return_value = 0.1
        mock_random.choice = lambda x: x[0]
        memories = [{"type": "TOPIC", "content": "太空"}]
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "FAMILIAR", memories)
        assert result is not None
        assert "太空" in result

    @pytest.mark.asyncio
    @patch("ai_core.services.proactive_trigger.random")
    async def test_no_memories_gets_greeting(self, mock_random):
        mock_random.random.return_value = 0.1
        mock_random.choice = lambda x: x[0]
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "FRIEND", [])
        assert result is not None
        assert len(result) > 3

    @pytest.mark.asyncio
    @patch("ai_core.services.proactive_trigger.random")
    async def test_probability_roll_fails(self, mock_random):
        mock_random.random.return_value = 0.99  # exceeds all thresholds
        memories = [{"type": "PREFERENCE", "content": "喜欢恐龙"}]
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "FAMILIAR", memories)
        assert result is None  # 0.99 > 0.5 (FAMILIAR prob)

    @pytest.mark.asyncio
    @patch("ai_core.services.proactive_trigger.random")
    async def test_preference_prioritized_over_topic(self, mock_random):
        mock_random.random.return_value = 0.1
        mock_random.choice = lambda x: x[0]
        memories = [
            {"type": "TOPIC", "content": "天气"},
            {"type": "PREFERENCE", "content": "喜欢画画"},
        ]
        result = await self.svc.maybe_generate_trigger("u1", "c1", "s1", "BESTFRIEND", memories)
        assert "画画" in result  # PREFERENCE prioritized
