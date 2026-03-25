"""Connection session manager backed by Redis with DB fallback."""

import json
import uuid
import logging
from dataclasses import dataclass, field

import asyncpg
import redis.asyncio as redis

from gateway.config import settings

logger = logging.getLogger(__name__)


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
                settings.database_url, min_size=1, max_size=3,
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
            # Backfill Redis cache
            if self.redis:
                await self.redis.setex(
                    f"device:{device_id}",
                    settings.session_ttl_seconds,
                    json.dumps(info),
                )
            return info
        except Exception as e:
            logger.warning("session.db_lookup_failed: %s", e)
            return None

    async def load_device_info(self, device_id: str) -> dict | None:
        """Load device info from Redis, falling back to DB.

        Used by both session creation and device authentication.
        """
        # Try Redis first
        if self.redis:
            raw = await self.redis.get(f"device:{device_id}")
            if raw:
                return json.loads(raw)

        # Fallback to DB
        return await self._load_device_from_db(device_id)

    async def create_session(self, device_id: str, protocol: str) -> Session:
        """Create a new session for a device connection."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            device_id=device_id,
            protocol=protocol,
        )

        device_info = await self.load_device_info(device_id)
        if device_info:
            session.character_id = device_info.get("character_id")
            session.end_user_id = device_info.get("end_user_id")
            session.brand_id = device_info.get("brand_id")

        # Store session in Redis
        if self.redis:
            await self.redis.setex(
                f"session:{session_id}",
                settings.session_ttl_seconds,
                json.dumps({
                    "device_id": device_id,
                    "character_id": session.character_id,
                    "end_user_id": session.end_user_id,
                    "brand_id": session.brand_id,
                    "protocol": protocol,
                }),
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
