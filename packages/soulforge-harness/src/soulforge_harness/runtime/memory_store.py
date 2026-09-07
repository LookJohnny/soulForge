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
            raise ValueError(
                f"unknown memory layer {layer!r}; expected one of {MEMORY_LAYERS}"
            )
        self._layers.setdefault((agent_id, layer), {})[key] = value

    def recall(self, agent_id: str, layer: str) -> dict[str, Any]:
        if layer not in MEMORY_LAYERS:
            raise ValueError(
                f"unknown memory layer {layer!r}; expected one of {MEMORY_LAYERS}"
            )
        return dict(self._layers.get((agent_id, layer), {}))


class AICoreMemoryStore:
    """Persistent ai-core state with an in-process view and ordered async writes.

    Startup calls ``project_characters`` and ``bootstrap`` off the event loop.
    Afterwards every MemoryStore method is local: no tick, conversation or
    reflection waits on HTTP. ``flush`` and ``health`` expose persistence lag;
    failed writes retain their FIFO position and retry rather than disappearing.
    With ``outbox_path``, each write is committed to SQLite before returning;
    unacknowledged entries survive process exits and are replayed on bootstrap.
    """

    def __init__(
        self,
        base_url: str,
        character_map: dict[str, str] | None = None,
        timeout_s: float = 5.0,
        *,
        service_token: str,
        brand_id: str,
        user_id: str,
        body_id: str = "",
        session_id: str = "",
        queue_limit: int = 4096,
        outbox_path: str | None = None,
    ):
        import queue
        import threading
        from uuid import UUID

        if not service_token:
            raise ValueError("AICoreMemoryStore requires a service token")
        if timeout_s <= 0 or queue_limit < 1:
            raise ValueError("timeout_s and queue_limit must be positive")
        self.base_url = base_url.rstrip("/")
        self.character_map = dict(character_map or {})
        self.timeout_s = timeout_s
        self._service_token = service_token
        self.brand_id = str(UUID(str(brand_id)))
        self.user_id = str(UUID(str(user_id)))
        self.body_id, self.session_id = body_id or "", session_id or ""
        self._layers: dict[tuple[str, str], dict[str, Any]] = {}
        self._bootstrapped: set[str] = set()
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=queue_limit)
        self._stop = threading.Event()
        self._thread = None
        self._last_error: str | None = None
        self._writes_completed = 0
        self._writes_blocked = 0
        self._blocked_keys: set[tuple[str, str, str]] = set()
        self._closed = False
        self._outbox = None
        self._durable_outbox = outbox_path is not None
        self._pending: dict[int, dict] = {}
        self._next_sequence = 0
        if outbox_path is not None:
            self._load_outbox(outbox_path, queue_limit)

    def _load_outbox(self, outbox_path: str, queue_limit: int) -> None:
        import queue
        import sqlite3
        from pathlib import Path

        from soulforge_harness.runtime.identity import RuntimeIdentity

        path = Path(outbox_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(str(path), check_same_thread=False)
        try:
            path.chmod(0o600)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS owner "
                "(id INTEGER PRIMARY KEY CHECK (id=1), brand_id TEXT, user_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outbox "
                "(seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO owner (id, brand_id, user_id) VALUES (1, ?, ?)",
                (self.brand_id, self.user_id),
            )
            owner = connection.execute(
                "SELECT brand_id, user_id FROM owner WHERE id=1"
            ).fetchone()
            if owner != (self.brand_id, self.user_id):
                raise ValueError("outbox belongs to a different brand or user")
            connection.commit()
            rows = connection.execute(
                "SELECT seq, payload FROM outbox ORDER BY seq"
            ).fetchall()
            self._queue = queue.Queue(maxsize=max(queue_limit, len(rows)))
            for seq, raw in rows:
                payload = json.loads(raw)
                identity = RuntimeIdentity(**payload["identity"])
                if (
                    identity.user_id != self.user_id
                    or payload["layer"] not in MEMORY_LAYERS
                ):
                    raise ValueError("invalid identity or layer in runtime outbox")
                existing = self.character_map.setdefault(
                    identity.agent_id, identity.character_id
                )
                if existing != identity.character_id:
                    raise ValueError(
                        "outbox character identity conflicts with character_map"
                    )
                self._pending[seq] = payload
                self._queue.put_nowait((seq, payload))
            self._outbox = connection
        except BaseException:
            connection.close()
            raise

    def _start_writer(self) -> None:
        import threading

        # Caller holds _lock. Recovered writes start only after startup bootstrap.
        if self._thread is None and self._pending and not self._closed:
            self._thread = threading.Thread(
                target=self._write_loop, name="runtime-memory-writer", daemon=True
            )
            self._thread.start()

    def identity(self, agent_id: str):
        from soulforge_harness.runtime.identity import (
            RuntimeIdentity,
            character_id_for_agent,
        )

        with self._lock:
            character = self.character_map.get(agent_id)
        return RuntimeIdentity(
            user_id=self.user_id,
            character_id=character or character_id_for_agent(self.brand_id, agent_id),
            agent_id=agent_id,
            body_id=self.body_id,
            session_id=self.session_id,
        )

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            ),
            headers={
                "Content-Type": "application/json",
                "X-Service-Token": self._service_token,
                "X-Brand-ID": self.brand_id,
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("runtime state API must return a JSON object")
        return data

    def project_characters(
        self, characters: list[dict], brand_name: str = "SoulForge"
    ) -> dict:
        """Upsert the authored roster before serving; caller runs this off-loop."""
        data = self._post(
            "/runtime/characters/project",
            {
                "characters": characters,
                "user_id": self.user_id,
                "brand_name": brand_name,
            },
        )
        mapping = data.get("character_map")
        if not isinstance(mapping, dict):
            raise ValueError("character projection returned no character_map")
        from soulforge_harness.runtime.identity import RuntimeIdentity

        for agent_id, character_id in mapping.items():
            RuntimeIdentity(self.user_id, character_id, agent_id)
        with self._lock:
            for payload in self._pending.values():
                identity = payload["identity"]
                projected = mapping.get(identity["agent_id"])
                if projected is not None and projected != identity["character_id"]:
                    raise ValueError(
                        "projection conflicts with a pending character identity"
                    )
            self.character_map.update(mapping)
        return data

    def bootstrap(self, agent_ids: list[str]) -> None:
        """Load every persisted key, including inter-character relationships.

        This is startup/roster-loading I/O, not a retrieval operation on ticks.
        Existing agents are not refreshed underneath pending local mutations.
        """
        for agent_id in agent_ids:
            with self._lock:
                if agent_id in self._bootstrapped:
                    continue
            layers = {}
            blocked_keys = set()
            for layer in MEMORY_LAYERS:
                data = self._post(
                    "/runtime/memory/recall",
                    {"identity": self.identity(agent_id).to_dict(), "layer": layer},
                )
                values = data.get("values")
                if not isinstance(values, dict):
                    raise ValueError("runtime memory recall returned no values")
                blocked = data.get("blocked_keys", [])
                if not isinstance(blocked, list) or any(
                    not isinstance(k, str) for k in blocked
                ):
                    raise ValueError(
                        "runtime memory recall returned invalid blocked_keys"
                    )
                blocked_keys.update((agent_id, layer, key) for key in blocked)
                layers[(agent_id, layer)] = values
            with self._lock:
                self._layers.update(layers)
                self._blocked_keys.update(blocked_keys)
                for agent, layer, key in blocked_keys:
                    self._layers[(agent, layer)].pop(key, None)
                # The acknowledged server snapshot may precede an interrupted
                # process's outbox. Replay local writes in their original order.
                for payload in self._pending.values():
                    if (
                        payload["identity"]["agent_id"] == agent_id
                        and (agent_id, payload["layer"], payload["key"])
                        not in self._blocked_keys
                    ):
                        self._layers[(agent_id, payload["layer"])][payload["key"]] = (
                            payload["value"]
                        )
                self._bootstrapped.add(agent_id)
        with self._lock:
            self._start_writer()

    def get_relationships(self, agent_id: str) -> dict[str, float]:
        import math

        relationships = {}
        for key, value in self.recall(agent_id, "relational").items():
            if (
                key.startswith("relationship:")
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                if math.isfinite(value):
                    relationships[key[len("relationship:") :]] = max(
                        0.0, min(1.0, value)
                    )
        return relationships

    def set_relationship(self, agent_id: str, other: str, value: float) -> None:
        import math

        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("relationship value must be finite")
        self.remember(
            agent_id, "relational", f"relationship:{other}", max(0.0, min(1.0, value))
        )

    def remember(self, agent_id: str, layer: str, key: str, value: Any) -> None:
        import queue

        if layer not in MEMORY_LAYERS:
            raise ValueError(f"unknown memory layer {layer!r}")
        if not isinstance(key, str) or not key or len(key) > 256:
            raise ValueError("runtime memory key must contain 1-256 characters")
        # Snapshot mutable values: later persona changes cannot rewrite queued history.
        clean = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
        payload = {
            "identity": self.identity(agent_id).to_dict(),
            "layer": layer,
            "key": key,
            "value": clean,
        }
        with self._lock:
            if self._closed:
                raise RuntimeError("runtime memory store is closed")
            if agent_id not in self._bootstrapped:
                raise RuntimeError(
                    f"bootstrap {agent_id!r} before using persistent memory"
                )
            if (agent_id, layer, key) in self._blocked_keys:
                raise PermissionError("runtime memory key is deleted or denied")
            try:
                if self._queue.full():
                    raise queue.Full
                if self._outbox is not None:
                    cursor = self._outbox.execute(
                        "INSERT INTO outbox (payload) VALUES (?)",
                        (json.dumps(payload, ensure_ascii=False, allow_nan=False),),
                    )
                    self._outbox.commit()  # Durable before the caller observes success.
                    seq = cursor.lastrowid
                else:
                    self._next_sequence += 1
                    seq = self._next_sequence
                self._pending[seq] = payload
                self._queue.put_nowait((seq, payload))
            except queue.Full as exc:
                self._last_error = "persistence queue full"
                raise RuntimeError(self._last_error) from exc
            except Exception as exc:
                if self._outbox is not None:
                    self._outbox.rollback()
                self._last_error = f"outbox failed: {type(exc).__name__}"
                raise RuntimeError(self._last_error) from exc
            self._layers.setdefault((agent_id, layer), {})[key] = clean
            self._start_writer()

    def recall(self, agent_id: str, layer: str) -> dict[str, Any]:
        if layer not in MEMORY_LAYERS:
            raise ValueError(f"unknown memory layer {layer!r}")
        with self._lock:
            if agent_id not in self._bootstrapped:
                raise RuntimeError(
                    f"bootstrap {agent_id!r} before using persistent memory"
                )
            return json.loads(
                json.dumps(self._layers.get((agent_id, layer), {}), ensure_ascii=False)
            )

    def _write_loop(self) -> None:
        import queue

        try:
            while not self._stop.is_set():
                try:
                    seq, payload = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                while not self._stop.is_set():
                    try:
                        scope = (
                            payload["identity"]["agent_id"],
                            payload["layer"],
                            payload["key"],
                        )
                        with self._lock:
                            blocked = scope in self._blocked_keys
                        result = (
                            {"status": "blocked"}
                            if blocked
                            else self._post("/runtime/memory/upsert", payload)
                        )
                        if result.get("status") not in (
                            "stored",
                            "unchanged",
                            "blocked",
                        ):
                            raise RuntimeError(
                                "runtime memory upsert was not acknowledged"
                            )
                        with self._lock:
                            if self._outbox is not None:
                                self._outbox.execute(
                                    "DELETE FROM outbox WHERE seq=?", (seq,)
                                )
                                self._outbox.commit()
                            self._pending.pop(seq, None)
                            if result["status"] == "blocked":
                                self._blocked_keys.add(scope)
                                self._layers.get(scope[:2], {}).pop(scope[2], None)
                                self._writes_blocked += 1
                            else:
                                self._writes_completed += 1
                            self._last_error = None
                        self._queue.task_done()
                    except Exception as exc:
                        # Never include request bodies or credentials in health output.
                        with self._lock:
                            self._last_error = (
                                f"persistence failed: {type(exc).__name__}"
                            )
                        self._stop.wait(0.5)
                    else:
                        break
        finally:
            with self._lock:
                if self._closed and self._outbox is not None:
                    self._outbox.close()
                    self._outbox = None

    def flush(self, timeout_s: float = 5.0) -> bool:
        """Wait for queued writes at a shutdown/checkpoint, never from a tick."""
        import time

        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "persistent": True,
                "durable_outbox": self._durable_outbox,
                "ready": bool(self._bootstrapped) and not self._closed,
                "agents_loaded": sorted(self._bootstrapped),
                "pending_writes": self._queue.unfinished_tasks,
                "writes_completed": self._writes_completed,
                "writes_blocked": self._writes_blocked,
                "last_error": self._last_error,
            }

    def close(self, timeout_s: float = 5.0) -> bool:
        with self._lock:
            self._closed = True
        flushed = self.flush(timeout_s)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(self.timeout_s + 0.1, max(0.0, timeout_s)))
        with self._lock:
            if (
                self._thread is None or not self._thread.is_alive()
            ) and self._outbox is not None:
                self._outbox.close()
                self._outbox = None
        return flushed
