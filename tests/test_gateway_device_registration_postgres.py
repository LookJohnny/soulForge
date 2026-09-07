"""Opt-in real SQL validation; all synthetic device/identity writes roll back."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from dotenv import dotenv_values

from ai_core.services.character_projection import CharacterProjectionService
from gateway.config import settings
from gateway.session import SessionManager

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_DEVICE_INTEGRATION") != "1",
        reason="opt-in local PostgreSQL transaction rollback test",
    ),
]


class TransactionPool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


async def test_registration_uses_projected_scope_and_preserves_existing_owners(
    monkeypatch,
):
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    database_url = env.get("DATABASE_URL")
    if not database_url or urlsplit(database_url).hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        pytest.fail(
            "Device integration is restricted to local PostgreSQL", pytrace=False
        )
    connection = await asyncpg.connect(database_url, timeout=5)
    brand, other_brand, user, other_user = (str(uuid4()) for _ in range(4))
    device_ids = [f"registration-test-{uuid4()}" for _ in range(3)]
    transaction = connection.transaction()
    await transaction.start()
    try:
        projection = CharacterProjectionService(TransactionPool(connection))
        first = await projection.project(
            brand, user, [{"id": "probe", "name": "Isolated primary", "energy": 0.5}]
        )
        second = await projection.project(
            other_brand,
            other_user,
            [{"id": "probe", "name": "Isolated other brand", "energy": 0.5}],
        )
        character = first["character_map"]["probe"]
        other_character = second["character_map"]["probe"]
        # This would win the old global "latest published character" lookup.
        await connection.execute(
            "UPDATE characters SET created_at=now()+interval '1 hour' WHERE id=$1",
            other_character,
        )
        monkeypatch.setattr(settings, "environment", "development")
        monkeypatch.setattr(settings, "character_runtime_url", "ws://127.0.0.1:1")
        monkeypatch.setattr(settings, "character_runtime_agent", "probe")
        monkeypatch.setattr(settings, "soulforge_brand_id", brand)
        monkeypatch.setattr(settings, "soulforge_user_id", user)
        manager = SessionManager()
        manager._db_pool = connection

        info = await manager._auto_register_device(device_ids[0])
        assert info is not None
        assert info["character_id"] == character
        assert info["brand_id"] == brand
        assert info["end_user_id"] == user
        saved = await connection.fetchrow(
            "SELECT character_id, end_user_id FROM devices WHERE id=$1", device_ids[0]
        )
        assert str(saved["character_id"]) == character
        assert str(saved["end_user_id"]) == user

        # Simulate a conflicting registration winning before this insertion.
        await connection.execute(
            "INSERT INTO devices (id, character_id, end_user_id, created_at, updated_at) "
            "VALUES ($1, $2, $3, now(), now())",
            device_ids[1],
            other_character,
            other_user,
        )
        try:
            conflicting = await manager._auto_register_device(device_ids[1])
        except PermissionError:
            conflicting = None
        if conflicting is not None:
            assert conflicting["end_user_id"] == other_user
            assert conflicting["brand_id"] == other_brand
        saved = await connection.fetchrow(
            "SELECT character_id, end_user_id FROM devices WHERE id=$1", device_ids[1]
        )
        assert str(saved["character_id"]) == other_character
        assert str(saved["end_user_id"]) == other_user

        # Existing unowned toys retain their DB row; session binding is separate.
        await connection.execute(
            "INSERT INTO devices (id, character_id, created_at, updated_at) "
            "VALUES ($1, $2, now(), now())",
            device_ids[2],
            character,
        )
        info = await manager.load_device_info(device_ids[2])
        assert info and info["character_id"] == character
        assert (
            await connection.fetchval(
                "SELECT end_user_id FROM devices WHERE id=$1", device_ids[2]
            )
            is None
        )
    finally:
        await transaction.rollback()
        try:
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM devices WHERE id=ANY($1::text[])", device_ids
                )
                == 0
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM brands WHERE id=ANY($1::uuid[])",
                    [brand, other_brand],
                )
                == 0
            )
        finally:
            await connection.close()
