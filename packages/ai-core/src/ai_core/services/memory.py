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
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import structlog

from ai_core.services.cache import CacheService
from ai_core.services.llm_client import LLMClient
from ai_core.services.memory_policy import MemoryPolicyEngine

logger = structlog.get_logger()

MEMORY_TYPES = ("TOPIC", "PREFERENCE", "EVENT")
MEMORY_LAYERS = ("PROFILE", "EPISODIC", "SEMANTIC", "RELATIONAL")
_MEMORY_CACHE_TTL = 1800
_MAX_MEMORIES = 10
_EXTRACTION_TIMEOUT = 8

_LAYER_TABLES = {
    "PROFILE": "profile_memories",
    "EPISODIC": "episodic_memories",
    "SEMANTIC": "semantic_memories",
    "RELATIONAL": "relational_memories",
}
_TABLE_LAYERS = {table: layer for layer, table in _LAYER_TABLES.items()}
_MEMORY_TABLES = tuple(_LAYER_TABLES.values()) + ("compiled_behavior_rules",)

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


class MemoryService:
    """Extract, store, retrieve, and govern companion memories."""

    def __init__(self, pool: asyncpg.Pool, llm: LLMClient, cache: CacheService):
        self.pool = pool
        self.llm = llm
        self.cache = cache
        self.policy = MemoryPolicyEngine()
        self._new_schema_available: bool | None = None

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
        candidates = await self._fetch_memory_candidates(end_user_id, character_id, limit)

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
        self, end_user_id: str, character_id: str, limit: int
    ) -> list[dict]:
        candidates: list[dict] = []
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
                              retrieval_weight, decay_rate, last_used_at, usage_count,
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
                    max(2, limit),
                    table,
                    layer,
                )
                candidates.extend(_stringify_row(row) for row in rows)

            rule_rows = await conn.fetch(
                """SELECT id, $1::UUID AS user_id, 'compiled_behavior_rules'::TEXT AS memory_table,
                          'COMPILED'::TEXT AS memory_layer,
                          content, confidence_score, emotional_valence,
                          sensitivity_level::TEXT, permission_level::TEXT,
                          retrieval_weight, decay_rate, last_used_at, usage_count,
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
                max(2, limit),
            )
            candidates.extend(_stringify_row(row) for row in rule_rows)

        candidates.sort(
            key=lambda m: (
                float(m.get("retrieval_weight") or 0),
                float(m.get("confidence_score") or 0),
            ),
            reverse=True,
        )
        return candidates[: max(limit * 2, limit)]

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
                candidate = {
                    "memory_type": layer,
                    "content": content,
                    "sensitivity_level": sensitivity,
                    "confidence_score": confidence,
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
                    )
                    await self._create_policy(
                        conn,
                        end_user_id,
                        memory_id,
                        "profile_memories",
                        layer,
                        content,
                        sensitivity,
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
                    )
                    await self._create_policy(
                        conn,
                        end_user_id,
                        memory_id,
                        "relational_memories",
                        layer,
                        content,
                        sensitivity,
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
                    )
                    await self._create_policy(
                        conn,
                        end_user_id,
                        memory_id,
                        "episodic_memories",
                        layer,
                        content,
                        sensitivity,
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
    ) -> str:
        row = await conn.fetchrow(
            """INSERT INTO profile_memories
               (id, user_id, character_id, key, content, raw_source, confidence_score,
                sensitivity_level, permission_level, retrieval_weight, updated_at)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5::jsonb, $6,
                       $7, 'AUTO', 1.0, now())
               ON CONFLICT (user_id, character_id, key) DO UPDATE SET
                   content = EXCLUDED.content,
                   raw_source = EXCLUDED.raw_source,
                   confidence_score = GREATEST(
                       profile_memories.confidence_score,
                       EXCLUDED.confidence_score
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
        )
        return str(row["id"])

    async def _insert_episodic_memory(
        self,
        conn: asyncpg.Connection,
        end_user_id: str,
        character_id: str,
        content: str,
        raw_source: dict,
        confidence: float,
        sensitivity: str,
    ) -> str:
        raw_transcript = {
            "user": raw_source.get("user_input"),
            "assistant": raw_source.get("ai_response"),
        }
        row = await conn.fetchrow(
            """INSERT INTO episodic_memories
               (id, user_id, character_id, content, raw_source, raw_transcript,
                confidence_score, sensitivity_level, permission_level, retrieval_weight)
               VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, $5::jsonb,
                       $6, $7, 'AUTO', 0.6)
               RETURNING id""",
            end_user_id,
            character_id,
            content,
            _json(raw_source),
            _json(raw_transcript),
            confidence,
            sensitivity,
        )
        return str(row["id"])

    async def _insert_relational_memory(
        self,
        conn: asyncpg.Connection,
        end_user_id: str,
        character_id: str,
        content: str,
        raw_source: dict,
        confidence: float,
        sensitivity: str,
    ) -> str:
        row = await conn.fetchrow(
            """INSERT INTO relational_memories
               (id, user_id, character_id, content, relation_axis, raw_source,
                confidence_score, sensitivity_level, permission_level, retrieval_weight)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5::jsonb, $6, $7, 'AUTO', 1.0)
               RETURNING id""",
            end_user_id,
            character_id,
            content,
            self.policy.relation_axis(content),
            _json(raw_source),
            confidence,
            sensitivity,
        )
        return str(row["id"])

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
    ) -> None:
        use_mode = "IMPLICIT_ONLY"
        await conn.execute(
            """INSERT INTO memory_policies
               (id, user_id, memory_id, memory_table, memory_type, content,
                sensitivity_level, permission_level, use_mode, can_surface_directly,
                implicit_only, allowed_channels)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, 'AUTO',
                       $7, false, true, ARRAY['response_style', 'robot_behavior']::TEXT[])""",
            end_user_id,
            memory_id,
            table,
            layer,
            content,
            sensitivity,
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
        raw_source = payload.get("raw_source") or {}
        user_id = payload["user_id"]
        character_id = payload.get("character_id")

        async with self.pool.acquire() as conn:
            if layer == "PROFILE":
                memory_id = await self._upsert_profile_memory(
                    conn, user_id, character_id, content, raw_source, confidence, sensitivity
                )
                table = "profile_memories"
            elif layer == "RELATIONAL":
                memory_id = await self._insert_relational_memory(
                    conn, user_id, character_id, content, raw_source, confidence, sensitivity
                )
                table = "relational_memories"
            elif layer == "SEMANTIC":
                row = await conn.fetchrow(
                    """INSERT INTO semantic_memories
                       (id, user_id, character_id, content, raw_source, confidence_score,
                        sensitivity_level, permission_level, evidence_count)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, $5, $6, $7, $8)
                       RETURNING id""",
                    user_id,
                    character_id,
                    content,
                    _json(raw_source),
                    confidence,
                    sensitivity,
                    payload.get("permission_level", "AUTO"),
                    int(payload.get("evidence_count", 0)),
                )
                memory_id = str(row["id"])
                table = "semantic_memories"
            else:
                memory_id = await self._insert_episodic_memory(
                    conn, user_id, character_id, content, raw_source, confidence, sensitivity
                )
                table = "episodic_memories"

            await self._create_policy(conn, user_id, memory_id, table, layer, content, sensitivity)

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
