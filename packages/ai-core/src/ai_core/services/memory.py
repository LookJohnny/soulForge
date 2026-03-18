"""Conversation Memory Layer — extracts, stores, and retrieves long-term memories.

After each conversation turn, key facts are extracted by the LLM and stored
in PostgreSQL. On the next conversation, relevant memories are retrieved
and injected into the system prompt so the character can reference past topics.

Memory types:
- topic: what was discussed ("上次聊了恐龙")
- preference: user likes/dislikes ("主人喜欢画画")
- event: something the user mentioned ("主人说今天考试了")
"""

import asyncio
import json

import asyncpg
import structlog

from ai_core.services.cache import CacheService
from ai_core.services.llm_client import LLMClient

logger = structlog.get_logger()

MEMORY_TYPES = ("TOPIC", "PREFERENCE", "EVENT")
_MEMORY_CACHE_TTL = 1800  # 30 min cache per session
_MAX_MEMORIES = 10
_EXTRACTION_TIMEOUT = 8  # seconds

# LLM prompt for memory extraction (Chinese, structured output)
_EXTRACTION_PROMPT = """你是一个记忆提取助手。请从以下对话中提取值得记住的信息。

用户说: {user_input}
角色回复: {ai_response}

请提取以下类型的记忆（如果有的话）:
- TOPIC: 聊了什么话题（如"恐龙"、"学校"、"画画"）
- PREFERENCE: 用户的喜好或厌恶（如"喜欢恐龙"、"不喜欢吃青菜"）
- EVENT: 用户提到的事件（如"今天考试了"、"下周要去旅行"）

规则:
- 每条记忆不超过20个字
- 只提取有意义的、值得下次提起的信息
- 日常寒暄（"你好"、"再见"）不需要记住
- 以JSON数组格式回复，如果没有值得记住的信息回复 []

格式: [{"type": "PREFERENCE", "content": "喜欢恐龙"}]"""


# Format memories for system prompt injection
_MEMORY_FORMAT = {
    "TOPIC": "上次聊了{content}",
    "PREFERENCE": "主人{content}",
    "EVENT": "主人说过{content}",
}


class MemoryService:
    """Extract, store, and retrieve conversation memories."""

    def __init__(self, pool: asyncpg.Pool, llm: LLMClient, cache: CacheService):
        self.pool = pool
        self.llm = llm
        self.cache = cache

    async def retrieve_memories(
        self, end_user_id: str, character_id: str, limit: int = _MAX_MEMORIES
    ) -> list[dict]:
        """Retrieve recent memories for prompt injection. Cached per session."""
        if not end_user_id:
            return []

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
        """Format memory dicts into Chinese text for the system prompt."""
        result = []
        for m in memories:
            fmt = _MEMORY_FORMAT.get(m["type"], "主人说过{content}")
            result.append(fmt.format(content=m["content"]))
        return result

    async def extract_and_store(
        self,
        end_user_id: str,
        character_id: str,
        session_id: str,
        user_input: str,
        ai_response: str,
    ) -> None:
        """Extract memories from a conversation turn and store them.

        This should be called as a fire-and-forget async task (non-blocking).
        """
        if not end_user_id:
            return

        try:
            memories = await asyncio.wait_for(
                self._extract_memories(user_input, ai_response),
                timeout=_EXTRACTION_TIMEOUT,
            )
            if memories:
                await self._store_memories(
                    end_user_id, character_id, session_id, user_input, memories
                )
                # Invalidate cache so next retrieval picks up new memories
                await self.cache.delete(f"memories:{end_user_id}:{character_id}")
                logger.info(
                    "memory.extracted",
                    count=len(memories),
                    end_user_id=end_user_id,
                    character_id=character_id,
                )
        except asyncio.TimeoutError:
            logger.warning("memory.extraction_timeout")
        except Exception:
            logger.exception("memory.extraction_error")

    async def _extract_memories(
        self, user_input: str, ai_response: str
    ) -> list[dict]:
        """Use LLM to extract structured memories from conversation."""
        prompt = _EXTRACTION_PROMPT.format(
            user_input=user_input, ai_response=ai_response
        )
        raw = await self.llm.chat(
            system_prompt="你是记忆提取助手，只输出JSON数组，不要其他内容。",
            user_input=prompt,
        )

        # Parse JSON from LLM response
        raw = raw.strip()
        # Handle markdown code blocks
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("memory.invalid_json", raw=raw[:200])
            return []

        if not isinstance(data, list):
            return []

        # Validate and filter
        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            mem_type = item.get("type", "").upper()
            content = item.get("content", "").strip()
            if mem_type in MEMORY_TYPES and content and len(content) <= 50:
                valid.append({"type": mem_type, "content": content})

        return valid[:5]  # Max 5 memories per turn

    async def _store_memories(
        self,
        end_user_id: str,
        character_id: str,
        session_id: str,
        source: str,
        memories: list[dict],
    ) -> None:
        """Store memories in PostgreSQL with deduplication."""
        async with self.pool.acquire() as conn:
            for mem in memories:
                # Dedup: skip if similar content already exists
                existing = await conn.fetchval(
                    """SELECT 1 FROM conversation_memories
                       WHERE end_user_id = $1 AND character_id = $2
                         AND content = $3
                       LIMIT 1""",
                    end_user_id,
                    character_id,
                    mem["content"],
                )
                if existing:
                    continue

                await conn.execute(
                    """INSERT INTO conversation_memories
                       (id, end_user_id, character_id, type, content, source, session_id, created_at)
                       VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, now())""",
                    end_user_id,
                    character_id,
                    mem["type"],
                    mem["content"],
                    source[:500] if source else None,
                    session_id,
                )
