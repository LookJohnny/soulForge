"""Exact runtime key/value persistence in the existing companion memory layers.

Deterministic row IDs make retries and repeated reflection updates idempotent.
Readable content lives in the normal tables so cognition's existing retrieval
and MemoryPolicy can use it; raw_source retains the lossless runtime value.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid5

from soulforge_harness.runtime.identity import RuntimeIdentity

from ai_core.services.character_projection import json_object, validate_runtime_identity
from ai_core.services.memory_policy import MemoryPolicyEngine

LAYER_TABLES = {
    "profile": "profile_memories",
    "episodic": "episodic_memories",
    "semantic": "semantic_memories",
    "relational": "relational_memories",
    # The planner contract has five layers; compiled runtime values remain
    # distinguishable from ordinary semantic values by their source marker.
    "compiled_behavior": "semantic_memories",
}


def runtime_memory_id(identity: RuntimeIdentity, layer: str, key: str) -> str:
    return str(
        uuid5(
            UUID(identity.user_id),
            json.dumps(
                ["soulforge:runtime", identity.character_id, identity.agent_id, layer, key],
                ensure_ascii=False,
            ),
        )
    )


def readable_memory(agent_id: str, key: str, value: Any) -> str:
    if key.startswith("relationship:"):
        return f"{agent_id}与{key.split(':', 1)[1]}的熟悉程度：{value}（0到1）。"
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return f"{agent_id}的{key}：{text}"[:2000]


class RuntimeStateService:
    def __init__(self, pool):
        self.pool = pool
        self.policy = MemoryPolicyEngine()

    @staticmethod
    def _table(layer: str) -> str:
        if layer not in LAYER_TABLES:
            raise ValueError("unknown runtime memory layer")
        return LAYER_TABLES[layer]

    async def recall(self, brand_id: str, identity: RuntimeIdentity, layer: str) -> dict:
        table = self._table(layer)
        async with self.pool.acquire() as conn:
            await validate_runtime_identity(conn, brand_id, identity)
            rows = await conn.fetch(
                f"""SELECT raw_source, deleted_at, permission_level::TEXT AS permission_level
                    FROM {table}
                    WHERE user_id = $1 AND character_id = $2
                      AND raw_source->'runtime'->>'agent_id' = $3
                      AND raw_source->'runtime'->>'layer' = $4
                    ORDER BY timestamp, id""",
                identity.user_id,
                identity.character_id,
                identity.agent_id,
                layer,
            )
        # No LIMIT, relevance filter or RAG token budget: this is state restore.
        values = {}
        blocked_keys = set()
        for row in rows:
            marker = json_object(row["raw_source"]).get("runtime", {})
            if marker.get("version") == 1 and isinstance(marker.get("key"), str):
                key = marker["key"]
                if row.get("deleted_at") is not None or row.get("permission_level") == "DENIED":
                    blocked_keys.add(key)
                else:
                    values[key] = marker.get("value")
        for key in blocked_keys:
            values.pop(key, None)
        return {"values": values, "blocked_keys": sorted(blocked_keys)}

    async def upsert(
        self, brand_id: str, identity: RuntimeIdentity, layer: str, key: str, value: Any
    ) -> dict:
        table = self._table(layer)
        if not isinstance(key, str) or not key or len(key) > 256:
            raise ValueError("runtime memory key must contain 1-256 characters")
        raw_source = {
            "source": "character_runtime",
            "identity": identity.to_dict(),
            "runtime": {
                "version": 1,
                "agent_id": identity.agent_id,
                "layer": layer,
                "key": key,
                "value": value,
            },
        }
        encoded = json.dumps(raw_source, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("runtime memory entry exceeds 64 KiB")
        memory_id = runtime_memory_id(identity, layer, key)
        content = readable_memory(identity.agent_id, key, value)
        sensitivity = self.policy.classify_sensitivity(content)
        requires_confirmation = sensitivity in ("HIGH", "CRITICAL")
        importance = self.policy.score_importance(content, layer)
        extra_column, extra_value = "", []
        if layer == "profile":
            extra_column, extra_value = ", key", [f"runtime:{identity.agent_id}:{key}"]
        elif layer == "relational":
            extra_column, extra_value = (
                ", relation_axis",
                [
                    "runtime_relationship"
                    if key.startswith("relationship:")
                    else self.policy.relation_axis(content)
                ],
            )
        # Episodic rows intentionally have no updated_at column in the schema.
        updated_at = ", updated_at" if table != "episodic_memories" else ""
        updated_value = ", now()" if updated_at else ""
        updated_assignment = ", updated_at=now()" if updated_at else ""
        extra_placeholder = ", $10" if extra_value else ""
        async with self.pool.acquire() as conn, conn.transaction():
            await validate_runtime_identity(conn, brand_id, identity)
            has_embedding = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = 'embedding')",
                table,
            )
            # Existing backfilled vectors must not describe the previous value.
            reset_embedding = ", embedding=NULL, embedding_model=NULL" if has_embedding else ""
            row = await conn.fetchrow(
                f"""INSERT INTO {table}
                    (id, user_id, character_id, content, raw_source, sensitivity_level,
                     importance_score, requires_confirmation,
                     permission_level{extra_column}{updated_at})
                    VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9{extra_placeholder}{updated_value})
                    ON CONFLICT (id) DO UPDATE SET content=EXCLUDED.content,
                      raw_source=EXCLUDED.raw_source, timestamp=now(),
                      sensitivity_level=EXCLUDED.sensitivity_level,
                      importance_score=EXCLUDED.importance_score,
                      requires_confirmation=EXCLUDED.requires_confirmation,
                      permission_level=EXCLUDED.permission_level{updated_assignment}{reset_embedding}
                    WHERE {table}.user_id=EXCLUDED.user_id
                      AND {table}.character_id=EXCLUDED.character_id
                      AND {table}.deleted_at IS NULL AND {table}.permission_level <> 'DENIED'
                    RETURNING id""",
                memory_id,
                identity.user_id,
                identity.character_id,
                content,
                encoded,
                sensitivity,
                importance,
                requires_confirmation,
                "PENDING_CONFIRMATION" if requires_confirmation else "AUTO",
                *extra_value,
            )
        if row is None:
            # A terminal, scoped policy result lets an outbox discard stale
            # pending values. Authentication failures remain PermissionError.
            return {"id": memory_id, "status": "blocked", "reason": "deleted_or_denied"}
        return {"id": str(row["id"]), "status": "stored"}
