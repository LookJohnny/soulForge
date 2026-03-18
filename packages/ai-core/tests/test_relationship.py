"""Tests for the Relationship Evolution Engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import date, timedelta

from ai_core.services.relationship import (
    RelationshipEngine, _affinity_to_stage,
    STAGE_PROMPTS, STAGE_MEMORY_DEPTH, STAGE_TRIGGER_PROB,
)


class TestAffinityToStage:
    def test_stranger(self):
        assert _affinity_to_stage(0) == "STRANGER"
        assert _affinity_to_stage(99) == "STRANGER"

    def test_acquaintance(self):
        assert _affinity_to_stage(100) == "ACQUAINTANCE"
        assert _affinity_to_stage(299) == "ACQUAINTANCE"

    def test_familiar(self):
        assert _affinity_to_stage(300) == "FAMILIAR"
        assert _affinity_to_stage(599) == "FAMILIAR"

    def test_friend(self):
        assert _affinity_to_stage(600) == "FRIEND"
        assert _affinity_to_stage(849) == "FRIEND"

    def test_bestfriend(self):
        assert _affinity_to_stage(850) == "BESTFRIEND"
        assert _affinity_to_stage(1000) == "BESTFRIEND"

    def test_out_of_range(self):
        assert _affinity_to_stage(-1) == "STRANGER"
        assert _affinity_to_stage(1500) == "STRANGER"  # no matching range


class TestStagePrompts:
    def test_all_stages_have_prompts(self):
        for stage in ("STRANGER", "ACQUAINTANCE", "FAMILIAR", "FRIEND", "BESTFRIEND"):
            assert stage in STAGE_PROMPTS
            assert len(STAGE_PROMPTS[stage]) > 5

    def test_all_stages_have_memory_depth(self):
        for stage in ("STRANGER", "ACQUAINTANCE", "FAMILIAR", "FRIEND", "BESTFRIEND"):
            assert stage in STAGE_MEMORY_DEPTH
            assert STAGE_MEMORY_DEPTH[stage] >= 2

    def test_memory_depth_increases_with_stage(self):
        stages = ["STRANGER", "ACQUAINTANCE", "FAMILIAR", "FRIEND", "BESTFRIEND"]
        depths = [STAGE_MEMORY_DEPTH[s] for s in stages]
        assert depths == sorted(depths)

    def test_trigger_prob_increases_with_stage(self):
        assert STAGE_TRIGGER_PROB["STRANGER"] == 0.0
        assert STAGE_TRIGGER_PROB["FAMILIAR"] > 0
        assert STAGE_TRIGGER_PROB["FRIEND"] > STAGE_TRIGGER_PROB["FAMILIAR"]
        assert STAGE_TRIGGER_PROB["BESTFRIEND"] > STAGE_TRIGGER_PROB["FRIEND"]


class TestRelationshipEngineGetState:
    def setup_method(self):
        self.pool = MagicMock()
        self.cache = MagicMock()
        self.cache.get_json = AsyncMock(return_value=None)
        self.cache.set_json = AsyncMock()
        self.engine = RelationshipEngine(pool=self.pool, cache=self.cache)

    @pytest.mark.asyncio
    async def test_no_user_returns_default(self):
        state = await self.engine.get_state("", "char-1")
        assert state["affinity"] == 0
        assert state["stage"] == "STRANGER"

    @pytest.mark.asyncio
    async def test_cached_state_returned(self):
        cached = {"affinity": 500, "stage": "FAMILIAR", "streak_days": 3,
                  "last_interaction_date": "2026-03-17", "turn_count_today": 5}
        self.cache.get_json = AsyncMock(return_value=cached)
        state = await self.engine.get_state("user-1", "char-1")
        assert state["affinity"] == 500
        assert state["stage"] == "FAMILIAR"


class TestRelationshipEngineHelpers:
    def setup_method(self):
        self.engine = RelationshipEngine(pool=MagicMock(), cache=MagicMock())

    def test_get_stage_prompt(self):
        assert "不太熟" in self.engine.get_stage_prompt("STRANGER")
        assert "好朋友" in self.engine.get_stage_prompt("FRIEND")
        assert "无话不说" in self.engine.get_stage_prompt("BESTFRIEND")

    def test_get_memory_depth(self):
        assert self.engine.get_memory_depth("STRANGER") == 2
        assert self.engine.get_memory_depth("BESTFRIEND") == 10
