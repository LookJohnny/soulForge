"""Synthetic-data checks for file projection and exact runtime persistence."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulforge_harness.runtime.identity import (
    RuntimeIdentity,
    character_id_for_agent,
    runtime_user_id,
)

from ai_core.api import runtime_state as api
from ai_core.services.character_projection import (
    CharacterProjectionService,
    project_character_fields,
)
from ai_core.services.memory import MemoryService
from ai_core.services.runtime_state import RuntimeStateService

BRAND = "70000000-0000-0000-0000-000000000001"
OTHER_BRAND = "70000000-0000-0000-0000-000000000002"
USER = runtime_user_id(BRAND)


class Database:
    """Small data-backed protocol double; no external DB, Redis or model access."""

    def __init__(self):
        self.characters = {}
        self.users = set()
        self.memories = {}
        self.voices = {}
        self.queries = []

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, sql, *args):
        self.queries.append((sql, args))
        if "INSERT INTO end_users" in sql:
            self.users.add(args[0])
        elif "INSERT INTO characters" in sql:
            self.characters[args[0]] = {
                "id": args[0],
                "brand_id": args[1],
                "name": args[2],
                "backstory": args[5],
                "personality": json.loads(args[7]),
                "voice_id": args[12],
                "emotion_config": json.loads(args[14]),
            }
        elif "INSERT INTO voice_profiles" in sql:
            self.voices[args[0]] = {"name": args[1], "edge": args[3], "fish": args[4]}

    async def fetchval(self, sql, *args):
        return False  # optional vector migration is not required for state storage

    async def fetch(self, sql, *args):
        self.queries.append((sql, args))
        if "FROM characters" in sql:
            return [row for row in self.characters.values() if row["brand_id"] == args[0]]
        assert "LIMIT" not in sql.upper(), "state restoration cannot use RAG top-k"
        user, character, agent, layer = args
        return [
            row
            for row in self.memories.values()
            if row["user_id"] == user
            and row["character_id"] == character
            and row["raw_source"]["runtime"]["agent_id"] == agent
            and row["raw_source"]["runtime"]["layer"] == layer
        ]

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, args))
        if "FROM characters c" in sql:
            row = self.characters.get(args[0])
            return row if row and row["brand_id"] == args[1] and args[2] in self.users else None
        if "INSERT INTO" in sql:
            self.memories[args[0]] = {
                "id": args[0],
                "user_id": args[1],
                "character_id": args[2],
                "content": args[3],
                "raw_source": json.loads(args[4]),
            }
            return {"id": args[0]}
        raise AssertionError(sql)


def character(name="Luna", voice="zh-CN-XiaoyiNeural", style="自然、温暖"):
    return {
        "id": "luna",
        "name": name,
        "archetype": "creative_care",
        "traits": ["warm", "artistic"],
        "energy": 0.7,
        "speech_style": style,
        "voice": {"edge": {"voice": voice}},
    }


@pytest.mark.asyncio
async def test_projection_bootstraps_then_hot_reload_preserves_identity_and_updates_voice():
    db, cache = Database(), SimpleNamespace(delete=AsyncMock())
    service = CharacterProjectionService(db, cache)
    first = await service.project(BRAND, USER, [character()])
    cid = first["character_map"]["luna"]
    assert cid == character_id_for_agent(BRAND, "luna") and USER in db.users
    second = await service.project(
        BRAND, USER, [character("New Luna", "zh-CN-XiaoxiaoNeural", "短句、直接")]
    )
    assert second["character_map"] == first["character_map"]
    assert len(db.characters) == len(db.voices) == 1
    assert "短句、直接" in db.characters[cid]["backstory"]
    assert db.voices[db.characters[cid]["voice_id"]]["edge"] == "zh-CN-XiaoxiaoNeural"
    cache.delete.assert_any_await(f"char:{BRAND}:{cid}")
    cache.delete.assert_any_await(f"voice:{db.characters[cid]['voice_id']}")
    assert cache.delete.await_count == 4
    identity = await service.resolve(BRAND, USER, "luna", "new-body", "new-session")
    assert (
        identity["identity"]
        == RuntimeIdentity(USER, cid, "luna", "new-body", "new-session").to_dict()
    )


@pytest.mark.asyncio
async def test_unique_legacy_name_projection_keeps_existing_character_foreign_keys():
    db = Database()
    legacy_id = "80000000-0000-0000-0000-000000000099"
    db.characters[legacy_id] = {
        "id": legacy_id,
        "name": "Luna",
        "brand_id": BRAND,
        "emotion_config": {},
    }
    result = await CharacterProjectionService(db).project(BRAND, USER, [character()])
    assert result["character_map"] == {"luna": legacy_id}
    assert len(db.characters) == 1
    renamed = character("Renamed Luna")
    assert (await CharacterProjectionService(db).project(BRAND, USER, [renamed]))[
        "character_map"
    ] == {"luna": legacy_id}


@pytest.mark.asyncio
async def test_ambiguous_legacy_name_fails_without_choosing_another_users_character():
    db = Database()
    for suffix in (1, 2):
        cid = f"80000000-0000-0000-0000-{suffix:012d}"
        db.characters[cid] = {"id": cid, "name": "Luna", "brand_id": BRAND, "emotion_config": {}}
    with pytest.raises(ValueError, match="ambiguous"):
        await CharacterProjectionService(db).project(BRAND, USER, [character()])
    assert len(db.characters) == 2
    assert not db.voices


@pytest.mark.asyncio
async def test_runtime_state_upserts_key_and_restores_every_value_after_body_switch():
    db = Database()
    await CharacterProjectionService(db).project(BRAND, USER, [character()])
    identity = RuntimeIdentity(USER, character_id_for_agent(BRAND, "luna"), "luna", "web", "a")
    service = RuntimeStateService(db)
    for i in range(75):
        await service.upsert(BRAND, identity, "episodic", f"event_{i}", {"day": i})
    first = await service.upsert(BRAND, identity, "relational", "relationship:kai", 0.7)
    second = await service.upsert(BRAND, identity, "relational", "relationship:kai", 0.8)
    assert first["id"] == second["id"]
    switched = RuntimeIdentity(USER, identity.character_id, "luna", "robot", "b")
    assert len((await service.recall(BRAND, switched, "episodic"))["values"]) == 75
    assert (await service.recall(BRAND, switched, "relational"))["values"] == {
        "relationship:kai": 0.8
    }
    assert "熟悉程度" in db.memories[first["id"]]["content"]
    assert len(db.memories) == 76


@pytest.mark.asyncio
async def test_runtime_state_rejects_cross_brand_unknown_user_and_forged_agent():
    db = Database()
    await CharacterProjectionService(db).project(BRAND, USER, [character()])
    cid = character_id_for_agent(BRAND, "luna")
    for brand, identity in (
        (OTHER_BRAND, RuntimeIdentity(USER, cid, "luna")),
        (BRAND, RuntimeIdentity(runtime_user_id(BRAND, "unknown"), cid, "luna")),
        (BRAND, RuntimeIdentity(USER, cid, "kai")),
    ):
        with pytest.raises(PermissionError):
            await RuntimeStateService(db).upsert(brand, identity, "episodic", "request", "private")
        with pytest.raises(PermissionError):
            await RuntimeStateService(db).recall(brand, identity, "episodic")
    assert not db.memories


@pytest.mark.asyncio
async def test_two_known_users_keep_distinct_values_for_the_same_agent_and_key():
    db = Database()
    projection = CharacterProjectionService(db)
    await projection.project(BRAND, USER, [character()])
    other_user = runtime_user_id(BRAND, "other-household")
    resolved = await projection.resolve(BRAND, other_user, "luna")
    first = RuntimeIdentity(USER, resolved["identity"]["character_id"], "luna")
    second = RuntimeIdentity(**resolved["identity"])
    assert first.user_id in db.users and second.user_id in db.users
    state = RuntimeStateService(db)
    row1 = await state.upsert(BRAND, first, "episodic", "last_request", "first-user-only")
    row2 = await state.upsert(BRAND, second, "episodic", "last_request", "second-user-only")
    assert row1["id"] != row2["id"]
    assert (await state.recall(BRAND, first, "episodic"))["values"] == {
        "last_request": "first-user-only"
    }
    assert (await state.recall(BRAND, second, "episodic"))["values"] == {
        "last_request": "second-user-only"
    }


def test_malformed_authored_personality_is_a_validation_error():
    with pytest.raises(ValueError, match="personality must be an object"):
        project_character_fields({**character(), "personality": "wrong-shape"})


@pytest.mark.asyncio
async def test_projection_preserves_authored_identity_disclosure_in_serving_config():
    db = Database()
    entry = {**character(), "emotion_config": {"identity_disclosure": "transparent_ai"}}
    result = await CharacterProjectionService(db).project(BRAND, USER, [entry])
    config = db.characters[result["character_map"]["luna"]]["emotion_config"]
    assert config["identity_disclosure"] == "transparent_ai"
    assert config["runtime_projection"]["agent_id"] == "luna"
    assert config["runtime_projection"]["config"] == entry


@pytest.mark.asyncio
async def test_profile_and_relational_create_memory_return_the_inserted_id():
    db = Database()
    memory = MemoryService(db, llm=None, cache=None)
    memory._has_new_schema = AsyncMock(return_value=True)
    memory._upsert_profile_memory = AsyncMock(return_value="profile-row")
    memory._insert_relational_memory = AsyncMock(return_value="relationship-row")
    for layer, expected in (("PROFILE", "profile-row"), ("RELATIONAL", "relationship-row")):
        result = await memory.create_memory(
            {
                "user_id": USER,
                "character_id": character_id_for_agent(BRAND, "luna"),
                "memory_type": layer,
                "content": "用户喜欢直接回答",
            }
        )
        assert result["id"] == expected and result["status"] == "created"


def test_projection_routes_require_service_brand_before_database_access(monkeypatch):
    get_pool = AsyncMock(side_effect=AssertionError("must reject before touching the database"))
    monkeypatch.setattr(api, "get_pool", get_pool)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        response = client.post("/runtime/resolve", json={"user_id": USER, "agent_id": "luna"})
    assert response.status_code == 403
    get_pool.assert_not_awaited()
