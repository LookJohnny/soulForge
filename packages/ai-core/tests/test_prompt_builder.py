"""Tests for the Prompt Builder service."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_core.services.prompt_builder import (
    PromptBuilder,
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


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_get_character_scopes_cache_and_query_by_brand():
    row = {"id": "char-1", "name": "Test Character"}
    conn = SimpleNamespace(fetchrow=AsyncMock(return_value=row))
    pool = SimpleNamespace(acquire=lambda: _Acquire(conn))
    cache = SimpleNamespace(get_json=AsyncMock(return_value=None), set_json=AsyncMock())

    builder = PromptBuilder(pool=pool, cache=cache)

    result = await builder._get_character("char-1", "brand-1")

    assert result == row
    cache.get_json.assert_awaited_once_with("char:brand-1:char-1")
    query, character_id, brand_id = conn.fetchrow.await_args.args
    assert "brand_id = $2" in query
    assert character_id == "char-1"
    assert brand_id == "brand-1"
    cache.set_json.assert_awaited_once_with("char:brand-1:char-1", row, ttl=builder.CACHE_TTL)


@pytest.mark.asyncio
async def test_get_character_uses_brand_scoped_cache_before_db():
    cached = {"id": "char-1", "name": "Cached Character"}
    conn = SimpleNamespace(fetchrow=AsyncMock())
    pool = SimpleNamespace(acquire=lambda: _Acquire(conn))
    cache = SimpleNamespace(get_json=AsyncMock(return_value=cached), set_json=AsyncMock())

    builder = PromptBuilder(pool=pool, cache=cache)

    result = await builder._get_character("char-1", "brand-2")

    assert result == cached
    cache.get_json.assert_awaited_once_with("char:brand-2:char-1")
    conn.fetchrow.assert_not_awaited()
    cache.set_json.assert_not_awaited()
