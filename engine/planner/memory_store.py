"""MemoryStore: character identity, relationships and long-term memory keyed by
agent_id — deliberately decoupled from body_id.

A character that talks to the user in Unity, then wakes up inside a robot,
carries the same relationships and memories: bodies hold only short-lived
execution state, the store holds the person.

Layers mirror the existing ai-core five-layer system
(PROFILE / EPISODIC / SEMANTIC / RELATIONAL / COMPILED_BEHAVIOR); this module
adds NO third memory implementation — `AICoreMemoryStore` is a thin HTTP
adapter to that service, and `InMemoryMemoryStore` is the test/offline stand-in.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

MEMORY_LAYERS = ("profile", "episodic", "semantic", "relational", "compiled_behavior")


@runtime_checkable
class MemoryStore(Protocol):
    def get_relationships(self, agent_id: str) -> dict[str, float]: ...
    def set_relationship(self, agent_id: str, other: str, value: float) -> None: ...
    def remember(self, agent_id: str, layer: str, key: str, value: Any) -> None: ...
    def recall(self, agent_id: str, layer: str) -> dict[str, Any]: ...


@dataclass
class InMemoryMemoryStore:
    """Reference implementation for tests and offline runs. Same contract,
    zero persistence — production paths should inject AICoreMemoryStore."""

    _relationships: dict[str, dict[str, float]] = field(default_factory=dict)
    _layers: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def get_relationships(self, agent_id: str) -> dict[str, float]:
        return dict(self._relationships.get(agent_id, {}))

    def set_relationship(self, agent_id: str, other: str, value: float) -> None:
        self._relationships.setdefault(agent_id, {})[other] = max(0.0, min(1.0, value))

    def remember(self, agent_id: str, layer: str, key: str, value: Any) -> None:
        if layer not in MEMORY_LAYERS:
            raise ValueError(f"unknown memory layer {layer!r}; expected one of {MEMORY_LAYERS}")
        self._layers.setdefault((agent_id, layer), {})[key] = value

    def recall(self, agent_id: str, layer: str) -> dict[str, Any]:
        if layer not in MEMORY_LAYERS:
            raise ValueError(f"unknown memory layer {layer!r}; expected one of {MEMORY_LAYERS}")
        return dict(self._layers.get((agent_id, layer), {}))


class AICoreMemoryStore:
    """Adapter to the existing ai-core five-layer memory service.

    Status: PROTOTYPE — requires a running ai-core instance (asyncpg-backed).
    Endpoints used: POST /memory (create), POST /memory/retrieve.
    Relationship state rides the RELATIONAL layer with stable keys, so the
    planner needs no second relationship system.
    """

    def __init__(self, base_url: str, character_map: dict[str, str] | None = None,
                 timeout_s: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.character_map = character_map or {}   # agent_id -> ai-core character_id
        self.timeout_s = timeout_s

    def _character(self, agent_id: str) -> str:
        return self.character_map.get(agent_id, agent_id)

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_relationships(self, agent_id: str) -> dict[str, float]:
        data = self._post("/memory/retrieve", {
            "character_id": self._character(agent_id),
            "query": "relationship_state",
            "layers": ["RELATIONAL"],
        })
        relationships: dict[str, float] = {}
        for memory in data.get("memories", []):
            content = memory.get("content", "")
            if content.startswith("relationship:"):
                try:
                    _, other, value = content.split(":", 2)
                    relationships[other] = float(value)
                except ValueError:
                    continue
        return relationships

    def set_relationship(self, agent_id: str, other: str, value: float) -> None:
        self._post("/memory", {
            "character_id": self._character(agent_id),
            "layer": "RELATIONAL",
            "content": f"relationship:{other}:{max(0.0, min(1.0, value)):.4f}",
        })

    def remember(self, agent_id: str, layer: str, key: str, value: Any) -> None:
        self._post("/memory", {
            "character_id": self._character(agent_id),
            "layer": layer.upper() if layer != "compiled_behavior" else "SEMANTIC",
            "content": f"{key}: {json.dumps(value, ensure_ascii=False)}",
        })

    def recall(self, agent_id: str, layer: str) -> dict[str, Any]:
        data = self._post("/memory/retrieve", {
            "character_id": self._character(agent_id),
            "query": "*",
            "layers": [layer.upper()],
        })
        out: dict[str, Any] = {}
        for memory in data.get("memories", []):
            content = memory.get("content", "")
            key, _, raw = content.partition(": ")
            if key:
                try:
                    out[key] = json.loads(raw) if raw else raw
                except json.JSONDecodeError:
                    out[key] = raw
        return out
