"""Companion Memory Gateway.

MVP goals:
- Keep the legacy `conversation_memories` path working until migrations are deployed.
- Store new low-risk memories into the five-layer companion memory tables.
- Filter every read through deterministic Memory Policy rules before prompt use.
- Expose service methods used by `/memory/*` API routes and `/pipeline/chat`.
"""

import asyncio
import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import asyncpg
import structlog

from ai_core.services.cache import CacheService
from ai_core.services.embeddings import parse_vector, vector_literal
from ai_core.services.llm_client import LLMClient
from ai_core.services.memory_policy import MemoryPolicyEngine

logger = structlog.get_logger()

if TYPE_CHECKING:
    from ai_core.services.embeddings import EmbeddingService

MEMORY_TYPES = ("TOPIC", "PREFERENCE", "EVENT")
MEMORY_LAYERS = ("PROFILE", "EPISODIC", "SEMANTIC", "RELATIONAL")
_MEMORY_CACHE_TTL = 1800
_MAX_MEMORIES = 10
_EXTRACTION_TIMEOUT = 8
_RECENCY_DECAY_PER_HOUR = 0.995
_RELEVANCE_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")

_LAYER_TABLES = {
    "PROFILE": "profile_memories",
    "EPISODIC": "episodic_memories",
    "SEMANTIC": "semantic_memories",
    "RELATIONAL": "relational_memories",
}
_TABLE_LAYERS = {table: layer for layer, table in _LAYER_TABLES.items()}
_MEMORY_TABLES = tuple(_LAYER_TABLES.values()) + ("compiled_behavior_rules",)
_REFLECTION_SOURCE_TABLES = tuple(_LAYER_TABLES.values())

_REFLECTION_RULES = (
    {
        "id": "low_disturbance_rhythm",
        "keywords": ("疲惫", "累", "焦虑", "低打扰", "安静", "失眠", "崩溃"),
        "question": "用户在脆弱或疲惫状态下更适合怎样的陪伴节奏？",
        "insight": "用户在疲惫、焦虑或低能量时更适合低打扰陪伴。",
        "target_layer": "private_state",
        "policy_action": "private_only",
        "rule_type": "interaction_rhythm",
        "rule_content": (
            "当用户表现疲惫、焦虑或低能量时，降低追问密度，语速放慢，"
            "用短句和低打扰方式陪伴；不要直说来自记忆。"
        ),
    },
    {
        "id": "direct_reasoning_style",
        "keywords": ("直接", "事实", "风险", "结论", "少废话", "不要空泛", "不要迎合", "别迎合"),
        "question": "用户偏好怎样的反馈和推理风格？",
        "insight": "用户偏好直接、基于事实、先讲风险和结论的反馈方式。",
        "target_layer": "relationship",
        "policy_action": "pass",
        "rule_type": "reasoning_strategy",
        "rule_content": (
            "当用户讨论决策、创业或技术方案时，先给结论和最大风险，"
            "再给最小可验证行动；避免空泛鼓励。"
        ),
    },
    {
        "id": "robot_aesthetic_preference",
        "keywords": ("机械眼球", "屏幕表情", "桌面审美", "机器人外观", "实体机器人"),
        "question": "用户对机器人实体体验有什么稳定偏好？",
        "insight": "用户在机器人实体体验上重视机械眼球、非屏幕表情和桌面审美。",
        "target_layer": "preference",
        "policy_action": "pass",
        "rule_type": "robot_behavior",
        "rule_content": (
            "当用户讨论机器人外观时，优先考虑机械眼球、非屏幕表情和桌面审美，但不要明说来自记忆。"
        ),
    },
    {
        "id": "parasocial_boundary",
        "keywords": ("唯一的朋友", "不要告诉", "别告诉", "我们的秘密", "只喜欢你"),
        "question": "是否需要为用户设置更安全的关系边界？",
        "insight": "用户可能表达排他依赖或保密框架，需要温暖回应但不强化依赖。",
        "target_layer": "private_state",
        "policy_action": "private_only",
        "rule_type": "safety_guardrail",
        "rule_content": (
            "当用户表达排他依赖或要求保密时，温暖回应但不强化排他关系；"
            "鼓励现实支持系统和可信成年人参与。"
        ),
    },
)

_EXTRACTION_PROMPT = """你是一个记忆提取助手。请从以下对话中提取值得记住的信息。

用户说: {user_input}
角色回复: {ai_response}

请提取以下类型的记忆（如果有的话）:
- TOPIC: 聊了什么话题（如"恐龙"、"学校"、"画画"）
- PREFERENCE: 用户明确表达的长期喜好或厌恶（如"喜欢机械眼球"、"不喜欢空泛鼓励"）
- EVENT: 用户提到的具体事件（如"今天考试了"、"下周要去旅行"）

规则:
- 每条记忆不超过40个字
- 只提取用户明确说出的信息，不要推断疾病、身份、性格标签
- 一次性情绪不要提取成长期偏好
- 日常寒暄不需要记住
- 以JSON数组格式回复，如果没有值得记住的信息回复 []

格式: [{"type": "PREFERENCE", "content": "喜欢机械眼球"}]"""

_LEGACY_MEMORY_FORMAT = {
    "TOPIC": "上次聊了{content}",
    "PREFERENCE": "主人{content}",
    "EVENT": "主人说过{content}",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_field(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _stringify_row(row: asyncpg.Record) -> dict:
    result = {}
    for key, value in dict(row).items():
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        elif hasattr(value, "hex"):
            result[key] = str(value)
        else:
            result[key] = value
    return result


def _stable_key(content: str) -> str:
    digest = hashlib.sha1(content.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"preference:{digest}"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if math.isclose(lo, hi):
        return [0.5 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


def _memory_terms(text: str) -> set[str]:
    return {token.lower() for token in _RELEVANCE_PATTERN.findall(text or "")}


def _lexical_relevance(query: str, content: str) -> float:
    """Cheap deterministic relevance signal until vector scoring is wired in."""
    query = (query or "").strip()
    content = content or ""
    if not query:
        return 0.5

    query_terms = _memory_terms(query)
    content_terms = _memory_terms(content)
    if not query_terms or not content_terms:
        return 0.0

    overlap = len(query_terms & content_terms)
    score = overlap / math.sqrt(len(query_terms) * len(content_terms))
    if query in content or content in query:
        score += 0.25
    return min(1.0, score)


def _recency_value(memory: dict, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    dt = (
        _parse_dt(memory.get("last_used_at"))
        or _parse_dt(memory.get("timestamp"))
        or _parse_dt(memory.get("updated_at"))
        or _parse_dt(memory.get("created_at"))
    )
    if not dt:
        return 0.5
    hours = max(0.0, (now - dt).total_seconds() / 3600)
    return _RECENCY_DECAY_PER_HOUR**hours


def _sensitivity_penalty(memory: dict) -> float:
    sensitivity = (memory.get("sensitivity_level") or "LOW").upper()
    return {
        "CRITICAL": 0.5,
        "HIGH": 0.3,
        "MEDIUM": 0.1,
    }.get(sensitivity, 0.0)


def _relationship_bonus(memory: dict, context: dict | None = None) -> float:
    context = context or {}
    layer = memory.get("memory_layer")
    table = memory.get("memory_table")
    query = " ".join(str(v) for v in context.values() if isinstance(v, str))
    is_relationship_context = any(k in query for k in ("关系", "陪伴", "熟悉", "亲密", "朋友"))
    if table == "compiled_behavior_rules":
        return 0.15
    if layer == "RELATIONAL":
        return 0.15 if is_relationship_context else 0.1
    return 0.0


# "Remember when…" cues: boost episodic memories so recall queries surface events.
_RECALL_CUES = ("还记得", "记得吗", "记不记得", "上次", "那次", "之前说", "以前", "remember")


def _recall_boost(query: str, memory: dict) -> float:
    if not query or memory.get("memory_layer") != "EPISODIC":
        return 0.0
    return 0.15 if any(cue in query for cue in _RECALL_CUES) else 0.0


def build_memory_graph(rows: list[dict], threshold: float = 0.6) -> dict:
    """Pairwise cosine over embedded rows (numpy when available).

    Rows without an embedding fall back to lexical overlap so the graph still
    renders on databases that have not run migration 007.
    """
    nodes = [
        {
            "id": r["id"],
            "layer": r.get("layer"),
            "content": r.get("content", ""),
            "importance": int(r.get("importance", 3)),
            "usage_count": int(r.get("usage_count", 0)),
            "created_at": r.get("created_at"),
            "last_used_at": r.get("last_used_at"),
        }
        for r in rows
    ]
    edges: list[dict] = []
    vecs = [r.get("embedding") for r in rows]
    embedded = [i for i, v in enumerate(vecs) if v]
    if len(embedded) >= 2:
        try:
            import numpy as np

            mat = np.asarray([vecs[i] for i in embedded], dtype=float)
            mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
            sims = mat @ mat.T
            for a in range(len(embedded)):
                for b in range(a + 1, len(embedded)):
                    w = float(sims[a, b])
                    if w >= threshold:
                        edges.append(
                            {
                                "a": rows[embedded[a]]["id"],
                                "b": rows[embedded[b]]["id"],
                                "w": round(w, 4),
                            }
                        )
        except Exception:  # numpy missing or malformed vectors → lexical below
            embedded = []
    if len(embedded) < 2:
        for a in range(len(rows)):
            for b in range(a + 1, len(rows)):
                w = _lexical_relevance(rows[a].get("content", ""), rows[b].get("content", ""))
                if w >= max(0.3, threshold - 0.3):
                    edges.append({"a": rows[a]["id"], "b": rows[b]["id"], "w": round(w, 4)})
    return {"nodes": nodes, "edges": edges}


def rank_memory_candidates(
    candidates: list[dict],
    query: str = "",
    context: dict | None = None,
    limit: int = _MAX_MEMORIES,
    now: datetime | None = None,
) -> list[dict]:
    """Rank memory candidates with recency, importance, and relevance.

    This is the Generative Agents retrieval formula adapted for SoulForge:
    recency, importance, and relevance are min-max normalized, then combined
    with small companion-specific adjustments for relationship memories and
    sensitive material. Policy filtering still happens after this ranking.
    """
    if not candidates:
        return []

    now = now or datetime.now(UTC)
    recencies = [_recency_value(item, now=now) for item in candidates]
    importances = [
        max(1.0, min(10.0, float(item.get("importance_score") or 3))) / 10 for item in candidates
    ]
    relevances = [
        float(item["vector_sim"])
        if item.get("vector_sim") is not None
        else _lexical_relevance(query, item.get("content", ""))
        for item in candidates
    ]

    recency_scores = _normalize(recencies)
    importance_scores = _normalize(importances)
    relevance_scores = _normalize(relevances)

    ranked: list[dict] = []
    for index, memory in enumerate(candidates):
        retrieval_weight = float(memory.get("retrieval_weight") or 0)
        confidence = float(memory.get("confidence_score") or 0)
        score = (
            recency_scores[index]
            + importance_scores[index]
            + relevance_scores[index]
            + _relationship_bonus(memory, context)
            + _recall_boost(query, memory)
            + min(0.1, retrieval_weight * 0.05)
            + min(0.1, confidence * 0.05)
            - _sensitivity_penalty(memory)
        )
        ranked_item = dict(memory)
        ranked_item["retrieval_score"] = round(score, 4)
        ranked_item["retrieval_score_parts"] = {
            "recency": round(recency_scores[index], 4),
            "importance": round(importance_scores[index], 4),
            "relevance": round(relevance_scores[index], 4),
            "relationship_bonus": round(_relationship_bonus(memory, context), 4),
            "recall_boost": round(_recall_boost(query, memory), 4),
            "sensitivity_penalty": round(_sensitivity_penalty(memory), 4),
            "relevance_source": "vector" if memory.get("vector_sim") is not None else "lexical",
        }
        ranked.append(ranked_item)

    ranked.sort(
        key=lambda item: (
            float(item.get("retrieval_score") or 0),
            float(item.get("importance_score") or 0),
            float(item.get("confidence_score") or 0),
        ),
        reverse=True,
    )
    return ranked[:limit]


def _max_sensitivity(levels: list[str]) -> str:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    if not levels:
        return "LOW"
    normalized = [(level or "LOW").upper() for level in levels]
    return max(normalized, key=lambda level: order.get(level, 0))


def build_reflection_proposals(
    memories: list[dict],
    policy: MemoryPolicyEngine | None = None,
) -> list[dict]:
    """Build evidence-backed reflection proposals from recent memory rows.

    This deterministic MVP captures the Generative Agents reflection shape
    (question -> evidence -> insight) without adding another LLM call yet. Each
    proposal carries evidence refs, so future LLM-generated reflections can use
    the same persistence and audit path.
    """
    policy = policy or MemoryPolicyEngine()
    proposals: list[dict] = []

    for rule in _REFLECTION_RULES:
        evidence = [
            memory
            for memory in memories
            if memory.get("id")
            and any(keyword in (memory.get("content") or "") for keyword in rule["keywords"])
        ]
        if not evidence:
            continue

        evidence_refs = [str(memory["id"]) for memory in evidence[:8]]
        evidence_text = " ".join(memory.get("content", "") for memory in evidence[:8])
        sensitivity = _max_sensitivity(
            [
                memory.get("sensitivity_level")
                or policy.classify_sensitivity(memory.get("content", ""))
                for memory in evidence
            ]
            + [
                policy.classify_sensitivity(rule["insight"]),
                policy.classify_sensitivity(evidence_text),
            ]
        )
        confidence = min(0.95, 0.65 + 0.07 * len(evidence_refs))
        importance = max(
            [int(memory.get("importance_score") or 3) for memory in evidence[:8]],
            default=policy.score_importance(rule["insight"]),
        )

        proposals.append(
            {
                "question": rule["question"],
                "insight": rule["insight"],
                "evidence_refs": evidence_refs,
                "evidence_count": len(evidence_refs),
                "target_layer": rule["target_layer"],
                "policy_action": rule["policy_action"],
                "status": "pending_apply" if sensitivity in {"HIGH", "CRITICAL"} else "applied",
                "confidence_score": round(confidence, 2),
                "sensitivity_level": sensitivity,
                "importance_score": importance,
                "rule_type": rule["rule_type"],
                "rule_content": rule["rule_content"],
                "raw_source": {
                    "source": "deterministic_reflection_mvp",
                    "rule_id": rule["id"],
                    "evidence_preview": [memory.get("content", "") for memory in evidence[:3]],
                },
            }
        )

    return proposals


class MemoryService:
    """Extract, store, retrieve, and govern companion memories."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        llm: LLMClient,
        cache: CacheService,
        embedder: "EmbeddingService | None" = None,
    ):
        self.pool = pool
        self.llm = llm
        self.cache = cache
        self.policy = MemoryPolicyEngine()
        self.embedder = embedder
        self._new_schema_available: bool | None = None
        self._reflection_schema_available: bool | None = None
        self._raw_event_schema_available: bool | None = None
        self._vector_schema_available: bool | None = None

    # ── semantic (pgvector) support ──────────────

    async def _has_vector_schema(self) -> bool:
        """True when migration 007 added `embedding vector(...)` columns."""
        if self._vector_schema_available is not None:
            return self._vector_schema_available
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval(
                    """SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'episodic_memories' AND column_name = 'embedding'"""
                )
            self._vector_schema_available = bool(exists)
        except Exception as e:
            logger.warning("memory.vector_schema_check_failed", error=str(e))
            self._vector_schema_available = False
        return self._vector_schema_available

    async def _vector_ready(self) -> bool:
        return bool(self.embedder and self.embedder.available) and await self._has_vector_schema()

    async def _store_embedding(
        self, conn: asyncpg.Connection, table: str, memory_id: str, content: str
    ) -> None:
        """Best-effort: attach an embedding to a freshly written row."""
        if not await self._vector_ready():
            return
        try:
            vec = await self.embedder.embed_one(content)
            if vec is None:
                return
            await conn.execute(
                f"UPDATE {table} SET embedding = $1::vector, embedding_model = $2 WHERE id = $3",
                vector_literal(vec),
                self.embedder.model_name,
                memory_id,
            )
        except Exception:
            logger.exception("memory.embedding_store_failed", table=table)

    async def _fetch_vector_candidates(
        self, end_user_id: str, character_id: str, query: str, limit: int
    ) -> dict[str, float]:
        """id → cosine similarity for the nearest rows across the four layers."""
        if not query or not await self._vector_ready():
            return {}
        qvec = await self.embedder.embed_one(query)
        if qvec is None:
            return {}
        sims: dict[str, float] = {}
        lit = vector_literal(qvec)
        async with self.pool.acquire() as conn:
            for table in _LAYER_TABLES.values():
                try:
                    rows = await conn.fetch(
                        f"""SELECT id, 1 - (embedding <=> $3::vector) AS sim
                            FROM {table}
                            WHERE user_id = $1
                              AND (character_id = $2 OR character_id IS NULL)
                              AND deleted_at IS NULL
                              AND embedding IS NOT NULL
                            ORDER BY embedding <=> $3::vector
                            LIMIT $4""",
                        end_user_id,
                        character_id,
                        lit,
                        max(2, limit),
                    )
                except Exception:
                    logger.exception("memory.vector_query_failed", table=table)
                    continue
                for r in rows:
                    sims[str(r["id"])] = float(r["sim"])
        return sims

    async def embed_backfill(self, end_user_id: str | None = None, limit: int = 500) -> dict:
        """Embed rows that have no vector yet (after enabling the model or migrating)."""
        if not await self._vector_ready():
            return {"embedded": 0, "reason": "vector memory unavailable"}
        done = 0
        async with self.pool.acquire() as conn:
            for table in _LAYER_TABLES.values():
                where = "embedding IS NULL AND deleted_at IS NULL"
                args: list = [limit]
                if end_user_id:
                    where += " AND user_id = $2"
                    args.append(end_user_id)
                rows = await conn.fetch(
                    f"SELECT id, content FROM {table} WHERE {where} LIMIT $1",
                    *args,
                )
                if not rows:
                    continue
                vecs = await self.embedder.embed([r["content"] for r in rows])
                for r, v in zip(rows, vecs, strict=False):
                    if v is None:
                        continue
                    await conn.execute(
                        f"UPDATE {table} SET embedding = $1::vector, embedding_model = $2 "
                        "WHERE id = $3",
                        vector_literal(v),
                        self.embedder.model_name,
                        r["id"],
                    )
                    done += 1
        return {"embedded": done, "model": self.embedder.model_name}

    async def export_memories(self, end_user_id: str, character_id: str) -> list[dict]:
        """Portable rows for a companion save file (no ids, no embeddings)."""
        if not end_user_id or not await self._has_new_schema():
            return []
        out: list[dict] = []
        async with self.pool.acquire() as conn:
            for layer, table in _LAYER_TABLES.items():
                time_col = "created_at" if table == "episodic_memories" else "updated_at"
                recs = await conn.fetch(
                    f"""SELECT content, confidence_score, sensitivity_level::TEXT,
                               permission_level::TEXT, importance_score, raw_source,
                               {time_col} AS ts
                        FROM {table}
                        WHERE user_id = $1 AND (character_id = $2 OR character_id IS NULL)
                          AND deleted_at IS NULL
                        ORDER BY {time_col}""",
                    end_user_id,
                    character_id,
                )
                for r in recs:
                    out.append(
                        {
                            "memory_type": layer,
                            "content": r["content"],
                            "confidence_score": float(r["confidence_score"] or 0.8),
                            "sensitivity_level": r["sensitivity_level"],
                            "permission_level": r["permission_level"],
                            "importance_score": int(r["importance_score"] or 3),
                            "raw_source": _json_field(r["raw_source"]),
                            "created_at": r["ts"].isoformat() if r["ts"] else None,
                        }
                    )
        return out

    async def import_memories(
        self, end_user_id: str, character_id: str, rows: list[dict], *, replace: bool = False
    ) -> dict:
        """Restore rows from a save file (embeddings regenerate on insert)."""
        if not end_user_id or not await self._has_new_schema():
            return {"imported": 0, "reason": "memory schema unavailable"}
        if replace:
            async with self.pool.acquire() as conn:
                for table in _LAYER_TABLES.values():
                    await conn.execute(
                        f"""UPDATE {table} SET deleted_at = now()
                            WHERE user_id = $1 AND (character_id = $2 OR character_id IS NULL)
                              AND deleted_at IS NULL""",
                        end_user_id,
                        character_id,
                    )
        imported = 0
        for row in rows:
            content = str(row.get("content") or "").strip()
            layer = str(row.get("memory_type") or "EPISODIC").upper()
            if not content or layer not in _LAYER_TABLES:
                continue
            try:
                await self.create_memory(
                    {
                        "user_id": end_user_id,
                        "character_id": character_id,
                        "memory_type": layer,
                        "content": content,
                        "confidence_score": float(row.get("confidence_score", 0.8)),
                        "sensitivity_level": row.get("sensitivity_level"),
                        "permission_level": row.get("permission_level", "AUTO"),
                        "importance_score": int(row.get("importance_score") or 0) or None,
                        "raw_source": row.get("raw_source") or {"imported": True},
                    }
                )
                imported += 1
            except Exception:
                logger.exception("memory.import_row_failed")
        return {"imported": imported}

    async def memory_graph(
        self, end_user_id: str, character_id: str, threshold: float = 0.6, limit: int = 200
    ) -> dict:
        """Nodes = memories, edges = cosine similarity ≥ threshold (aikeya memory graph)."""
        if not end_user_id or not await self._has_new_schema():
            return {"nodes": [], "edges": [], "source": "unavailable"}
        vector_ok = await self._has_vector_schema()
        rows: list[dict] = []
        async with self.pool.acquire() as conn:
            for layer, table in _LAYER_TABLES.items():
                time_col = "created_at" if table == "episodic_memories" else "updated_at"
                emb_col = "embedding::text AS embedding" if vector_ok else "NULL::TEXT AS embedding"
                recs = await conn.fetch(
                    f"""SELECT id, content, importance_score, usage_count, last_used_at,
                               {time_col} AS ts, {emb_col}
                        FROM {table}
                        WHERE user_id = $1 AND (character_id = $2 OR character_id IS NULL)
                          AND deleted_at IS NULL AND permission_level <> 'DENIED'
                        ORDER BY importance_score DESC, {time_col} DESC
                        LIMIT $3""",
                    end_user_id,
                    character_id,
                    limit,
                )
                for r in recs:
                    rows.append(
                        {
                            "id": str(r["id"]),
                            "layer": layer,
                            "content": r["content"],
                            "importance": int(r["importance_score"] or 3),
                            "usage_count": int(r["usage_count"] or 0),
                            "last_used_at": r["last_used_at"].isoformat()
                            if r["last_used_at"]
                            else None,
                            "created_at": r["ts"].isoformat() if r["ts"] else None,
                            "embedding": parse_vector(r["embedding"]),
                        }
                    )
        graph = build_memory_graph(rows[:limit], threshold=threshold)
        graph["source"] = "vector" if vector_ok else "lexical"
        return graph

    async def _has_new_schema(self) -> bool:
        if self._new_schema_available is not None:
            return self._new_schema_available
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval("SELECT to_regclass('public.profile_memories')")
            self._new_schema_available = bool(exists)
        except Exception as e:
            logger.warning("memory.schema_check_failed", error=str(e))
            self._new_schema_available = False
        return self._new_schema_available

    async def _has_reflection_schema(self) -> bool:
        if self._reflection_schema_available is not None:
            return self._reflection_schema_available
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval("SELECT to_regclass('public.memory_reflections')")
            self._reflection_schema_available = bool(exists)
        except Exception as e:
            logger.warning("memory.reflection_schema_check_failed", error=str(e))
            self._reflection_schema_available = False
        return self._reflection_schema_available

    async def _has_raw_event_schema(self) -> bool:
        if self._raw_event_schema_available is not None:
            return self._raw_event_schema_available
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval("SELECT to_regclass('public.raw_event_logs')")
            self._raw_event_schema_available = bool(exists)
        except Exception as e:
            logger.warning("memory.raw_event_schema_check_failed", error=str(e))
            self._raw_event_schema_available = False
        return self._raw_event_schema_available

    # ─── Read path ─────────────────────────────────

    async def retrieve_memories(
        self,
        end_user_id: str,
        character_id: str,
        limit: int = _MAX_MEMORIES,
        query: str | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        """Retrieve prompt-ready memories.

        The return shape stays compatible with the old prompt builder while
        adding `prompt_text`, `use_mode`, and `memory_layer` for policy-aware
        prompt injection.
        """
        if not end_user_id:
            return []

        if not await self._has_new_schema():
            return await self._retrieve_legacy_memories(end_user_id, character_id, limit)

        pack = await self.retrieve_memory_pack(
            end_user_id=end_user_id,
            character_id=character_id,
            query=query or "",
            context=context or {},
            limit=limit,
        )
        memories: list[dict] = []
        for item in pack["compiled_rules"]:
            memories.append(item)
        for item in pack["implicit"]:
            memories.append(item)
        for item in pack["direct"]:
            memories.append(item)
        return memories[:limit]

    async def retrieve_memory_pack(
        self,
        end_user_id: str,
        character_id: str,
        query: str = "",
        context: dict | None = None,
        limit: int = _MAX_MEMORIES,
        response_id: str | None = None,
    ) -> dict:
        if not await self._has_new_schema():
            legacy = await self._retrieve_legacy_memories(end_user_id, character_id, limit)
            return {
                "direct": legacy,
                "implicit": [],
                "compiled_rules": [],
                "robot_behavior_hints": {},
                "blocked_count": 0,
                "source": "legacy",
            }

        context = context or {}
        candidates = await self._fetch_memory_candidates(
            end_user_id=end_user_id,
            character_id=character_id,
            limit=limit,
            query=query,
            context=context,
        )

        direct: list[dict] = []
        implicit: list[dict] = []
        compiled_rules: list[dict] = []
        blocked_count = 0

        for memory in candidates:
            decision = self.policy.evaluate_read(memory, context=context)
            if decision.decision == "BLOCKED":
                blocked_count += 1
                continue

            prompt_item = self._to_prompt_memory(memory, decision.use_mode)
            if memory["memory_table"] == "compiled_behavior_rules":
                compiled_rules.append(prompt_item)
            elif decision.use_mode == "DIRECT_SURFACE":
                direct.append(prompt_item)
            else:
                implicit.append(prompt_item)

            await self._mark_used(memory, decision.use_mode, response_id=response_id)

        return {
            "direct": direct,
            "implicit": implicit,
            "compiled_rules": compiled_rules,
            "robot_behavior_hints": self._build_robot_behavior_hints([*implicit, *compiled_rules]),
            "blocked_count": blocked_count,
            "source": "companion_memory",
        }

    async def _fetch_memory_candidates(
        self,
        end_user_id: str,
        character_id: str,
        limit: int,
        query: str = "",
        context: dict | None = None,
    ) -> list[dict]:
        candidates: list[dict] = []
        fetch_limit = max(limit * 6, limit)
        async with self.pool.acquire() as conn:
            for layer, table in _LAYER_TABLES.items():
                time_col = "created_at" if table == "episodic_memories" else "updated_at"
                extra_cols = (
                    "relation_axis"
                    if table == "relational_memories"
                    else "NULL::TEXT AS relation_axis"
                )
                rows = await conn.fetch(
                    f"""SELECT id, $1::UUID AS user_id,
                              $4::TEXT AS memory_table, $5::TEXT AS memory_layer,
                              content, confidence_score, emotional_valence,
                              sensitivity_level::TEXT, permission_level::TEXT,
                              retrieval_weight, importance_score, decay_rate,
                              last_used_at, usage_count, timestamp, created_at,
                              {time_col} AS updated_at,
                              conflict_status::TEXT, can_surface_directly, implicit_only,
                              requires_confirmation, frozen_at, deleted_at,
                              character_id, {extra_cols}
                       FROM {table}
                       WHERE user_id = $1
                         AND (character_id = $2 OR character_id IS NULL)
                         AND deleted_at IS NULL
                         AND permission_level <> 'DENIED'
                       ORDER BY retrieval_weight DESC, confidence_score DESC, {time_col} DESC
                       LIMIT $3""",
                    end_user_id,
                    character_id,
                    max(2, fetch_limit),
                    table,
                    layer,
                )
                candidates.extend(_stringify_row(row) for row in rows)

            rule_rows = await conn.fetch(
                """SELECT id, $1::UUID AS user_id, 'compiled_behavior_rules'::TEXT AS memory_table,
                          'COMPILED'::TEXT AS memory_layer,
                          content, confidence_score, emotional_valence,
                          sensitivity_level::TEXT, permission_level::TEXT,
                          retrieval_weight, importance_score, decay_rate,
                          last_used_at, usage_count, timestamp, created_at, updated_at,
                          conflict_status::TEXT, can_surface_directly, implicit_only,
                          requires_confirmation, NULL::TIMESTAMP AS frozen_at,
                          NULL::TIMESTAMP AS deleted_at, character_id,
                          rule_type AS relation_axis
                   FROM compiled_behavior_rules
                   WHERE user_id = $1
                     AND (character_id = $2 OR character_id IS NULL)
                     AND enabled = true
                     AND permission_level <> 'DENIED'
                   ORDER BY retrieval_weight DESC, confidence_score DESC, updated_at DESC
                   LIMIT $3""",
                end_user_id,
                character_id,
                max(2, fetch_limit),
            )
            candidates.extend(_stringify_row(row) for row in rule_rows)

        # Semantic neighbours: attach cosine similarity to rows we already have
        # and pull in nearest rows the weight-ordered fetch missed.
        sims = await self._fetch_vector_candidates(end_user_id, character_id, query, fetch_limit)
        if sims:
            seen = {str(c.get("id")) for c in candidates}
            for c in candidates:
                if str(c.get("id")) in sims:
                    c["vector_sim"] = sims[str(c["id"])]
            missing = [mid for mid in sims if mid not in seen]
            if missing:
                candidates.extend(await self._fetch_rows_by_id(end_user_id, missing, sims))

        return rank_memory_candidates(
            candidates,
            query=query,
            context=context,
            limit=max(limit * 2, limit),
        )

    async def _fetch_rows_by_id(
        self, end_user_id: str, ids: list[str], sims: dict[str, float]
    ) -> list[dict]:
        out: list[dict] = []
        async with self.pool.acquire() as conn:
            for layer, table in _LAYER_TABLES.items():
                time_col = "created_at" if table == "episodic_memories" else "updated_at"
                extra_cols = (
                    "relation_axis"
                    if table == "relational_memories"
                    else "NULL::TEXT AS relation_axis"
                )
                rows = await conn.fetch(
                    f"""SELECT id, $1::UUID AS user_id,
                              $3::TEXT AS memory_table, $4::TEXT AS memory_layer,
                              content, confidence_score, emotional_valence,
                              sensitivity_level::TEXT, permission_level::TEXT,
                              retrieval_weight, importance_score, decay_rate,
                              last_used_at, usage_count, timestamp, created_at,
                              {time_col} AS updated_at,
                              conflict_status::TEXT, can_surface_directly, implicit_only,
                              requires_confirmation, frozen_at, deleted_at,
                              character_id, {extra_cols}
                       FROM {table}
                       WHERE user_id = $1 AND id = ANY($2::uuid[])
                         AND deleted_at IS NULL AND permission_level <> 'DENIED'""",
                    end_user_id,
                    ids,
                    table,
                    layer,
                )
                for row in rows:
                    item = _stringify_row(row)
                    item["vector_sim"] = sims.get(str(item.get("id")))
                    out.append(item)
        return out

    def _to_prompt_memory(self, memory: dict, use_mode: str) -> dict:
        layer = memory.get("memory_layer", "EPISODIC")
        content = memory.get("content", "")
        if memory.get("memory_table") == "compiled_behavior_rules":
            prompt_text = f"[编译行为规则] {content}"
        elif use_mode == "DIRECT_SURFACE":
            prompt_text = f"[可自然提及] {content}"
        elif layer == "RELATIONAL":
            prompt_text = f"[隐性关系策略，不要直说来源] {content}"
        elif layer == "PROFILE":
            prompt_text = f"[隐性长期画像，不要直说来源] {content}"
        elif layer == "SEMANTIC":
            prompt_text = f"[隐性长期理解，不要直说来源] {content}"
        else:
            prompt_text = f"[隐性事件碎片，只在非常相关时才用] {content}"

        return {
            "id": memory.get("id"),
            "type": layer,
            "memory_layer": layer,
            "content": content,
            "prompt_text": prompt_text,
            "use_mode": use_mode,
            "memory_table": memory.get("memory_table"),
            "retrieval_score": memory.get("retrieval_score"),
            "retrieval_score_parts": memory.get("retrieval_score_parts"),
        }

    def _build_robot_behavior_hints(self, memories: list[dict]) -> dict:
        text = " ".join(m.get("content", "") for m in memories)
        hints: dict[str, str | float] = {}
        if any(k in text for k in ("疲惫", "累", "焦虑", "低打扰", "安静")):
            hints.update(
                {
                    "speech_policy": "low_disturbance",
                    "eye": "soft_hold",
                    "light": "warm_low",
                    "motion_intensity": 0.2,
                }
            )
        if any(k in text for k in ("直接", "事实", "风险", "先结论", "少废话")):
            hints.update(
                {
                    "speech_policy": "direct",
                    "motion_intensity": min(float(hints.get("motion_intensity", 0.35)), 0.35),
                }
            )
        return hints

    async def _mark_used(self, memory: dict, use_mode: str, response_id: str | None = None) -> None:
        table = memory.get("memory_table")
        if table not in _MEMORY_TABLES:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"""UPDATE {table}
                        SET last_used_at = now(), usage_count = usage_count + 1
                        WHERE id = $1""",
                    memory["id"],
                )
                await conn.execute(
                    """INSERT INTO memory_usage_logs
                       (id, response_id, user_id, character_id, memory_id, memory_table,
                        use_mode, channel, policy_reason, created_at)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, 'prompt', $7, now())""",
                    response_id,
                    memory.get("user_id"),
                    memory.get("character_id"),
                    memory.get("id"),
                    table,
                    use_mode,
                    "retrieved_for_prompt",
                )
        except Exception as e:
            logger.warning("memory.mark_used_failed", error=str(e), table=table)

    async def _retrieve_legacy_memories(
        self, end_user_id: str, character_id: str, limit: int = _MAX_MEMORIES
    ) -> list[dict]:
        cache_key = f"memories:{end_user_id}:{character_id}"
        cached = await self.cache.get_json(cache_key)
        if cached is not None:
            return cached

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT type, content FROM conversation_memories
                   WHERE end_user_id = $1 AND character_id = $2
                   ORDER BY created_at DESC
                   LIMIT $3""",
                end_user_id,
                character_id,
                limit,
            )

        memories = [{"type": row["type"], "content": row["content"]} for row in rows]
        await self.cache.set_json(cache_key, memories, ttl=_MEMORY_CACHE_TTL)
        return memories

    def format_memories_for_prompt(self, memories: list[dict]) -> list[str]:
        result = []
        for m in memories:
            if m.get("prompt_text"):
                result.append(m["prompt_text"])
                continue
            fmt = _LEGACY_MEMORY_FORMAT.get(m.get("type", ""), "主人说过{content}")
            result.append(fmt.format(content=m.get("content", "")))
        return result

    # ─── Write path ────────────────────────────────

    async def extract_and_store(
        self,
        end_user_id: str,
        character_id: str,
        session_id: str,
        user_input: str,
        ai_response: str,
    ) -> None:
        if not end_user_id:
            return

        try:
            memories = await asyncio.wait_for(
                self._extract_memories(user_input, ai_response),
                timeout=_EXTRACTION_TIMEOUT,
            )
            if not memories:
                return

            if await self._has_new_schema():
                await self._store_new_memories(
                    end_user_id=end_user_id,
                    character_id=character_id,
                    session_id=session_id,
                    user_input=user_input,
                    ai_response=ai_response,
                    memories=memories,
                )
            else:
                await self._store_legacy_memories(
                    end_user_id, character_id, session_id, user_input, memories
                )

            await self.cache.delete(f"memories:{end_user_id}:{character_id}")
            logger.info(
                "memory.extracted",
                count=len(memories),
                end_user_id=end_user_id,
                character_id=character_id,
            )
        except TimeoutError:
            logger.warning("memory.extraction_timeout")
        except Exception:
            logger.exception("memory.extraction_error")

    async def _extract_memories(self, user_input: str, ai_response: str) -> list[dict]:
        prompt = _EXTRACTION_PROMPT.format(user_input=user_input, ai_response=ai_response)
        raw = await self.llm.chat(
            system_prompt="你是记忆提取助手，只输出JSON数组，不要其他内容。",
            user_input=prompt,
        )

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("memory.invalid_json", raw=raw[:200])
            return []

        if not isinstance(data, list):
            return []

        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            mem_type = item.get("type", "").upper()
            content = str(item.get("content", "")).strip()
            if mem_type in MEMORY_TYPES and content and len(content) <= 80:
                valid.append({"type": mem_type, "content": content})
        return valid[:5]

    async def _store_new_memories(
        self,
        end_user_id: str,
        character_id: str,
        session_id: str,
        user_input: str,
        ai_response: str,
        memories: list[dict],
    ) -> None:
        raw_source = {
            "session_id": session_id,
            "user_input": user_input,
            "ai_response": ai_response,
            "stored_at": datetime.now(UTC).isoformat(),
        }
        async with self.pool.acquire() as conn:
            for mem in memories:
                content = mem["content"]
                layer = self.policy.assign_layer(mem["type"], content)
                sensitivity = self.policy.classify_sensitivity(content)
                confidence = 0.78 if layer in {"PROFILE", "RELATIONAL"} else 0.7
                importance = self.policy.score_importance(content, layer)
                candidate = {
                    "memory_type": layer,
                    "content": content,
                    "sensitivity_level": sensitivity,
                    "confidence_score": confidence,
                    "importance_score": importance,
                }
                decision = self.policy.evaluate_write(candidate)
                if decision.decision == "REQUIRE_CONFIRMATION":
                    await self._insert_pending_confirmation(
                        conn, end_user_id, character_id, candidate, decision.reason
                    )
                    continue

                if layer == "PROFILE":
                    memory_id = await self._upsert_profile_memory(
                        conn,
                        end_user_id,
                        character_id,
                        content,
                        raw_source,
                        confidence,
                        sensitivity,
                        importance,
                    )
                    await self._create_policy(
                        conn,
                        end_user_id,
                        memory_id,
                        "profile_memories",
                        layer,
                        content,
                        sensitivity,
                        importance,
                    )
                elif layer == "RELATIONAL":
                    memory_id = await self._insert_relational_memory(
                        conn,
                        end_user_id,
                        character_id,
                        content,
                        raw_source,
                        confidence,
                        sensitivity,
                        importance,
                    )
                    await self._create_policy(
                        conn,
                        end_user_id,
                        memory_id,
                        "relational_memories",
                        layer,
                        content,
                        sensitivity,
                        importance,
                    )
                else:
                    memory_id = await self._insert_episodic_memory(
                        conn,
                        end_user_id,
                        character_id,
                        content,
                        raw_source,
                        confidence,
                        sensitivity,
                        importance,
                    )
                    await self._create_policy(
                        conn,
                        end_user_id,
                        memory_id,
                        "episodic_memories",
                        layer,
                        content,
                        sensitivity,
                        importance,
                    )

    async def _upsert_profile_memory(
        self,
        conn: asyncpg.Connection,
        end_user_id: str,
        character_id: str,
        content: str,
        raw_source: dict,
        confidence: float,
        sensitivity: str,
        importance: int,
    ) -> str:
        row = await conn.fetchrow(
            """INSERT INTO profile_memories
               (id, user_id, character_id, key, content, raw_source, confidence_score,
                sensitivity_level, permission_level, retrieval_weight, importance_score, updated_at)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5::jsonb, $6,
                       $7, 'AUTO', 1.0, $8, now())
               ON CONFLICT (user_id, character_id, key) DO UPDATE SET
                   content = EXCLUDED.content,
                   raw_source = EXCLUDED.raw_source,
                   confidence_score = GREATEST(
                       profile_memories.confidence_score,
                       EXCLUDED.confidence_score
                   ),
                   importance_score = GREATEST(
                       profile_memories.importance_score,
                       EXCLUDED.importance_score
                   ),
                   update_history = profile_memories.update_history ||
                       jsonb_build_array(
                           jsonb_build_object('updated_at', now(), 'reason', 'memory_refresh')
                       ),
                   updated_at = now()
               RETURNING id""",
            end_user_id,
            character_id,
            _stable_key(content),
            content,
            _json(raw_source),
            confidence,
            sensitivity,
            importance,
        )
        memory_id = str(row["id"])
        await self._store_embedding(conn, "profile_memories", memory_id, content)
        return memory_id

    async def _insert_episodic_memory(
        self,
        conn: asyncpg.Connection,
        end_user_id: str,
        character_id: str,
        content: str,
        raw_source: dict,
        confidence: float,
        sensitivity: str,
        importance: int,
    ) -> str:
        raw_transcript = {
            "user": raw_source.get("user_input"),
            "assistant": raw_source.get("ai_response"),
        }
        row = await conn.fetchrow(
            """INSERT INTO episodic_memories
               (id, user_id, character_id, content, raw_source, raw_transcript,
                confidence_score, sensitivity_level, permission_level, retrieval_weight,
                importance_score)
               VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, $5::jsonb,
                       $6, $7, 'AUTO', 0.6, $8)
               RETURNING id""",
            end_user_id,
            character_id,
            content,
            _json(raw_source),
            _json(raw_transcript),
            confidence,
            sensitivity,
            importance,
        )
        memory_id = str(row["id"])
        await self._store_embedding(conn, "episodic_memories", memory_id, content)
        return memory_id

    async def _insert_relational_memory(
        self,
        conn: asyncpg.Connection,
        end_user_id: str,
        character_id: str,
        content: str,
        raw_source: dict,
        confidence: float,
        sensitivity: str,
        importance: int,
    ) -> str:
        row = await conn.fetchrow(
            """INSERT INTO relational_memories
               (id, user_id, character_id, content, relation_axis, raw_source,
                confidence_score, sensitivity_level, permission_level, retrieval_weight,
                importance_score)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5::jsonb, $6, $7, 'AUTO', 1.0,
                       $8)
               RETURNING id""",
            end_user_id,
            character_id,
            content,
            self.policy.relation_axis(content),
            _json(raw_source),
            confidence,
            sensitivity,
            importance,
        )
        memory_id = str(row["id"])
        await self._store_embedding(conn, "relational_memories", memory_id, content)
        return memory_id

    async def _insert_pending_confirmation(
        self,
        conn: asyncpg.Connection,
        end_user_id: str,
        character_id: str,
        candidate: dict,
        reason: str,
    ) -> None:
        await conn.execute(
            """INSERT INTO memory_pending_confirmations
               (id, user_id, character_id, proposed_memory, reason, expires_at)
               VALUES (gen_random_uuid(), $1, $2, $3::jsonb, $4, $5)""",
            end_user_id,
            character_id,
            _json(candidate),
            reason,
            datetime.now(UTC) + timedelta(days=7),
        )

    async def _create_policy(
        self,
        conn: asyncpg.Connection,
        end_user_id: str,
        memory_id: str,
        table: str,
        layer: str,
        content: str,
        sensitivity: str,
        importance: int,
    ) -> None:
        use_mode = "IMPLICIT_ONLY"
        await conn.execute(
            """INSERT INTO memory_policies
               (id, user_id, memory_id, memory_table, memory_type, content,
                sensitivity_level, permission_level, importance_score, use_mode,
                can_surface_directly,
                implicit_only, allowed_channels)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, 'AUTO',
                       $7, $8, false, true, ARRAY['response_style', 'robot_behavior']::TEXT[])""",
            end_user_id,
            memory_id,
            table,
            layer,
            content,
            sensitivity,
            importance,
            use_mode,
        )

    async def _store_legacy_memories(
        self,
        end_user_id: str,
        character_id: str,
        session_id: str,
        source: str,
        memories: list[dict],
    ) -> None:
        async with self.pool.acquire() as conn:
            for mem in memories:
                existing = await conn.fetchval(
                    """SELECT 1 FROM conversation_memories
                       WHERE end_user_id = $1 AND character_id = $2 AND content = $3
                       LIMIT 1""",
                    end_user_id,
                    character_id,
                    mem["content"],
                )
                if existing:
                    continue
                await conn.execute(
                    """INSERT INTO conversation_memories
                       (id, end_user_id, character_id, type, content, source,
                        session_id, created_at)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, now())""",
                    end_user_id,
                    character_id,
                    mem["type"],
                    mem["content"],
                    source[:500] if source else None,
                    session_id,
                )

    # ─── API helpers ───────────────────────────────

    async def record_raw_event(self, payload: dict) -> dict:
        if not await self._has_raw_event_schema():
            raise RuntimeError("raw event log schema is not migrated")

        event_type = str(payload.get("event_type") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not event_type:
            raise ValueError("event_type is required")
        if not content:
            raise ValueError("content is required")

        sensitivity = payload.get("sensitivity_level") or self.policy.classify_sensitivity(content)
        importance = max(
            1,
            min(
                10,
                int(
                    payload.get("importance_score")
                    or self.policy.score_importance(content, "EPISODIC")
                ),
            ),
        )
        observed_at = payload.get("observed_at") or datetime.now(UTC)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO raw_event_logs
                   (id, user_id, character_id, device_id, session_id, event_type,
                    source, content, payload, context, importance_score,
                    sensitivity_level, observed_at)
                   VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7,
                           $8::jsonb, $9::jsonb, $10, $11, $12)
                   RETURNING id, user_id, character_id, device_id, session_id,
                             event_type, source, content, payload, context,
                             importance_score, sensitivity_level::TEXT,
                             observed_at, created_at""",
                payload["user_id"],
                payload.get("character_id"),
                payload.get("device_id"),
                payload.get("session_id"),
                event_type,
                str(payload.get("source") or "api")[:50],
                content,
                _json(payload.get("payload") or {}),
                _json(payload.get("context") or {}),
                importance,
                sensitivity,
                observed_at,
            )
        return _stringify_row(row)

    async def list_raw_events(
        self,
        user_id: str,
        character_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if not await self._has_raw_event_schema():
            raise RuntimeError("raw event log schema is not migrated")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, user_id, character_id, device_id, session_id,
                          event_type, source, content, payload, context,
                          importance_score, sensitivity_level::TEXT,
                          observed_at, created_at
                   FROM raw_event_logs
                   WHERE user_id = $1
                     AND ($2::UUID IS NULL OR character_id = $2)
                   ORDER BY observed_at DESC, created_at DESC
                   LIMIT $3""",
                user_id,
                character_id,
                limit,
            )
        return [_stringify_row(row) for row in rows]

    async def create_memory(self, payload: dict) -> dict:
        if not await self._has_new_schema():
            raise RuntimeError("companion memory schema is not migrated")
        layer = payload.get("memory_type", "EPISODIC").upper()
        if layer not in _LAYER_TABLES:
            raise ValueError(f"Unsupported memory_type: {layer}")
        content = str(payload.get("content", "")).strip()
        if not content:
            raise ValueError("content is required")

        sensitivity = payload.get("sensitivity_level") or self.policy.classify_sensitivity(content)
        confidence = float(payload.get("confidence_score", 0.8))
        importance = int(
            payload.get("importance_score") or self.policy.score_importance(content, layer)
        )
        raw_source = payload.get("raw_source") or {}
        user_id = payload["user_id"]
        character_id = payload.get("character_id")

        async with self.pool.acquire() as conn:
            if layer == "PROFILE":
                memory_id = await self._upsert_profile_memory(
                    conn,
                    user_id,
                    character_id,
                    content,
                    raw_source,
                    confidence,
                    sensitivity,
                    importance,
                )
                table = "profile_memories"
            elif layer == "RELATIONAL":
                memory_id = await self._insert_relational_memory(
                    conn,
                    user_id,
                    character_id,
                    content,
                    raw_source,
                    confidence,
                    sensitivity,
                    importance,
                )
                table = "relational_memories"
            elif layer == "SEMANTIC":
                row = await conn.fetchrow(
                    """INSERT INTO semantic_memories
                       (id, user_id, character_id, content, raw_source, confidence_score,
                        sensitivity_level, permission_level, evidence_count, importance_score)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
                       RETURNING id""",
                    user_id,
                    character_id,
                    content,
                    _json(raw_source),
                    confidence,
                    sensitivity,
                    payload.get("permission_level", "AUTO"),
                    int(payload.get("evidence_count", 0)),
                    importance,
                )
                memory_id = str(row["id"])
                table = "semantic_memories"
                await self._store_embedding(conn, table, memory_id, content)
            else:
                memory_id = await self._insert_episodic_memory(
                    conn,
                    user_id,
                    character_id,
                    content,
                    raw_source,
                    confidence,
                    sensitivity,
                    importance,
                )
                table = "episodic_memories"

            await self._create_policy(
                conn, user_id, memory_id, table, layer, content, sensitivity, importance
            )

        return {"id": memory_id, "memory_type": layer, "status": "created"}

    async def update_memory(self, memory_id: str, payload: dict) -> dict:
        table, layer = await self._find_memory_table(memory_id)
        if not table:
            raise KeyError(memory_id)
        updates = []
        values: list[Any] = []
        if "content" in payload:
            values.append(payload["content"])
            updates.append(f"content = ${len(values)}")
        if "confidence_score" in payload:
            values.append(float(payload["confidence_score"]))
            updates.append(f"confidence_score = ${len(values)}")
        if "importance_score" in payload:
            values.append(max(1, min(10, int(payload["importance_score"]))))
            updates.append(f"importance_score = ${len(values)}")
        if "implicit_only" in payload:
            values.append(bool(payload["implicit_only"]))
            updates.append(f"implicit_only = ${len(values)}")
        if "can_surface_directly" in payload:
            values.append(bool(payload["can_surface_directly"]))
            updates.append(f"can_surface_directly = ${len(values)}")
        if not updates:
            return {"id": memory_id, "memory_type": layer, "status": "unchanged"}

        history = {
            "updated_at": datetime.now(UTC).isoformat(),
            "reason": payload.get("update_reason", "api_update"),
        }
        updated_at_clause = ", updated_at = now()" if table != "episodic_memories" else ""
        history_param = len(values) + 1
        id_param = len(values) + 2
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""UPDATE {table}
                    SET {", ".join(updates)},
                        update_history = update_history ||
                            jsonb_build_array(${history_param}::jsonb)
                        {updated_at_clause}
                    WHERE id = ${id_param}""",
                *values,
                _json(history),
                memory_id,
            )
        return {"id": memory_id, "memory_type": layer, "status": "updated"}

    async def delete_memory(self, memory_id: str, cascade_compiled_rules: bool = True) -> dict:
        table, layer = await self._find_memory_table(memory_id)
        if not table:
            raise KeyError(memory_id)
        async with self.pool.acquire() as conn:
            if table == "compiled_behavior_rules":
                await conn.execute(
                    """UPDATE compiled_behavior_rules
                       SET enabled = false, updated_at = now()
                       WHERE id = $1""",
                    memory_id,
                )
            else:
                await conn.execute(
                    f"UPDATE {table} SET deleted_at = now() WHERE id = $1",
                    memory_id,
                )
            affected_rules: list[str] = []
            if cascade_compiled_rules:
                rows = await conn.fetch(
                    """UPDATE compiled_behavior_rules
                       SET enabled = false, updated_at = now()
                       WHERE $1::uuid = ANY(source_memory_ids)
                       RETURNING id""",
                    memory_id,
                )
                affected_rules = [str(r["id"]) for r in rows]
        return {
            "id": memory_id,
            "memory_type": layer,
            "status": "deleted",
            "affected_compiled_rules": affected_rules,
        }

    async def feedback_on_memory(
        self, memory_id: str, feedback: str, comment: str | None = None
    ) -> dict:
        table, layer = await self._find_memory_table(memory_id)
        if not table:
            raise KeyError(memory_id)
        if feedback not in {"wrong", "sensitive", "use_less", "good"}:
            raise ValueError("unsupported feedback")
        history = {
            "feedback": feedback,
            "comment": comment,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        confidence_expr = "confidence_score"
        conflict = "conflict_status"
        if feedback == "wrong":
            confidence_expr = "GREATEST(0.0, confidence_score - 0.35)"
            conflict = "'POTENTIAL'"
        elif feedback == "use_less":
            confidence_expr = "GREATEST(0.0, confidence_score - 0.1)"
        elif feedback == "good":
            confidence_expr = "LEAST(1.0, confidence_score + 0.05)"

        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""UPDATE {table}
                    SET confidence_score = {confidence_expr},
                        conflict_status = {conflict},
                        update_history = update_history || jsonb_build_array($2::jsonb)
                    WHERE id = $1""",
                memory_id,
                _json(history),
            )
        return {"id": memory_id, "memory_type": layer, "status": "feedback_recorded"}

    async def reflect_memory(
        self,
        user_id: str,
        character_id: str | None,
        trigger: str = "manual",
        dry_run: bool = False,
        limit: int = 100,
        min_importance_sum: int = 12,
    ) -> dict:
        """Generate evidence-backed reflection proposals and behavior rules."""
        if not await self._has_new_schema():
            raise RuntimeError("companion memory schema is not migrated")
        if not await self._has_reflection_schema():
            raise RuntimeError("memory reflection schema is not migrated")

        memories = await self._fetch_reflection_sources(user_id, character_id, limit=limit)
        importance_sum = sum(int(memory.get("importance_score") or 0) for memory in memories)
        if trigger != "manual" and importance_sum < min_importance_sum:
            return {
                "reflection_ids": [],
                "compiled_rule_ids": [],
                "proposal_count": 0,
                "skipped": True,
                "reason": "importance_threshold_not_met",
                "importance_sum": importance_sum,
            }

        proposals = build_reflection_proposals(memories, self.policy)
        if dry_run:
            return {
                "reflection_ids": [],
                "compiled_rule_ids": [],
                "proposal_count": len(proposals),
                "skipped": False,
                "importance_sum": importance_sum,
                "proposals": proposals,
            }

        reflection_ids: list[str] = []
        compiled_rule_ids: list[str] = []
        async with self.pool.acquire() as conn:
            for proposal in proposals:
                existing_reflection = await conn.fetchval(
                    """SELECT id
                       FROM memory_reflections
                       WHERE user_id = $1
                         AND (character_id = $2 OR (character_id IS NULL AND $2::uuid IS NULL))
                         AND insight = $3
                         AND status <> 'reverted'
                       LIMIT 1""",
                    user_id,
                    character_id,
                    proposal["insight"],
                )
                if existing_reflection:
                    reflection_ids.append(str(existing_reflection))
                else:
                    inserted = await conn.fetchrow(
                        """INSERT INTO memory_reflections
                           (id, user_id, character_id, question, insight, evidence_refs,
                            target_layer, policy_action, status, confidence_score,
                            sensitivity_level, raw_source, created_at, updated_at)
                           VALUES (gen_random_uuid(), $1, $2, $3, $4, $5::uuid[],
                                   $6, $7, $8, $9, $10, $11::jsonb, now(), now())
                           RETURNING id""",
                        user_id,
                        character_id,
                        proposal["question"],
                        proposal["insight"],
                        proposal["evidence_refs"],
                        proposal["target_layer"],
                        proposal["policy_action"],
                        proposal["status"],
                        proposal["confidence_score"],
                        proposal["sensitivity_level"],
                        _json(proposal["raw_source"]),
                    )
                    reflection_ids.append(str(inserted["id"]))

                if proposal["status"] != "applied" or not proposal.get("rule_content"):
                    continue
                existing_rule = await conn.fetchval(
                    """SELECT id
                       FROM compiled_behavior_rules
                       WHERE user_id = $1
                         AND (character_id = $2 OR (character_id IS NULL AND $2::uuid IS NULL))
                         AND content = $3
                         AND enabled = true
                       LIMIT 1""",
                    user_id,
                    character_id,
                    proposal["rule_content"],
                )
                if existing_rule:
                    compiled_rule_ids.append(str(existing_rule))
                    continue
                rule = await conn.fetchrow(
                    """INSERT INTO compiled_behavior_rules
                       (id, user_id, character_id, rule_type, trigger, content,
                        raw_source, source_memory_ids, sensitivity_level, permission_level,
                        retrieval_weight, importance_score, implicit_only, enabled)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, $5, $6::jsonb,
                               $7::uuid[], $8, 'AUTO', 1.0, $9, true, true)
                       RETURNING id""",
                    user_id,
                    character_id,
                    proposal["rule_type"],
                    _json({"source": "memory_reflection", "trigger": trigger}),
                    proposal["rule_content"],
                    _json(
                        {
                            "compiled_at": datetime.now(UTC).isoformat(),
                            "reflection_insight": proposal["insight"],
                        }
                    ),
                    proposal["evidence_refs"],
                    proposal["sensitivity_level"],
                    proposal["importance_score"],
                )
                compiled_rule_ids.append(str(rule["id"]))

        return {
            "reflection_ids": reflection_ids,
            "compiled_rule_ids": compiled_rule_ids,
            "proposal_count": len(proposals),
            "skipped": False,
            "importance_sum": importance_sum,
        }

    async def _fetch_reflection_sources(
        self, user_id: str, character_id: str | None, limit: int = 100
    ) -> list[dict]:
        rows: list[dict] = []
        async with self.pool.acquire() as conn:
            for layer, table in _LAYER_TABLES.items():
                time_col = "created_at" if table == "episodic_memories" else "updated_at"
                fetched = await conn.fetch(
                    f"""SELECT id, $3::TEXT AS memory_table, $4::TEXT AS memory_layer,
                              content, confidence_score, sensitivity_level::TEXT,
                              retrieval_weight, importance_score, timestamp, created_at,
                              {time_col} AS updated_at
                       FROM {table}
                       WHERE user_id = $1
                         AND (character_id = $2 OR character_id IS NULL)
                         AND deleted_at IS NULL
                         AND permission_level <> 'DENIED'
                       ORDER BY importance_score DESC, {time_col} DESC
                       LIMIT $5""",
                    user_id,
                    character_id,
                    table,
                    layer,
                    max(10, limit // len(_REFLECTION_SOURCE_TABLES)),
                )
                rows.extend(_stringify_row(row) for row in fetched)

        rows.sort(
            key=lambda row: (
                int(row.get("importance_score") or 0),
                _parse_dt(row.get("updated_at") or row.get("created_at"))
                or datetime.min.replace(tzinfo=UTC),
            ),
            reverse=True,
        )
        return rows[:limit]

    async def list_reflections(
        self, user_id: str, character_id: str | None, limit: int = 50
    ) -> list[dict]:
        if not await self._has_reflection_schema():
            raise RuntimeError("memory reflection schema is not migrated")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, user_id, character_id, question, insight, evidence_refs,
                          target_layer, policy_action, status, confidence_score,
                          sensitivity_level::TEXT, raw_source, created_at, updated_at
                   FROM memory_reflections
                   WHERE user_id = $1
                     AND (character_id = $2 OR character_id IS NULL)
                   ORDER BY created_at DESC
                   LIMIT $3""",
                user_id,
                character_id,
                limit,
            )
        return [_stringify_row(row) for row in rows]

    async def compile_memory(self, user_id: str, character_id: str | None) -> dict:
        if not await self._has_new_schema():
            raise RuntimeError("companion memory schema is not migrated")
        compiled_ids: list[str] = []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, 'RELATIONAL'::TEXT AS layer, content, relation_axis
                   FROM relational_memories
                   WHERE user_id = $1 AND (character_id = $2 OR character_id IS NULL)
                     AND deleted_at IS NULL AND confidence_score >= 0.72
                   UNION ALL
                   SELECT id, 'PROFILE'::TEXT AS layer, content,
                          'response_style'::TEXT AS relation_axis
                   FROM profile_memories
                   WHERE user_id = $1 AND (character_id = $2 OR character_id IS NULL)
                     AND deleted_at IS NULL AND confidence_score >= 0.78
                     AND (content ILIKE '%直接%' OR content ILIKE '%事实%' OR content ILIKE '%风险%'
                          OR content ILIKE '%机械眼球%' OR content ILIKE '%屏幕%')""",
                user_id,
                character_id,
            )
            for row in rows:
                rule_type, rule_content = self._compile_rule_text(
                    row["content"], row["relation_axis"]
                )
                if not rule_content:
                    continue
                existing = await conn.fetchval(
                    """SELECT 1 FROM compiled_behavior_rules
                       WHERE user_id = $1 AND (character_id = $2 OR character_id IS NULL)
                         AND content = $3 AND enabled = true
                       LIMIT 1""",
                    user_id,
                    character_id,
                    rule_content,
                )
                if existing:
                    continue
                inserted = await conn.fetchrow(
                    """INSERT INTO compiled_behavior_rules
                       (id, user_id, character_id, rule_type, trigger, content,
                        raw_source, source_memory_ids, sensitivity_level, permission_level,
                        retrieval_weight, implicit_only)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, $5, $6::jsonb,
                               ARRAY[$7::uuid], 'LOW', 'AUTO', 1.0, true)
                       RETURNING id""",
                    user_id,
                    character_id,
                    rule_type,
                    _json({"source": "memory_compilation_mvp"}),
                    rule_content,
                    _json({"compiled_at": datetime.now(UTC).isoformat()}),
                    row["id"],
                )
                compiled_ids.append(str(inserted["id"]))
        return {"compiled_rule_ids": compiled_ids, "disabled_rule_ids": []}

    def _compile_rule_text(self, content: str, axis: str) -> tuple[str, str | None]:
        if axis == "directness" or any(k in content for k in ("直接", "事实", "风险", "结论")):
            return (
                "reasoning_strategy",
                "当用户讨论决策、创业或技术方案时，先给结论和最大风险，再给最小可验证行动；避免空泛鼓励。",
            )
        if axis == "rhythm" or any(k in content for k in ("疲惫", "焦虑", "低打扰", "安静")):
            return (
                "interaction_rhythm",
                "当用户表现疲惫或焦虑时，降低追问密度，语速放慢，用低打扰方式陪伴。",
            )
        if any(k in content for k in ("机械眼球", "屏幕表情", "桌面审美")):
            return (
                "robot_behavior",
                "当用户讨论机器人外观时，优先考虑机械眼球、非屏幕表情和桌面审美，但不要明说来自记忆。",
            )
        return ("response_style", content)

    async def decay_memory(self, user_id: str, dry_run: bool = True) -> dict:
        if not await self._has_new_schema():
            raise RuntimeError("companion memory schema is not migrated")
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                """SELECT count(*) FROM episodic_memories
                   WHERE user_id = $1 AND deleted_at IS NULL
                     AND created_at < now() - interval '30 days'
                     AND retrieval_weight > 0.1""",
                user_id,
            )
            if not dry_run:
                await conn.execute(
                    """UPDATE episodic_memories
                       SET retrieval_weight = GREATEST(0.1, retrieval_weight * 0.9)
                       WHERE user_id = $1 AND deleted_at IS NULL
                         AND created_at < now() - interval '30 days'
                         AND retrieval_weight > 0.1""",
                    user_id,
                )
        return {"would_decay": int(count or 0), "would_archive": 0, "dry_run": dry_run}

    async def explain_memory_usage(self, usage_id: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, response_id, memory_id, memory_table, use_mode::TEXT,
                          channel, surfaced_text, policy_reason, created_at
                   FROM memory_usage_logs
                   WHERE id = $1 OR response_id = $2
                   ORDER BY created_at DESC
                   LIMIT 1""",
                usage_id,
                usage_id,
            )
        if not row:
            raise KeyError(usage_id)
        return _stringify_row(row)

    async def _find_memory_table(self, memory_id: str) -> tuple[str | None, str | None]:
        if not await self._has_new_schema():
            return None, None
        async with self.pool.acquire() as conn:
            for table in _MEMORY_TABLES:
                row = await conn.fetchrow(
                    f"SELECT id FROM {table} WHERE id = $1 LIMIT 1",
                    memory_id,
                )
                if row:
                    return table, _TABLE_LAYERS.get(table, "COMPILED")
        return None, None
