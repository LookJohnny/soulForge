"""Prompt Builder - The soul injection engine.

Merges designer character config + user customization + RAG context
into a complete System Prompt for the LLM.
"""

import json
import re
from pathlib import Path

import asyncpg
from jinja2 import Environment, FileSystemLoader

from ai_core.services.cache import CacheService

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

# Pattern to strip Jinja2 syntax and control characters from user fields
_JINJA_PATTERN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_user_field(value: str, max_length: int = 200) -> str:
    """Sanitize user-controlled fields to prevent prompt injection.

    - Strip Jinja2 template syntax ({{ }}, {% %}, {# #})
    - Remove control characters
    - Collapse newlines to single space (prevents section injection)
    - Truncate to max_length
    """
    value = _JINJA_PATTERN.sub("", value)
    value = _CONTROL_CHARS.sub("", value)
    value = re.sub(r"\n+", " ", value)
    return value[:max_length].strip()


# Personality trait descriptions (Chinese)
TRAIT_DESCRIPTIONS = {
    "extrovert": {
        "high": "活泼外向，喜欢和人聊天",
        "mid": "不太主动但也不排斥交流",
        "low": "安静内敛，说话温声细语",
    },
    "humor": {
        "high": "幽默风趣，经常讲冷笑话",
        "mid": "偶尔幽默",
        "low": "认真严肃，很少开玩笑",
    },
    "warmth": {
        "high": "温暖贴心，会关心你的感受",
        "mid": "友善但不过分热情",
        "low": "酷酷的，不太表达关心",
    },
    "curiosity": {
        "high": "充满好奇心，喜欢问东问西",
        "mid": "对新事物有一些兴趣",
        "low": "淡定从容，见怪不怪",
    },
    "energy": {
        "high": "元气满满，说话充满活力",
        "mid": "精力适中",
        "low": "慢悠悠的，节奏很慢",
    },
}

RESPONSE_LENGTH_MAP = {
    "SHORT": "回复控制在1-2句话以内，简洁有趣。",
    "MEDIUM": "回复控制在2-3句话以内。",
    "LONG": "可以稍微展开回复，但不超过4-5句话。",
}


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def _merge_personality(base: dict, offsets: dict | None) -> dict:
    """Merge base personality with user offsets, clamp to 0-100."""
    if not offsets:
        return dict(base)
    result = dict(base)
    for key, offset in offsets.items():
        if key in result:
            result[key] = _clamp(result[key] + offset)
    return result


def _personality_to_text(traits: dict) -> str:
    """Convert numeric personality traits to descriptive text."""
    descriptions = []
    for trait_key, levels in TRAIT_DESCRIPTIONS.items():
        value = traits.get(trait_key, 50)
        if value >= 70:
            descriptions.append(levels["high"])
        elif value <= 30:
            descriptions.append(levels["low"])
    return "；".join(descriptions) if descriptions else "性格平和，随和友善"


class PromptBuilder:
    # Cache TTL in seconds (1 hour)
    CACHE_TTL = 3600

    def __init__(self, pool: asyncpg.Pool, rag_engine=None, cache: CacheService | None = None):
        self.pool = pool
        self.rag = rag_engine
        self.cache = cache or CacheService()
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        self.template = self.env.get_template("system_prompt.jinja2")

    async def build(
        self,
        character_id: str,
        end_user_id: str | None = None,
        user_input: str = "",
    ) -> dict:
        """Build complete system prompt and voice config.

        Returns:
            {"system_prompt": str, "voice_id": str|None, "voice_speed": float}
        """
        base = await self._get_character(character_id)
        if not base:
            raise ValueError(f"Character {character_id} not found")

        custom = None
        if end_user_id:
            custom = await self._get_customization(end_user_id, character_id)

        # Merge personality (asyncpg may return JSONB as str)
        base_personality = base["personality"]
        if isinstance(base_personality, str):
            base_personality = json.loads(base_personality)
        custom_offsets = None
        if custom and custom.get("personality_offsets"):
            custom_offsets = custom["personality_offsets"]
            if isinstance(custom_offsets, str):
                custom_offsets = json.loads(custom_offsets)
        personality = _merge_personality(base_personality, custom_offsets)
        personality_desc = _personality_to_text(personality)

        # RAG retrieval
        rag_context = ""
        if self.rag and user_input:
            results = await self.rag.search(character_id, user_input)
            if results:
                rag_context = "\n".join(results)

        # Sanitize user-controlled fields to prevent prompt injection
        raw_nickname = custom.get("nickname") or base["name"] if custom else base["name"]
        raw_user_title = custom.get("user_title", "主人") if custom else "主人"
        raw_interests = custom.get("interest_topics", []) if custom else base.get("topics", [])

        safe_nickname = _sanitize_user_field(str(raw_nickname), max_length=50)
        safe_user_title = _sanitize_user_field(str(raw_user_title), max_length=20)
        safe_interests = [_sanitize_user_field(str(t), max_length=50) for t in raw_interests][:20]

        # Render template
        system_prompt = self.template.render(
            name=safe_nickname,
            species=base["species"],
            backstory=base.get("backstory", ""),
            personality_description=personality_desc,
            catchphrases=base.get("catchphrases", []),
            suffix=base.get("suffix", ""),
            relationship=base.get("relationship", "朋友"),
            user_title=safe_user_title,
            interests=safe_interests,
            response_length_instruction=RESPONSE_LENGTH_MAP.get(
                base.get("response_length", "SHORT"), RESPONSE_LENGTH_MAP["SHORT"]
            ),
            forbidden=base.get("forbidden", []),
            rag_context=rag_context,
        )

        # Get voice info — explicit assignment or auto-match
        voice_id = None
        voice_speed = base.get("voice_speed", 1.0)
        pitch_rate = 0
        speech_rate = 0
        ssml_pitch = 1.0
        ssml_rate = 1.0
        ssml_effect = ""

        if base.get("voice_id"):
            # Designer explicitly assigned a voice
            voice = await self._get_voice(base["voice_id"])
            if voice:
                voice_id = voice.get("dashscope_voice_id")
        else:
            # No voice assigned — auto-match based on character traits
            from ai_core.services.voice_matcher import match_voice
            matched = match_voice(
                species=base.get("species", ""),
                age_setting=base.get("age_setting"),
                personality=personality,
                relationship=base.get("relationship"),
            )
            voice_id = matched["voice_id"]
            voice_speed = matched["speed"]
            pitch_rate = matched.get("pitch_rate", 0)
            speech_rate = matched.get("speech_rate", 0)
            ssml_pitch = matched.get("ssml_pitch", 1.0)
            ssml_rate = matched.get("ssml_rate", 1.0)
            ssml_effect = matched.get("ssml_effect", "")

        return {
            "system_prompt": system_prompt,
            "voice_id": voice_id,
            "voice_speed": voice_speed,
            "pitch_rate": pitch_rate,
            "speech_rate": speech_rate,
            "ssml_pitch": ssml_pitch,
            "ssml_rate": ssml_rate,
            "ssml_effect": ssml_effect,
        }

    async def _get_character(self, character_id: str) -> dict | None:
        # Try cache first
        cache_key = f"char:{character_id}"
        cached = await self.cache.get_json(cache_key)
        if cached is not None:
            return cached

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, species, age_setting, backstory, relationship,
                          personality, catchphrases, suffix, topics, forbidden,
                          response_length, voice_id, voice_speed, emotion_config
                   FROM characters WHERE id = $1""",
                character_id,
            )
            if not row:
                return None
            result = dict(row)
            await self.cache.set_json(cache_key, result, ttl=self.CACHE_TTL)
            return result

    async def _get_customization(self, end_user_id: str, character_id: str) -> dict | None:
        # Try cache first
        cache_key = f"custom:{end_user_id}:{character_id}"
        cached = await self.cache.get_json(cache_key)
        if cached is not None:
            return cached

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT nickname, user_title, personality_offsets, interest_topics
                   FROM user_customizations
                   WHERE end_user_id = $1 AND character_id = $2 AND is_active = true""",
                end_user_id,
                character_id,
            )
            if not row:
                return None
            result = dict(row)
            await self.cache.set_json(cache_key, result, ttl=self.CACHE_TTL)
            return result

    async def _get_voice(self, voice_id: str) -> dict | None:
        # Try cache first
        cache_key = f"voice:{voice_id}"
        cached = await self.cache.get_json(cache_key)
        if cached is not None:
            return cached

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT dashscope_voice_id, reference_audio FROM voice_profiles WHERE id = $1",
                voice_id,
            )
            if not row:
                return None
            result = dict(row)
            await self.cache.set_json(cache_key, result, ttl=self.CACHE_TTL)
            return result
