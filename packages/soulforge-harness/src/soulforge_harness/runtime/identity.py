"""Canonical identities shared by cognition, life runtime and body transports.

An agent slug identifies a roster entry, a character UUID identifies its tenant
projection, and a user UUID owns the relationship and memories. Bodies and
sessions are routing context: changing either never changes the person.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from uuid import UUID, uuid5

_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


def validate_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str) or not _AGENT.fullmatch(agent_id):
        raise ValueError("agent_id must be a 1-64 character roster identifier")
    return agent_id


def character_id_for_agent(brand_id: str, agent_id: str) -> str:
    """Stable identity for a new file-authored character within one brand."""
    return str(
        uuid5(UUID(str(brand_id)), "soulforge:character:" + validate_agent_id(agent_id))
    )


def runtime_user_id(brand_id: str, local_user: str = "default") -> str:
    """Stable local household user; explicit authenticated user IDs take precedence."""
    if not isinstance(local_user, str) or not local_user or len(local_user) > 128:
        raise ValueError("local_user must contain 1-128 characters")
    return str(uuid5(UUID(str(brand_id)), "soulforge:user:" + local_user))


@dataclass(frozen=True)
class RuntimeIdentity:
    user_id: str
    character_id: str
    agent_id: str
    body_id: str = ""
    session_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", str(UUID(str(self.user_id))))
        object.__setattr__(self, "character_id", str(UUID(str(self.character_id))))
        validate_agent_id(self.agent_id)
        for name in ("body_id", "session_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 128:
                raise ValueError(f"{name} must be a string of at most 128 characters")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
