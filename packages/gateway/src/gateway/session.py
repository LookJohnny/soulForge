"""Connection session manager backed by Redis."""

import json
import uuid
from dataclasses import dataclass, field

import redis.asyncio as redis

from gateway.config import settings


@dataclass
class Session:
    session_id: str
    device_id: str
    character_id: str | None = None
    end_user_id: str | None = None
    protocol: str = ""
    history: list[dict] = field(default_factory=list)


class SessionManager:
    def __init__(self):
        self.redis: redis.Redis | None = None
        self._local_sessions: dict[str, Session] = {}  # ws_id -> Session

    async def connect(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def create_session(self, device_id: str, protocol: str) -> Session:
        """Create a new session for a device connection."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            device_id=device_id,
            protocol=protocol,
        )

        # Load device info from Redis cache or DB
        if self.redis:
            device_info = await self.redis.get(f"device:{device_id}")
            if device_info:
                info = json.loads(device_info)
                session.character_id = info.get("character_id")
                session.end_user_id = info.get("end_user_id")

            # Store session
            await self.redis.setex(
                f"session:{session_id}",
                settings.session_ttl_seconds,
                json.dumps({
                    "device_id": device_id,
                    "character_id": session.character_id,
                    "end_user_id": session.end_user_id,
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
            # Keep last 10 turns
            if len(session.history) > 20:
                session.history = session.history[-20:]
