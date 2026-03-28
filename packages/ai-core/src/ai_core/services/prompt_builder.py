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
        self._templates = {
            "default": self.env.get_template("system_prompt.jinja2"),
            "idol": self.env.get_template("idol_prompt.jinja2"),
        }
        self.template = self._templates["default"]

    async def build(
        self,
        character_id: str,
        brand_id: str,
        end_user_id: str | None = None,
        user_input: str = "",
        emotion_state: str | None = None,
        user_mood: str | None = None,
        memories: list[dict] | None = None,
        relationship_stage: str | None = None,
        proactive_trigger: str | None = None,
        time_context: str | None = None,
        scene: str | None = None,
        touch_context: str | None = None,
        structured_output: bool = True,
    ) -> dict:
        """Build complete system prompt and voice config.

        Args:
            emotion_state: Character's current emotion for prompt injection.
            user_mood: Detected user mood for empathetic response.
            memories: Past-conversation memories for recall.
            relationship_stage: Dynamic stage (STRANGER→BESTFRIEND) for tone control.
            proactive_trigger: Optional opening line for the character to say.
            time_context: Time-of-day + absence duration context.
            structured_output: If True, prompt asks for JSON output. If False,
                plain text dialogue only (for device/TTS pipelines).

        Returns:
            {"system_prompt": str, "voice_id": str|None, "voice_speed": float, ...}
        """
        base = await self._get_character(character_id, brand_id)
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
        # Load drift for 3-layer merge: base + user_offsets + micro-drift
        personality_drift = None
        if custom and custom.get("personality_drift"):
            personality_drift = custom["personality_drift"]
            if isinstance(personality_drift, str):
                personality_drift = json.loads(personality_drift)

        from ai_core.services.personality_drift import merge_personality_with_drift
        personality = merge_personality_with_drift(base_personality, custom_offsets, personality_drift)
        personality_desc = _personality_to_text(personality)

        # RAG retrieval
        rag_context = ""
        if self.rag and user_input:
            results = await self.rag.search(character_id, user_input)
            if results:
                rag_context = "\n".join(results)

        # ── PersonaContext: archetype-driven adaptive language ──
        from ai_core.services.persona_context import PersonaContext
        archetype = base.get("archetype", "ANIMAL")
        pctx = PersonaContext.from_archetype(archetype)

        # Sanitize user-controlled fields to prevent prompt injection
        raw_nickname = custom.get("nickname") or base["name"] if custom else base["name"]
        raw_user_title = custom.get("user_title", pctx.user_title) if custom else pctx.user_title
        raw_interests = custom.get("interest_topics", []) if custom else base.get("topics", [])

        safe_nickname = _sanitize_user_field(str(raw_nickname), max_length=50)
        safe_user_title = _sanitize_user_field(str(raw_user_title), max_length=20)
        safe_interests = [_sanitize_user_field(str(t), max_length=50) for t in raw_interests][:20]

        # Format emotion for template
        current_emotion = bool(emotion_state and emotion_state != "calm")
        current_emotion_description = ""
        if current_emotion:
            from ai_core.services.emotion import EMOTION_DESCRIPTIONS
            current_emotion_description = EMOTION_DESCRIPTIONS.get(emotion_state, "")

        # Format user mood for template (using PersonaContext for adaptive language)
        user_mood_instruction = ""
        if user_mood and user_mood != "neutral":
            user_mood_instruction = pctx.mood_response(user_mood)

        # Format memories for template
        memory_context = []
        if memories:
            _ref = pctx.user_ref
            _MEMORY_FMT = {"TOPIC": "上次聊了{content}", "PREFERENCE": f"{_ref}{{content}}", "EVENT": f"{_ref}说过{{content}}"}
            for m in memories:
                fmt = _MEMORY_FMT.get(m.get("type", ""), f"{_ref}说过{{content}}")
                memory_context.append(fmt.format(content=m.get("content", "")))

        # Relationship stage description (use romance stages for idol archetype)
        relationship_description = ""
        if relationship_stage:
            archetype = base.get("archetype", "ANIMAL")
            if archetype == "HUMAN" and base.get("relationship", "") in (
                "暗恋对象", "青梅竹马", "深爱的人", "开朗的恋人", "表面冷漠的恋人",
                "温柔的恋人", "热血恋人", "若即若离的暧昧对象",
            ):
                from ai_core.services.idol_presets import ROMANCE_STAGE_PROMPTS
                relationship_description = ROMANCE_STAGE_PROMPTS.get(relationship_stage, "")
            else:
                from ai_core.services.relationship import STAGE_PROMPTS
                relationship_description = STAGE_PROMPTS.get(relationship_stage, "")

        # Scene prompt for idol mode
        # Scene prompt (archetype-adaptive via PersonaContext)
        scene_prompt = ""
        if scene:
            scene_prompt = pctx.scene_prompt(scene)
            if not scene_prompt:
                # Fallback to legacy static prompts
                from ai_core.services.idol_presets import SCENE_PROMPTS
                scene_prompt = SCENE_PROMPTS.get(scene, "")

        # Select template: idol for HUMAN romance archetype, default otherwise
        template = self._templates["default"]
        if base.get("archetype") == "HUMAN" and scene_prompt:
            template = self._templates["idol"]
        elif base.get("archetype") == "HUMAN" and base.get("relationship", "") in (
            "暗恋对象", "青梅竹马", "深爱的人", "开朗的恋人", "表面冷漠的恋人",
            "温柔的恋人", "热血恋人", "若即若离的暧昧对象",
        ):
            template = self._templates["idol"]

        # Render template with PersonaContext-driven variables
        system_prompt = template.render(
            name=safe_nickname,
            archetype=archetype,
            species=base.get("species") or "",
            backstory=base.get("backstory", ""),
            personality_description=personality_desc,
            current_emotion=current_emotion,
            current_emotion_description=current_emotion_description,
            user_mood_instruction=user_mood_instruction,
            touch_context=touch_context or "",
            time_context=time_context or "",
            catchphrases=base.get("catchphrases", []),
            suffix=base.get("suffix", ""),
            relationship=base.get("relationship", pctx.rel_default),
            relationship_description=relationship_description,
            user_title=safe_user_title,
            user_ref=pctx.user_ref,
            section_title=pctx.section_title,
            interests=safe_interests,
            memory_context=memory_context,
            proactive_trigger=proactive_trigger,
            scene_prompt=scene_prompt,
            response_length_instruction=RESPONSE_LENGTH_MAP.get(
                base.get("response_length", "SHORT"), RESPONSE_LENGTH_MAP["SHORT"]
            ),
            forbidden=base.get("forbidden", []),
            structured_output=structured_output,
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
            "personality": personality,
            "_species": base.get("species", ""),  # for Fish Audio voice resolution
        }

    async def _get_character(self, character_id: str, brand_id: str) -> dict | None:
        # Try cache first
        cache_key = f"char:{brand_id}:{character_id}"
        cached = await self.cache.get_json(cache_key)
        if cached is not None:
            return cached

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, archetype, species, age_setting, backstory, relationship,
                          personality, catchphrases, suffix, topics, forbidden,
                          response_length, voice_id, voice_speed, emotion_config
                   FROM characters WHERE id = $1 AND brand_id = $2""",
                character_id,
                brand_id,
            )
            if not row:
                return None
            # Convert UUID objects to strings for JSON serialization
            result = {k: (str(v) if hasattr(v, 'hex') else v) for k, v in dict(row).items()}
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
                """SELECT nickname, user_title, personality_offsets, personality_drift, interest_topics
                   FROM user_customizations
                   WHERE end_user_id = $1 AND character_id = $2 AND is_active = true""",
                end_user_id,
                character_id,
            )
            if not row:
                return None
            result = {k: (str(v) if hasattr(v, 'hex') else v) for k, v in dict(row).items()}
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
            result = {k: (str(v) if hasattr(v, 'hex') else v) for k, v in dict(row).items()}
            await self.cache.set_json(cache_key, result, ttl=self.CACHE_TTL)
            return result
