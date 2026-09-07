"""Connection session manager backed by Redis with DB fallback."""

import json
import uuid
import logging
from dataclasses import dataclass, field

import asyncpg
import redis.asyncio as redis

from gateway.config import settings

logger = logging.getLogger(__name__)


class DeviceRegistryUnavailable(RuntimeError):
    """Device ownership could not be checked against the authoritative registry."""


def _runtime_owner() -> tuple[str, str] | None:
    if not (settings.character_runtime_url and settings.soulforge_brand_id):
        return None
    from soulforge_harness.runtime.identity import runtime_user_id

    brand = str(uuid.UUID(settings.soulforge_brand_id))
    user = str(uuid.UUID(settings.soulforge_user_id or runtime_user_id(brand)))
    return brand, user


def _validate_runtime_owner(info: dict) -> None:
    owner = _runtime_owner()
    if owner is None:
        return
    brand, user = owner
    if info.get("brand_id") and info["brand_id"] != brand:
        raise PermissionError("Device belongs to a different runtime brand")
    if info.get("end_user_id") and info["end_user_id"] != user:
        raise PermissionError("Device belongs to a different runtime user")


@dataclass
class Session:
    session_id: str
    device_id: str
    character_id: str | None = None
    end_user_id: str | None = None
    brand_id: str | None = None
    protocol: str = ""
    history: list[dict] = field(default_factory=list)


class SessionManager:
    def __init__(self):
        self.redis: redis.Redis | None = None
        self._local_sessions: dict[str, Session] = {}
        self._db_pool: asyncpg.Pool | None = None

    async def connect(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            self._db_pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=1,
                max_size=3,
            )
        except Exception as e:
            logger.warning("session.db_pool_failed: %s", e)

    async def _load_device_from_db(self, device_id: str) -> dict | None:
        """Fallback: load device info from PostgreSQL when Redis cache misses.

        Device schema: id (VARCHAR PK), character_id, end_user_id, device_secret.
        brand_id comes from the linked character.
        """
        if not self._db_pool:
            return None
        try:
            row = await self._db_pool.fetchrow(
                """SELECT d.character_id, d.end_user_id, d.device_secret,
                          c.brand_id
                   FROM devices d
                   LEFT JOIN characters c ON c.id = d.character_id
                   WHERE d.id = $1""",
                device_id,
            )
            if not row:
                return None
            info = {
                "character_id": str(row["character_id"]) if row["character_id"] else None,
                "end_user_id": str(row["end_user_id"]) if row["end_user_id"] else None,
                "brand_id": str(row["brand_id"]) if row["brand_id"] else None,
                "device_secret": row["device_secret"],
            }
            await self._cache_device_info(device_id, info)
            return info
        except Exception as e:
            logger.warning("session.db_lookup_failed: %s", e)
            if _runtime_owner() is not None:
                raise DeviceRegistryUnavailable("Device ownership registry is unavailable") from e
            return None

    async def _cache_device_info(self, device_id: str, info: dict) -> None:
        if self.redis:
            try:
                await self.redis.setex(
                    f"device:{device_id}", settings.session_ttl_seconds, json.dumps(info)
                )
            except Exception as exc:
                # A failed cache write must not turn a known DB owner into an
                # apparently unknown device that is then auto-registered.
                logger.warning("session.device_cache_failed: %s", type(exc).__name__)

    async def _auto_register_device(self, device_id: str) -> dict | None:
        """Auto-register an unknown device with a default character.

        Unified mode uses this installation's projected character and user.
        Legacy mode picks the first PUBLISHED character in the DB as default.
        Only runs in non-production environments.
        """
        if settings.environment == "production":
            return None
        if not self._db_pool:
            return None
        owner = _runtime_owner()
        try:
            if owner is not None:
                brand, user = owner
                rows = await self._db_pool.fetch(
                    """SELECT c.id AS character_id, c.brand_id
                       FROM characters c
                       WHERE c.status = 'PUBLISHED' AND c.brand_id = $1
                         AND c.emotion_config->'runtime_projection'->>'agent_id' = $2
                         AND EXISTS (SELECT 1 FROM end_users WHERE id = $3)
                       LIMIT 2""",
                    uuid.UUID(brand),
                    settings.character_runtime_agent,
                    uuid.UUID(user),
                )
                if len(rows) != 1:
                    raise DeviceRegistryUnavailable(
                        "Runtime character or user projection is unavailable"
                    )
                char_row = rows[0]
            else:
                char_row = await self._db_pool.fetchrow(
                    """SELECT c.id AS character_id, c.brand_id
                       FROM characters c
                       WHERE c.status = 'PUBLISHED'
                       ORDER BY c.created_at DESC
                       LIMIT 1""",
                )
            if not char_row:
                logger.warning("session.auto_register: no published characters found")
                return None

            if owner is not None:
                await self._db_pool.execute(
                    """INSERT INTO devices
                       (id, device_type, character_id, end_user_id, status, created_at, updated_at)
                       VALUES ($1, 'toy', $2, $3, 'ACTIVE', now(), now())
                       ON CONFLICT (id) DO NOTHING""",
                    device_id,
                    char_row["character_id"],
                    uuid.UUID(owner[1]),
                )
            else:
                await self._db_pool.execute(
                    """INSERT INTO devices (id, device_type, character_id, status, created_at, updated_at)
                       VALUES ($1, 'toy', $2, 'ACTIVE', now(), now())
                       ON CONFLICT (id) DO NOTHING""",
                    device_id,
                    char_row["character_id"],
                )

            # A concurrent registration may have won ON CONFLICT. Always use
            # its real owner; never cache the identity we merely attempted.
            info = await self._load_device_from_db(device_id)
            if not info:
                raise DeviceRegistryUnavailable("Registered device could not be read back")
            _validate_runtime_owner(info)

            logger.info(
                "session.auto_registered device=%s character=%s",
                device_id,
                info["character_id"],
            )
            return info
        except (PermissionError, DeviceRegistryUnavailable):
            raise
        except Exception as e:
            logger.warning("session.auto_register_failed: %s", type(e).__name__)
            if owner is not None:
                raise DeviceRegistryUnavailable("Device registration is unavailable") from e
            return None

    async def load_device_info(self, device_id: str) -> dict | None:
        """Load device info from Redis → DB → auto-register if unknown.

        Used by both session creation and device authentication.
        """
        if _runtime_owner() is not None:
            # Ownership may have changed since an unowned Redis entry was
            # cached. In unified mode the DB is authoritative at connection.
            if self._db_pool is None:
                raise DeviceRegistryUnavailable("Device ownership registry is unavailable")
            info = await self._load_device_from_db(device_id)
            if info is None:
                info = await self._auto_register_device(device_id)
            if info is not None:
                _validate_runtime_owner(info)
            return info

        # Try Redis first
        if self.redis:
            raw = await self.redis.get(f"device:{device_id}")
            if raw:
                return json.loads(raw)

        # Fallback to DB
        info = await self._load_device_from_db(device_id)
        if info:
            return info

        # Auto-register unknown device with default character
        return await self._auto_register_device(device_id)

    async def create_session(self, device_id: str, protocol: str) -> Session:
        """Create a new session for a device connection."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            device_id=device_id,
            protocol=protocol,
        )

        device_info = await self.load_device_info(device_id)
        owner = _runtime_owner()
        if device_info:
            _validate_runtime_owner(device_info)
            session.character_id = device_info.get("character_id")
            session.end_user_id = device_info.get("end_user_id")
            session.brand_id = device_info.get("brand_id")
            if owner is not None:
                # Existing unowned local devices share the installation user
                # for this session. Their device row and old memories stay put.
                session.brand_id = session.brand_id or owner[0]
                session.end_user_id = session.end_user_id or owner[1]
        elif owner is not None:
            raise PermissionError("Device is not registered for this runtime")

        # Store session in Redis
        if self.redis:
            await self.redis.setex(
                f"session:{session_id}",
                settings.session_ttl_seconds,
                json.dumps(
                    {
                        "device_id": device_id,
                        "character_id": session.character_id,
                        "end_user_id": session.end_user_id,
                        "brand_id": session.brand_id,
                        "protocol": protocol,
                    }
                ),
            )

        self._local_sessions[session_id] = session
        return session

    async def get_session(self, session_id: str) -> Session | None:
        return self._local_sessions.get(session_id)

    async def remove_session(self, session_id: str):
        self._local_sessions.pop(session_id, None)
        if self.redis:
            await self.redis.delete(f"session:{session_id}")

    async def add_to_history(self, session_id: str, role: str, content: str):
        session = self._local_sessions.get(session_id)
        if session:
            session.history.append({"role": role, "content": content})
            if len(session.history) > 20:
                session.history = session.history[-20:]
