"""Integration tests for touch perception — tests the full chain:
TouchEngine → EmotionEngine influence → RelationshipEngine bonus → PromptBuilder injection.

Uses real Redis (must be running on localhost:6379).
Mocks DB/LLM/TTS since we only test touch data flow.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_core.services.cache import CacheService
from ai_core.services.touch import TouchEngine, TOUCH_GESTURES
from ai_core.services.emotion import EmotionEngine


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def redis_cache():
    """Real Redis-backed cache for integration tests."""
    import redis.asyncio as aioredis
    client = aioredis.from_url("redis://localhost:6379/1", decode_responses=True)
    cache = CacheService(redis_client=client)
    yield cache
    # Cleanup: flush test DB
    asyncio.get_event_loop().run_until_complete(client.flushdb())


@pytest.fixture
def mock_cache():
    """In-memory mock cache for fast unit-level integration tests."""
    store = {}

    cache = MagicMock(spec=CacheService)

    async def mock_set(key, value, ttl=3600):
        store[key] = value

    async def mock_get(key):
        return store.get(key)

    async def mock_set_json(key, value, ttl=3600):
        store[key] = json.dumps(value, ensure_ascii=False)

    async def mock_get_json(key):
        raw = store.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def mock_delete(key):
        store.pop(key, None)

    cache.set = AsyncMock(side_effect=mock_set)
    cache.get = AsyncMock(side_effect=mock_get)
    cache.set_json = AsyncMock(side_effect=mock_set_json)
    cache.get_json = AsyncMock(side_effect=mock_get_json)
    cache.delete = AsyncMock(side_effect=mock_delete)

    return cache


# ──────────────────────────────────────────────
# Integration: Touch → Emotion chain
# ──────────────────────────────────────────────

class TestTouchEmotionChain:
    """Test: touch event → emotion state update → prompt text generation."""

    @pytest.mark.asyncio
    async def test_hug_shifts_emotion_to_worried(self, mock_cache):
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "test-session-hug"

        # Start with calm emotion
        await emotion.set_emotion(session_id, "calm")
        current = await emotion.get_emotion(session_id)
        assert current == "calm"

        # Process hug touch
        touch_result = await touch.process_touch(session_id, "hug", zone="belly")
        assert touch_result["emotion_hint"] == "worried"

        # Apply touch influence
        new_emotion = emotion.apply_touch_influence(current, touch_result["emotion_hint"])
        assert new_emotion == "worried"

        # Store updated emotion
        await emotion.set_emotion(session_id, new_emotion)
        stored = await emotion.get_emotion(session_id)
        assert stored == "worried"

    @pytest.mark.asyncio
    async def test_poke_shifts_calm_to_playful(self, mock_cache):
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "test-session-poke"
        await emotion.set_emotion(session_id, "calm")

        touch_result = await touch.process_touch(session_id, "poke", zone="cheek")
        new_emotion = emotion.apply_touch_influence("calm", touch_result["emotion_hint"])
        assert new_emotion == "playful"

    @pytest.mark.asyncio
    async def test_pat_shifts_calm_to_happy(self, mock_cache):
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "test-session-pat"
        await emotion.set_emotion(session_id, "calm")

        touch_result = await touch.process_touch(session_id, "pat", zone="head")
        new_emotion = emotion.apply_touch_influence("calm", touch_result["emotion_hint"])
        assert new_emotion == "happy"

    @pytest.mark.asyncio
    async def test_touch_does_not_override_strong_emotion(self, mock_cache):
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "test-session-angry"
        await emotion.set_emotion(session_id, "angry")

        # Pat while angry → stays angry
        touch_result = await touch.process_touch(session_id, "pat")
        new_emotion = emotion.apply_touch_influence("angry", touch_result["emotion_hint"])
        assert new_emotion == "angry"


# ──────────────────────────────────────────────
# Integration: Touch → Cache → Pipeline retrieval
# ──────────────────────────────────────────────

class TestTouchCacheChain:
    """Test: touch event stored → pipeline reads it → context cleared after use."""

    @pytest.mark.asyncio
    async def test_touch_stored_and_retrieved(self, mock_cache):
        touch = TouchEngine(mock_cache)
        session_id = "test-session-cache"

        # Process touch
        await touch.process_touch(session_id, "stroke", zone="back", pressure=0.6)

        # Simulate pipeline reading touch context
        ctx = await touch.get_touch_context(session_id)
        assert ctx is not None
        assert ctx["gesture"] == "stroke"
        assert "摸你的背" in ctx["prompt"]
        assert ctx["affinity_bonus"] >= 4

    @pytest.mark.asyncio
    async def test_touch_context_cleared_after_use(self, mock_cache):
        touch = TouchEngine(mock_cache)
        session_id = "test-session-clear"

        await touch.process_touch(session_id, "hug")

        # Read context
        ctx = await touch.get_touch_context(session_id)
        assert ctx is not None

        # Clear after consumption (as pipeline does)
        await touch.clear_touch_context(session_id)

        # Should be gone
        ctx2 = await touch.get_touch_context(session_id)
        assert ctx2 is None

    @pytest.mark.asyncio
    async def test_multiple_touches_last_wins(self, mock_cache):
        touch = TouchEngine(mock_cache)
        session_id = "test-session-multi"

        await touch.process_touch(session_id, "pat")
        await touch.process_touch(session_id, "hug")

        ctx = await touch.get_touch_context(session_id)
        assert ctx["gesture"] == "hug"  # last touch wins


# ──────────────────────────────────────────────
# Integration: Touch → Mood hint chain
# ──────────────────────────────────────────────

class TestTouchMoodChain:
    """Test: touch mood_hint fills in neutral user mood."""

    @pytest.mark.asyncio
    async def test_hug_provides_lonely_mood(self, mock_cache):
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "test-mood-hug"

        # User says something neutral (no mood keywords)
        user_mood = emotion.detect_user_mood("你好")
        assert user_mood == "neutral"

        # But they're hugging the toy
        touch_result = await touch.process_touch(session_id, "hug")
        assert touch_result["mood_hint"] == "lonely"

        # Pipeline logic: if user_mood is neutral and touch has hint, use touch hint
        if touch_result["mood_hint"] != "neutral" and user_mood == "neutral":
            user_mood = touch_result["mood_hint"]

        assert user_mood == "lonely"

        # Get the corresponding response prompt
        prompt = emotion.get_user_mood_prompt(user_mood)
        assert "陪陪" in prompt or "温暖" in prompt

    @pytest.mark.asyncio
    async def test_text_mood_overrides_touch(self, mock_cache):
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "test-mood-override"

        # User says something angry
        user_mood = emotion.detect_user_mood("气死了！太过分了！")
        assert user_mood == "angry"

        # Touch is pat (mood_hint=happy)
        touch_result = await touch.process_touch(session_id, "pat")
        assert touch_result["mood_hint"] == "happy"

        # But text mood is not neutral, so touch doesn't override
        if touch_result["mood_hint"] != "neutral" and user_mood == "neutral":
            user_mood = touch_result["mood_hint"]

        assert user_mood == "angry"  # text mood preserved


# ──────────────────────────────────────────────
# Integration: Touch prompt injection
# ──────────────────────────────────────────────

class TestTouchPromptInjection:
    """Test: touch context appears correctly in system prompt template."""

    @pytest.mark.asyncio
    async def test_touch_context_in_prompt(self, mock_cache):
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).parent.parent / "src" / "ai_core" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("system_prompt.jinja2")

        touch = TouchEngine(mock_cache)
        result = await touch.process_touch("test-prompt", "stroke", zone="head")

        prompt = template.render(
            name="棉花糖",
            archetype="ANIMAL",
            species="小猫",
            backstory="一只温暖的小猫",
            personality_description="温暖贴心",
            current_emotion=False,
            current_emotion_description="",
            user_mood_instruction="",
            touch_context=result["prompt"],
            time_context="",
            catchphrases=["喵~"],
            suffix="喵",
            relationship="朋友",
            relationship_description="",
            user_title="主人",
            interests=["画画"],
            memory_context=[],
            proactive_trigger=None,
            response_length_instruction="回复控制在1-2句话以内",
            forbidden=[],
            rag_context="",
        )

        # Touch context should be in the prompt
        assert "摸头杀" in prompt
        assert "触摸" in prompt

    @pytest.mark.asyncio
    async def test_no_touch_no_section(self, mock_cache):
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).parent.parent / "src" / "ai_core" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("system_prompt.jinja2")

        prompt = template.render(
            name="棉花糖",
            archetype="ANIMAL",
            species="小猫",
            backstory="",
            personality_description="温暖贴心",
            current_emotion=False,
            current_emotion_description="",
            user_mood_instruction="",
            touch_context="",
            time_context="",
            catchphrases=[],
            suffix="",
            relationship="朋友",
            relationship_description="",
            user_title="主人",
            interests=[],
            memory_context=[],
            proactive_trigger=None,
            response_length_instruction="回复控制在1-2句话以内",
            forbidden=[],
            rag_context="",
        )

        # No touch context → no touch-related text in prompt
        assert "触摸" not in prompt


# ──────────────────────────────────────────────
# Full scenario: simulate a complete interaction
# ──────────────────────────────────────────────

class TestFullTouchScenario:
    """Simulate: user hugs toy → toy detects hug → says something → user speaks → LLM gets touch context."""

    @pytest.mark.asyncio
    async def test_hug_then_chat_scenario(self, mock_cache):
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "scenario-hug-chat"

        # 1. Initial state: calm
        await emotion.set_emotion(session_id, "calm")

        # 2. User hugs the toy (touch event arrives)
        touch_result = await touch.process_touch(
            session_id, "hug", zone="belly", pressure=0.7, duration_ms=5000
        )
        assert touch_result["gesture"] == "hug"
        assert touch_result["intent"] == "寻求安慰"
        assert touch_result["affinity_bonus"] >= 7  # base 6 + long touch bonus 1

        # 3. Emotion shifts
        current_emotion = await emotion.get_emotion(session_id)
        new_emotion = emotion.apply_touch_influence(current_emotion, touch_result["emotion_hint"])
        await emotion.set_emotion(session_id, new_emotion)
        assert new_emotion == "worried"  # character concerned for user

        # 4. User speaks (simulate pipeline reading touch context)
        ctx = await touch.get_touch_context(session_id)
        assert ctx is not None
        assert ctx["gesture"] == "hug"
        assert "抱紧" in ctx["prompt"]

        # 5. Touch context consumed by pipeline
        await touch.clear_touch_context(session_id)
        assert await touch.get_touch_context(session_id) is None

        # 6. Next touch event starts fresh
        await touch.process_touch(session_id, "pat", zone="head")
        ctx2 = await touch.get_touch_context(session_id)
        assert ctx2["gesture"] == "pat"

    @pytest.mark.asyncio
    async def test_rapid_touch_sequence(self, mock_cache):
        """Simulate rapid touch interactions (user playing with toy)."""
        touch = TouchEngine(mock_cache)
        emotion = EmotionEngine(mock_cache)

        session_id = "scenario-rapid"
        await emotion.set_emotion(session_id, "calm")

        gestures = ["poke", "poke", "shake", "pat", "stroke"]
        for gesture in gestures:
            result = await touch.process_touch(session_id, gesture)
            new_emotion = emotion.apply_touch_influence(
                await emotion.get_emotion(session_id),
                result["emotion_hint"],
            )
            await emotion.set_emotion(session_id, new_emotion)

        # After poke+shake+pat+stroke, should end up in a good state
        final_emotion = await emotion.get_emotion(session_id)
        assert final_emotion in ("playful", "happy", "calm")

    @pytest.mark.asyncio
    async def test_all_gestures_produce_valid_output(self, mock_cache):
        """Every gesture should produce a valid result without errors."""
        touch = TouchEngine(mock_cache)

        for gesture in TOUCH_GESTURES:
            result = await touch.process_touch(
                f"test-{gesture}", gesture, zone="head", pressure=0.5, duration_ms=1000
            )
            assert result["gesture"] == gesture
            assert isinstance(result["prompt"], str)
            assert isinstance(result["affinity_bonus"], int)
            assert result["affinity_bonus"] >= 0
            assert result["intensity"] in ("gentle", "normal", "firm")
