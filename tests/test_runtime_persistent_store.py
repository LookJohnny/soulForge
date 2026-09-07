"""Runtime persistence across restarts, body swaps and delayed HTTP writes."""

import io
import json
import sqlite3
import subprocess
import sys
import threading
import time
from uuid import UUID

import pytest
from soulforge_harness.runtime.identity import (
    RuntimeIdentity,
    character_id_for_agent,
    runtime_user_id,
)
from soulforge_harness.runtime.memory_store import AICoreMemoryStore

BRAND = "70000000-0000-0000-0000-000000000001"
USER = runtime_user_id(BRAND)


class FakeStore(AICoreMemoryStore):
    def __init__(self, database, **kwargs):
        super().__init__(
            "http://runtime.test",
            service_token="synthetic-token",
            brand_id=BRAND,
            user_id=USER,
            **kwargs,
        )
        self.database = database
        self.calls = []
        self.write_entered = threading.Event()
        self.allow_write = threading.Event()
        self.allow_write.set()

    def _post(self, path, payload):
        self.calls.append((threading.get_ident(), path, payload))
        if path.endswith("/project"):
            return {
                "character_map": {
                    c["id"]: character_id_for_agent(BRAND, c["id"])
                    for c in payload["characters"]
                }
            }
        identity = payload["identity"]
        scope = (identity["user_id"], identity["character_id"], payload["layer"])
        if path.endswith("/recall"):
            return {"values": dict(self.database.get(scope, {}))}
        self.write_entered.set()
        if not self.allow_write.wait(2):
            raise TimeoutError("synthetic outage")
        self.database.setdefault(scope, {})[payload["key"]] = payload["value"]
        return {"status": "stored", "id": "synthetic-row"}


def test_identity_survives_body_and_session_switch_but_is_tenant_scoped():
    cid = character_id_for_agent(BRAND, "luna")
    first = RuntimeIdentity(USER, cid, "luna", "web", "session-1")
    second = RuntimeIdentity(USER, cid, "luna", "robot", "session-2")
    assert first.user_id == second.user_id and first.character_id == second.character_id
    assert UUID(cid).version == 5
    assert character_id_for_agent("70000000-0000-0000-0000-000000000002", "luna") != cid
    with pytest.raises(ValueError):
        RuntimeIdentity("not-a-user", cid, "luna")


def test_restart_recalls_all_keys_and_other_character_relationships():
    database = {}
    first = FakeStore(database, body_id="web", session_id="first")
    first.bootstrap(["luna", "kai"])
    for i in range(75):
        first.remember("luna", "episodic", f"event_{i}", {"detail": i})
    first.set_relationship("luna", "kai", 0.83)
    first.remember("luna", "semantic", "reflection_d0_0", "明天陪用户")
    assert first.flush(2)
    assert first.close()

    second = FakeStore(database, body_id="robot", session_id="second")
    second.bootstrap(["luna", "kai"])
    assert len(second.recall("luna", "episodic")) == 75  # cannot use RAG top-k restore
    assert second.recall("luna", "episodic")["event_74"] == {"detail": 74}
    assert second.get_relationships("luna") == {"kai": 0.83}
    assert second.recall("kai", "episodic") == {}
    assert second.close()


def test_tick_writes_are_local_ordered_and_hot_reload_keeps_pending_values():
    store = FakeStore({})
    store.bootstrap(["luna"])
    store.allow_write.clear()
    caller = threading.get_ident()
    store.remember("luna", "episodic", "last_request", {"order": 1})
    assert store.write_entered.wait(1)
    store.remember("luna", "episodic", "last_request", {"order": 2})
    store.bootstrap(["luna", "kai"])
    assert store.recall("luna", "episodic")["last_request"] == {"order": 2}
    assert store.health()["pending_writes"] == 2
    assert store.flush(0) is False
    assert all(
        thread != caller for thread, path, _ in store.calls if path.endswith("upsert")
    )
    store.allow_write.set()
    assert store.flush(2)
    scope = (USER, character_id_for_agent(BRAND, "luna"), "episodic")
    assert store.database[scope]["last_request"] == {"order": 2}
    assert store.close()


def test_memory_reads_return_snapshots_and_unbootstrapped_use_fails():
    store = FakeStore({})
    with pytest.raises(RuntimeError, match="bootstrap"):
        store.recall("luna", "episodic")
    store.bootstrap(["luna"])
    original = {"items": [1]}
    store.remember("luna", "episodic", "nested", original)
    original["items"].append(2)
    recalled = store.recall("luna", "episodic")
    recalled["nested"]["items"].append(3)
    assert store.recall("luna", "episodic")["nested"] == {"items": [1]}
    assert store.close()


def test_write_failure_stays_visible_and_retries_without_losing_fifo_order():
    class OutageStore(FakeStore):
        failing = True

        def _post(self, path, payload):
            if path.endswith("/upsert") and self.failing:
                raise OSError("synthetic private payload must not appear in health")
            return super()._post(path, payload)

    store = OutageStore({})
    store.bootstrap(["luna"])
    try:
        store.remember("luna", "episodic", "current", {"order": 1})
        store.remember("luna", "episodic", "current", {"order": 2})
        deadline = time.monotonic() + 1
        while store.health()["last_error"] is None and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        health = store.health()
        assert health["last_error"] == "persistence failed: OSError"
        assert health["pending_writes"] == 2 and health["writes_completed"] == 0
        assert store.flush(0) is False
        assert store.recall("luna", "episodic")["current"] == {"order": 2}
        store.failing = False
        assert store.flush(2)
        assert store.health()["last_error"] is None
        assert store.health()["writes_completed"] == 2
        scope = (USER, character_id_for_agent(BRAND, "luna"), "episodic")
        assert store.database[scope]["current"] == {"order": 2}
    finally:
        store.failing = False
        assert store.close()


def test_http_contract_carries_service_brand_and_complete_identity(monkeypatch):
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        return io.BytesIO(b'{"values": {}}')

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    store = AICoreMemoryStore(
        "http://runtime.test",
        service_token="synthetic-service-token",
        brand_id=BRAND,
        user_id=USER,
    )
    store.bootstrap(["luna"])
    assert len(requests) == 5
    headers = {k.lower(): v for k, v in requests[0].header_items()}
    assert headers["x-service-token"] == "synthetic-service-token"
    assert headers["x-brand-id"] == BRAND
    payload = json.loads(requests[0].data)
    assert payload["identity"]["character_id"] == character_id_for_agent(BRAND, "luna")
    assert payload["identity"]["user_id"] == USER
    assert store.close()


def test_durable_outbox_survives_abrupt_process_exit_and_replays_over_old_snapshot(
    tmp_path,
):
    outbox = str(tmp_path / "outbox.sqlite3")
    # No close/flush/finally: os._exit models interruption during an API outage.
    child = """
import os
import sys
from soulforge_harness.runtime.identity import runtime_user_id
from soulforge_harness.runtime.memory_store import AICoreMemoryStore
class OfflineStore(AICoreMemoryStore):
    def _post(self, path, payload):
        if path.endswith('/recall'):
            return {'values': {}}
        raise OSError('synthetic outage')
brand = '70000000-0000-0000-0000-000000000001'
store = OfflineStore('http://synthetic.test', service_token='never-persist-this-token',
    brand_id=brand, user_id=runtime_user_id(brand), outbox_path=sys.argv[1])
store.bootstrap(['luna'])
store.remember('luna', 'episodic', 'current', {'order': 1})
store.set_relationship('luna', 'kai', 0.83)
store.remember('luna', 'episodic', 'current', {'order': 2})
os._exit(0)
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, outbox], check=False, timeout=10
    )
    assert completed.returncode == 0
    with sqlite3.connect(outbox) as connection:
        persisted = connection.execute(
            "SELECT payload FROM outbox ORDER BY seq"
        ).fetchall()
        assert len(persisted) == 3
        assert "never-persist-this-token" not in str(persisted)

    scope = (USER, character_id_for_agent(BRAND, "luna"), "episodic")
    server = {scope: {"current": {"order": -1}, "acknowledged": "kept"}}
    recovered = FakeStore(
        server, outbox_path=outbox, body_id="new-body", session_id="new"
    )
    recovered.allow_write.clear()
    try:
        recovered.bootstrap(["luna"])
        assert recovered.write_entered.wait(1)
        assert recovered.recall("luna", "episodic") == {
            "current": {"order": 2},
            "acknowledged": "kept",
        }
        assert recovered.get_relationships("luna") == {"kai": 0.83}
        assert recovered.health()["durable_outbox"] is True
        assert recovered.health()["pending_writes"] == 3
        recovered.allow_write.set()
        assert recovered.flush(2)
        assert server[scope]["current"] == {"order": 2}
        with sqlite3.connect(outbox) as connection:
            assert connection.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    finally:
        recovered.allow_write.set()
        assert recovered.close()


def test_outbox_cannot_be_reused_by_another_user_or_brand(tmp_path):
    outbox = str(tmp_path / "outbox.sqlite3")
    original = FakeStore({}, outbox_path=outbox)
    assert original.close()
    for brand, user in (
        (BRAND, runtime_user_id(BRAND, "other")),
        ("70000000-0000-0000-0000-000000000002", USER),
    ):
        with pytest.raises(ValueError, match="different brand or user"):
            AICoreMemoryStore(
                "http://synthetic.test",
                service_token="synthetic-token",
                brand_id=brand,
                user_id=user,
                outbox_path=outbox,
            )


def test_server_tombstone_prevents_pending_outbox_value_from_reappearing(tmp_path):
    class PausedStore(FakeStore):
        def _start_writer(self):
            pass

    class DeletedStore(FakeStore):
        def _post(self, path, payload):
            result = super()._post(path, payload)
            if path.endswith("/recall") and payload["layer"] == "episodic":
                result["blocked_keys"] = ["erased"]
            return result

    outbox = str(tmp_path / "outbox.sqlite3")
    first = PausedStore({}, outbox_path=outbox)
    first.bootstrap(["luna"])
    first.remember("luna", "episodic", "erased", "stale pending value")
    first.remember("luna", "episodic", "retained", "allowed value")
    assert first.close(0) is False
    recovered = DeletedStore({}, outbox_path=outbox)
    try:
        recovered.bootstrap(["luna"])
        assert "erased" not in recovered.recall("luna", "episodic")
        assert recovered.flush(2)
        assert recovered.health()["writes_blocked"] == 1
        assert all(
            payload["key"] != "erased"
            for _, path, payload in recovered.calls
            if path.endswith("/upsert")
        )
        with pytest.raises(PermissionError):
            recovered.remember("luna", "episodic", "erased", "cannot revive")
        with sqlite3.connect(outbox) as connection:
            assert connection.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    finally:
        assert recovered.close()


def test_policy_block_during_write_removes_local_value_and_does_not_block_fifo():
    class BlockedStore(FakeStore):
        def _post(self, path, payload):
            if path.endswith("/upsert") and payload["key"] == "erased":
                return {"status": "blocked", "reason": "deleted_or_denied"}
            return super()._post(path, payload)

    store = BlockedStore({})
    store.bootstrap(["luna"])
    try:
        store.remember("luna", "episodic", "erased", "stale")
        store.remember("luna", "episodic", "retained", "allowed")
        assert store.flush(2)
        assert store.recall("luna", "episodic") == {"retained": "allowed"}
        assert store.health()["writes_blocked"] == 1
        assert store.health()["writes_completed"] == 1
    finally:
        assert store.close()
