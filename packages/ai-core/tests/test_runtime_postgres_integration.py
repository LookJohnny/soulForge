"""Opt-in validation against local PostgreSQL; every test write is rolled back.

Run with RUN_POSTGRES_RUNTIME_INTEGRATION=1. The normal suite skips this module.
Connection details are loaded from the repository .env without logging them.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from dotenv import dotenv_values
from soulforge_harness.runtime.identity import RuntimeIdentity, character_id_for_agent

from ai_core.services.character_projection import CharacterProjectionService
from ai_core.services.runtime_state import LAYER_TABLES, RuntimeStateService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_RUNTIME_INTEGRATION") != "1",
        reason="opt-in local PostgreSQL integration with transaction rollback",
    ),
]


class TransactionPool:
    """Reuse the outer transaction; service transactions become savepoints."""

    def __init__(self, connection):
        self.connection = connection
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        async with self.lock:
            yield self.connection


async def test_real_projection_and_five_memory_layers_rollback_all_synthetic_data():
    env_path = Path(__file__).resolve().parents[3] / ".env"
    database_url = dotenv_values(env_path).get("DATABASE_URL")
    if not database_url:
        pytest.fail("Repository .env has no DATABASE_URL", pytrace=False)
    if urlsplit(database_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("This integration test is restricted to local PostgreSQL", pytrace=False)
    try:
        connection = await asyncpg.connect(database_url, timeout=5)
    except Exception as exc:
        pytest.fail(f"Local PostgreSQL connection failed: {type(exc).__name__}", pytrace=False)

    brand, user, other_user, legacy_id = (str(uuid4()) for _ in range(4))
    transaction = connection.transaction()
    await transaction.start()
    try:
        pool = TransactionPool(connection)
        cache = SimpleNamespace(delete=AsyncMock())
        projection = CharacterProjectionService(pool, cache)
        roster = [
            {
                "id": "integration-luna",
                "name": "Synthetic Runtime Integration",
                "traits": ["warm", "curious"],
                "speech_style": "Synthetic style one",
                "energy": 0.6,
                "voice": {"edge": {"voice": "zh-CN-XiaoyiNeural"}},
            }
        ]
        first = await projection.project(brand, user, roster, "Synthetic rollback test")
        initial_id = first["character_map"]["integration-luna"]
        assert initial_id == character_id_for_agent(brand, "integration-luna")

        # Simulate a pre-existing Studio UUID before any test memories exist.
        await connection.execute(
            "UPDATE characters SET id=$1, emotion_config='{}'::jsonb WHERE id=$2",
            legacy_id,
            initial_id,
        )
        adopted = await projection.project(brand, user, roster)
        assert adopted["character_map"] == {"integration-luna": legacy_id}
        roster[0]["name"] = "Synthetic Renamed Runtime"
        roster[0]["speech_style"] = "Synthetic style two"
        roster[0]["voice"]["edge"]["voice"] = "zh-CN-XiaoxiaoNeural"
        reloaded = await projection.project(brand, user, roster)
        assert reloaded["character_map"] == adopted["character_map"]
        saved = await connection.fetchrow(
            "SELECT c.name, c.backstory, c.voice_id, v.dashscope_voice_id "
            "FROM characters c JOIN voice_profiles v ON c.voice_id=v.id WHERE c.id=$1",
            legacy_id,
        )
        assert saved["name"] == "Synthetic Renamed Runtime"
        assert "Synthetic style two" in saved["backstory"]
        assert saved["dashscope_voice_id"] == "zh-CN-XiaoxiaoNeural"
        cache.delete.assert_any_await(f"char:{brand}:{legacy_id}")
        cache.delete.assert_any_await(f"voice:{saved['voice_id']}")

        resolved = await projection.resolve(brand, user, "integration-luna", "web", "one")
        first_identity = RuntimeIdentity(**resolved["identity"])
        second_identity = RuntimeIdentity(
            **(await projection.resolve(brand, other_user, "integration-luna", "robot", "two"))[
                "identity"
            ]
        )
        memory = RuntimeStateService(pool)
        for layer in LAYER_TABLES:
            first = await memory.upsert(
                brand,
                first_identity,
                layer,
                "shared-key",
                {
                    "scope": "first",
                    "layer": layer,
                    "nested": [1, True, None],
                },
            )
            second = await memory.upsert(
                brand,
                second_identity,
                layer,
                "shared-key",
                {
                    "scope": "second",
                    "layer": layer,
                },
            )
            assert first["id"] != second["id"]
            restored = RuntimeIdentity(user, legacy_id, "integration-luna", "new-body", "new")
            assert (await memory.recall(brand, restored, layer))["values"] == {
                "shared-key": {"scope": "first", "layer": layer, "nested": [1, True, None]}
            }
            assert (await memory.recall(brand, second_identity, layer))["values"] == {
                "shared-key": {"scope": "second", "layer": layer}
            }

        for i in range(75):
            await memory.upsert(brand, first_identity, "episodic", f"event_{i}", i)
        assert len((await memory.recall(brand, first_identity, "episodic"))["values"]) == 76
        one = await memory.upsert(brand, first_identity, "relational", "relationship:kai", 0.7)
        two = await memory.upsert(brand, first_identity, "relational", "relationship:kai", 0.9)
        assert one["id"] == two["id"]
        assert (await memory.recall(brand, first_identity, "relational"))["values"][
            "relationship:kai"
        ] == 0.9
        with pytest.raises(PermissionError):
            await memory.recall(str(uuid4()), first_identity, "episodic")
        with pytest.raises(PermissionError):
            await memory.recall(brand, RuntimeIdentity(user, legacy_id, "forged"), "episodic")
        # All layers retain terminal policy tombstones, including the semantic
        # table shared by semantic and compiled_behavior runtime values.
        for layer, table in LAYER_TABLES.items():
            for policy in ("deleted", "denied"):
                key = f"terminal-{policy}"
                created = await memory.upsert(brand, first_identity, layer, key, "original")
                assignment = (
                    "deleted_at=now()" if policy == "deleted" else "permission_level='DENIED'"
                )
                await connection.execute(
                    f"UPDATE {table} SET {assignment} WHERE id=$1", created["id"]
                )
                blocked = await memory.upsert(brand, first_identity, layer, key, "cannot revive")
                assert blocked["status"] == "blocked"
                recalled = await memory.recall(brand, first_identity, layer)
                assert key not in recalled["values"] and key in recalled["blocked_keys"]
                assert (
                    await connection.fetchval(
                        f"SELECT raw_source->'runtime'->>'value' FROM {table} WHERE id=$1",
                        created["id"],
                    )
                    == "original"
                )
        max_key = "k" * 256
        await memory.upsert(brand, first_identity, "profile", max_key, "long key remains valid")
        assert (await memory.recall(brand, first_identity, "profile"))["values"][max_key] == (
            "long key remains valid"
        )
    finally:
        await transaction.rollback()
        try:
            assert await connection.fetchval("SELECT count(*) FROM brands WHERE id=$1", brand) == 0
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM end_users WHERE id=ANY($1::uuid[])", [user, other_user]
                )
                == 0
            )
        finally:
            await connection.close()


class LocalCache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=3600):
        self.values[key] = value

    async def get_json(self, key):
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key, value, ttl=3600):
        await self.set(key, json.dumps(value), ttl)

    async def delete(self, key):
        self.values.pop(key, None)


async def test_real_cognition_dependencies_write_events_facts_and_recall_after_body_swap(
    monkeypatch,
):
    from ai_core import dependencies
    from ai_core.services.cognition import CognitionService

    env_path = Path(__file__).resolve().parents[3] / ".env"
    database_url = dotenv_values(env_path).get("DATABASE_URL")
    if not database_url or urlsplit(database_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("This integration test requires local PostgreSQL", pytrace=False)
    try:
        connection = await asyncpg.connect(database_url, timeout=5)
    except Exception as exc:
        pytest.fail(f"Local PostgreSQL connection failed: {type(exc).__name__}", pytrace=False)
    brand, user, other_user = (str(uuid4()) for _ in range(3))
    transaction = connection.transaction()
    await transaction.start()
    memory = None
    try:
        pool, cache = TransactionPool(connection), LocalCache()
        llm = SimpleNamespace(
            provider="synthetic",
            model="no-network",
            chat=AsyncMock(
                return_value=json.dumps(
                    {
                        "selected_intent": "respond",
                        "emotional_read": "calm",
                        "plan_delta": "micro",
                        "impact": 1,
                        "template_to_call": "idle",
                        "template_params": {},
                        "dialogue": [
                            {"agent": "integration-luna", "text": "我记住了。", "emotion": "calm"}
                        ],
                        "memory_update": {},
                        "body_actions": [],
                        "pad": {"p": 0.3, "a": -0.1, "d": 0.1},
                        "state_changes": {"trust": 1},
                    },
                    ensure_ascii=False,
                )
            ),
        )
        monkeypatch.setattr(dependencies, "get_pool", AsyncMock(return_value=pool))
        monkeypatch.setattr(dependencies, "get_embedding_service", lambda: None)
        monkeypatch.setattr(dependencies, "_cache", cache)
        monkeypatch.setattr(dependencies, "_llm_client", llm)
        for name in (
            "_prompt_builder",
            "_memory_service",
            "_relationship_engine",
            "_emotion_engine",
        ):
            monkeypatch.setattr(dependencies, name, None)
        projection = CharacterProjectionService(pool, cache)
        await projection.project(
            brand,
            user,
            [
                {
                    "id": "integration-luna",
                    "name": "虚构回滚角色",
                    "traits": ["warm"],
                    "energy": 0.6,
                }
            ],
        )
        resolved = await projection.resolve(brand, user, "integration-luna", "browser", "first")
        identity = resolved["identity"]
        builder = await dependencies.get_prompt_builder()
        memory = await dependencies.get_memory_service()
        relationships = await dependencies.get_relationship_engine()
        service = CognitionService(
            builder=builder,
            memory=memory,
            relationships=relationships,
            emotion=dependencies.get_emotion_engine(),
            llm=await dependencies.get_llm_client(),
            cache=dependencies.get_cache(),
        )
        first = await service.decide(
            identity=identity,
            brand_id=brand,
            event={
                "kind": "user_utterance",
                "text": "我叫虚构阿晴。我喜欢桂花乌龙。",
                "source": "user",
            },
            world={},
        )
        assert first["provider_status"]["status"] == "ok"
        assert first["authoritative_state"]["relationship"]["total_interactions"] == 1
        assert (
            await connection.fetchval("SELECT count(*) FROM raw_event_logs WHERE user_id=$1", user)
            == 1
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM profile_memories WHERE user_id=$1", user
            )
            == 2
        )
        await service.decide(
            identity={**identity, "body_id": "unity", "session_id": "second"},
            brand_id=brand,
            event={
                "kind": "user_utterance",
                "text": "还记得我叫什么和喜欢的茶吗？",
                "source": "user",
            },
            world={},
        )
        prompt = llm.chat.await_args.kwargs["system_prompt"]
        assert "虚构阿晴" in prompt and "桂花乌龙" in prompt
        other = (await projection.resolve(brand, other_user, "integration-luna"))["identity"]
        await service.decide(
            identity=other,
            brand_id=brand,
            event={"kind": "user_utterance", "text": "你好", "source": "user"},
            world={},
        )
        prompt = llm.chat.await_args.kwargs["system_prompt"]
        assert "虚构阿晴" not in prompt and "桂花乌龙" not in prompt
        assert llm.chat.await_count == 3
    finally:
        if memory is not None and memory._usage_tasks:
            await asyncio.gather(*memory._usage_tasks)
        await transaction.rollback()
        try:
            assert await connection.fetchval("SELECT count(*) FROM brands WHERE id=$1", brand) == 0
        finally:
            await connection.close()
