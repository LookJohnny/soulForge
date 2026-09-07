"""Installation-local registration never claims another stored device owner."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from gateway.config import settings
from gateway.session import DeviceRegistryUnavailable, SessionManager


class Registry:
    def __init__(self, characters, users):
        self.characters = characters
        self.users = users
        self.devices = {}
        self.inserts = []
        self.queries = []
        self.on_insert = None
        self.fail = False

    async def fetch(self, sql, brand, agent, user):
        assert "c.brand_id = $1" in sql
        assert "runtime_projection'->>'agent_id' = $2" in sql
        assert "EXISTS (SELECT 1 FROM end_users WHERE id = $3)" in sql
        self.queries.append((sql, brand, agent, user))
        return [
            {"character_id": c["id"], "brand_id": c["brand_id"]}
            for c in self.characters
            if c["brand_id"] == str(brand)
            and c["agent_id"] == agent
            and c["status"] == "PUBLISHED"
            and str(user) in self.users
        ][:2]

    async def fetchrow(self, sql, *args):
        if self.fail:
            raise RuntimeError("test registry unavailable")
        if "FROM devices d" in sql:
            row = self.devices.get(args[0])
            if row is None:
                return None
            character = next(
                (c for c in self.characters if c["id"] == row["character_id"]), {}
            )
            return {**row, "brand_id": character.get("brand_id")}
        assert "ORDER BY c.created_at DESC" in sql
        character = max(self.characters, key=lambda c: c["created_at"])
        return {"character_id": character["id"], "brand_id": character["brand_id"]}

    async def execute(self, sql, device_id, character_id, *user):
        assert "INSERT INTO devices" in sql and "ON CONFLICT (id) DO NOTHING" in sql
        self.inserts.append(
            (device_id, str(character_id), str(user[0]) if user else None)
        )
        if self.on_insert:
            self.on_insert(device_id)
        # Emulate the actual insert-only ownership rule, including a competing
        # registration that wins between the initial lookup and this statement.
        self.devices.setdefault(
            device_id,
            {
                "character_id": str(character_id),
                "end_user_id": str(user[0]) if user else None,
                "device_secret": None,
            },
        )
        return "INSERT 0 1"


class Cache:
    def __init__(self):
        self.data = {}
        self.fail = False

    async def get(self, key):
        return self.data.get(key)

    async def setex(self, key, ttl, value):
        if self.fail:
            raise RuntimeError("test cache unavailable")
        self.data[key] = value


@pytest.fixture
def installation(monkeypatch):
    brand, user, other_brand, other_user = (str(uuid4()) for _ in range(4))
    current, previous, foreign = (str(uuid4()) for _ in range(3))
    for key, value in {
        "environment": "development",
        "character_runtime_url": "ws://unused.invalid",
        "character_runtime_agent": "kai",
        "soulforge_brand_id": brand,
        "soulforge_user_id": user,
    }.items():
        monkeypatch.setattr(settings, key, value)
    db = Registry(
        [
            {
                "id": current,
                "brand_id": brand,
                "agent_id": "kai",
                "status": "PUBLISHED",
                "created_at": 1,
            },
            {
                "id": previous,
                "brand_id": brand,
                "agent_id": "luna",
                "status": "PUBLISHED",
                "created_at": 2,
            },
            {
                "id": foreign,
                "brand_id": other_brand,
                "agent_id": "kai",
                "status": "PUBLISHED",
                "created_at": 99,
            },
        ],
        {user, other_user},
    )
    manager = SessionManager()
    manager._db_pool, manager.redis = db, Cache()
    return SimpleNamespace(
        manager=manager,
        db=db,
        brand=brand,
        user=user,
        current=current,
        previous=previous,
        foreign=foreign,
        other_brand=other_brand,
        other_user=other_user,
    )


@pytest.mark.asyncio
async def test_unknown_device_registers_projected_character_and_installation_user(
    installation,
):
    x = installation
    session = await x.manager.create_session("new-esp32", "xiaozhi")
    assert session.brand_id == x.brand and session.end_user_id == x.user
    assert (
        session.character_id == x.current
    )  # not the globally newest foreign character
    assert x.db.devices["new-esp32"]["end_user_id"] == x.user
    assert x.db.inserts == [("new-esp32", x.current, x.user)]
    assert (
        json.loads(x.manager.redis.data[f"session:{session.session_id}"])["end_user_id"]
        == x.user
    )


@pytest.mark.asyncio
async def test_existing_unowned_local_device_gets_session_user_without_database_reassignment(
    installation,
):
    x = installation
    x.db.devices["old-esp32"] = {
        "character_id": x.previous,
        "end_user_id": None,
        "device_secret": "fixture-secret",
    }
    before = copy.deepcopy(x.db.devices)
    session = await x.manager.create_session("old-esp32", "xiaozhi")
    assert session.end_user_id == x.user and session.brand_id == x.brand
    assert session.character_id == x.previous
    assert x.db.devices == before and not x.db.inserts
    assert json.loads(x.manager.redis.data["device:old-esp32"])["end_user_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("different_brand", [False, True])
async def test_existing_foreign_owner_or_brand_is_never_reassigned_even_with_unowned_cache(
    installation,
    different_brand,
):
    x = installation
    x.db.devices["owned"] = {
        "character_id": x.foreign if different_brand else x.current,
        "end_user_id": None if different_brand else x.other_user,
        "device_secret": "fixture-secret",
    }
    x.manager.redis.data["device:owned"] = json.dumps(
        {
            "character_id": x.current,
            "brand_id": x.brand,
            "end_user_id": None,
        }
    )
    before = copy.deepcopy(x.db.devices)
    with pytest.raises(PermissionError, match="different runtime"):
        await x.manager.create_session("owned", "xiaozhi")
    assert x.db.devices == before and not x.db.inserts
    assert not x.manager._local_sessions


@pytest.mark.asyncio
async def test_insert_conflict_reads_winning_owner_instead_of_caching_attempted_identity(
    installation,
):
    x = installation
    winning = {
        "character_id": x.foreign,
        "end_user_id": x.other_user,
        "device_secret": "winner",
    }
    x.db.on_insert = lambda device: x.db.devices.setdefault(
        device, copy.deepcopy(winning)
    )
    with pytest.raises(PermissionError):
        await x.manager.load_device_info("racing-device")
    assert x.db.devices["racing-device"] == winning
    cached = json.loads(x.manager.redis.data["device:racing-device"])
    assert cached["end_user_id"] == x.other_user and cached["brand_id"] == x.other_brand


@pytest.mark.asyncio
@pytest.mark.parametrize("no_pool", [False, True])
async def test_registry_failure_does_not_create_an_unowned_session_or_trust_stale_cache(
    installation, no_pool
):
    x = installation
    x.manager.redis.data["device:offline"] = json.dumps(
        {"brand_id": x.brand, "end_user_id": None}
    )
    if no_pool:
        x.manager._db_pool = None
    else:
        x.db.fail = True
    with pytest.raises(DeviceRegistryUnavailable):
        await x.manager.create_session("offline", "xiaozhi")
    assert not x.db.inserts and not x.manager._local_sessions


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["user", "character", "duplicate_character"])
async def test_registration_requires_existing_unambiguous_runtime_projection(
    installation, missing
):
    x = installation
    if missing == "user":
        x.db.users.remove(x.user)
    elif missing == "character":
        x.db.characters = [c for c in x.db.characters if c["id"] != x.current]
    else:
        duplicate = {**x.db.characters[0], "id": str(uuid4())}
        x.db.characters.append(duplicate)
    with pytest.raises(DeviceRegistryUnavailable):
        await x.manager.load_device_info("new")
    assert not x.db.devices and not x.db.inserts


@pytest.mark.asyncio
async def test_production_does_not_auto_register_unknown_device(
    installation, monkeypatch
):
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(PermissionError, match="not registered"):
        await installation.manager.create_session(
            "unknown-production-device", "xiaozhi"
        )
    assert not installation.db.inserts


@pytest.mark.asyncio
async def test_legacy_registration_remains_unowned_when_runtime_is_disabled(
    installation, monkeypatch
):
    monkeypatch.setattr(settings, "character_runtime_url", "")
    session = await installation.manager.create_session("legacy", "xiaozhi")
    assert session.end_user_id is None
    assert session.character_id == installation.foreign


@pytest.mark.asyncio
async def test_failed_cache_backfill_does_not_hide_a_real_owner(installation):
    x = installation
    x.db.devices["owned"] = {
        "character_id": x.current,
        "end_user_id": x.other_user,
        "device_secret": None,
    }
    x.manager.redis.fail = True
    with pytest.raises(PermissionError):
        await x.manager.load_device_info("owned")
    assert not x.db.inserts


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable,code", [(False, 4003), (True, 1013)])
async def test_websocket_reports_ownership_or_registry_failure_before_runtime_access(
    installation, monkeypatch, unavailable, code
):
    from gateway import server as module

    x = installation
    x.db.devices["esp32"] = {
        "character_id": x.current,
        "end_user_id": x.other_user,
        "device_secret": None,
    }
    x.db.fail = unavailable
    server = module.WebSocketServer.__new__(module.WebSocketServer)
    server.session_manager = x.manager
    server.orchestrator = SimpleNamespace(bind_runtime_session=AsyncMock())
    server._verify_device = AsyncMock(return_value=True)
    ws = SimpleNamespace(
        accept=AsyncMock(),
        receive=AsyncMock(return_value={"text": '{"type":"hello"}'}),
        close=AsyncMock(),
    )
    adapter = SimpleNamespace(handshake=AsyncMock(return_value="esp32"), name="xiaozhi")
    monkeypatch.setattr(module.registry, "detect", AsyncMock(return_value=adapter))
    await server.handle_connection(ws)
    assert ws.close.await_args.kwargs["code"] == code
    server.orchestrator.bind_runtime_session.assert_not_awaited()
