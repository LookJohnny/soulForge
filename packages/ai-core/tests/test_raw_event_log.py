"""Tests for immutable raw event log service helpers."""

import json
from datetime import UTC, datetime

from ai_core.services.memory import MemoryService


class _FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _FakeAcquire(self.conn)


class _FakeConn:
    def __init__(self):
        self.fetchrow_args = None
        self.fetch_args = None

    async def fetchrow(self, _query, *args):
        self.fetchrow_args = args
        return {
            "id": "00000000-0000-0000-0000-000000000011",
            "user_id": args[0],
            "character_id": args[1],
            "device_id": args[2],
            "session_id": args[3],
            "event_type": args[4],
            "source": args[5],
            "content": args[6],
            "payload": json.loads(args[7]),
            "context": json.loads(args[8]),
            "importance_score": args[9],
            "sensitivity_level": args[10],
            "observed_at": args[11],
            "created_at": datetime(2026, 6, 12, 12, tzinfo=UTC),
        }

    async def fetch(self, _query, *args):
        self.fetch_args = args
        return [
            {
                "id": "00000000-0000-0000-0000-000000000012",
                "user_id": args[0],
                "character_id": args[1],
                "device_id": None,
                "session_id": "s1",
                "event_type": "user_utterance",
                "source": "chat",
                "content": "今天考试很重要",
                "payload": {},
                "context": {},
                "importance_score": 8,
                "sensitivity_level": "LOW",
                "observed_at": datetime(2026, 6, 12, 9, tzinfo=UTC),
                "created_at": datetime(2026, 6, 12, 12, tzinfo=UTC),
            }
        ]


async def test_record_raw_event_auto_scores_and_persists_payload():
    conn = _FakeConn()
    service = MemoryService(_FakePool(conn), llm=None, cache=None)
    service._raw_event_schema_available = True
    observed_at = datetime(2026, 6, 12, 9, tzinfo=UTC)

    row = await service.record_raw_event(
        {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "character_id": "00000000-0000-0000-0000-000000000002",
            "event_type": "user_utterance",
            "source": "chat",
            "content": "今天考试很重要",
            "payload": {"turn": 3},
            "context": {"mood": "nervous"},
            "observed_at": observed_at,
        }
    )

    assert row["event_type"] == "user_utterance"
    assert row["payload"] == {"turn": 3}
    assert row["context"] == {"mood": "nervous"}
    assert 1 <= conn.fetchrow_args[9] <= 10
    assert conn.fetchrow_args[11] == observed_at


async def test_list_raw_events_returns_stringified_datetimes():
    conn = _FakeConn()
    service = MemoryService(_FakePool(conn), llm=None, cache=None)
    service._raw_event_schema_available = True

    rows = await service.list_raw_events(
        "00000000-0000-0000-0000-000000000001",
        character_id="00000000-0000-0000-0000-000000000002",
        limit=10,
    )

    assert rows[0]["event_type"] == "user_utterance"
    assert rows[0]["observed_at"] == "2026-06-12T09:00:00+00:00"
    assert conn.fetch_args[2] == 10
