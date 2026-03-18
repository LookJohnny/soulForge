"""Singleton service instances, lazily initialized."""

import structlog

from ai_core.db import get_pool
from ai_core.services.asr_client import ASRClient
from ai_core.services.cache import CacheService
from ai_core.services.emotion import EmotionEngine
from ai_core.services.llm_client import LLMClient
from ai_core.services.memory import MemoryService
from ai_core.services.personality_drift import PersonalityDriftService
from ai_core.services.proactive_trigger import ProactiveTriggerService
from ai_core.services.prompt_builder import PromptBuilder
from ai_core.services.rag_engine import RagEngine
from ai_core.services.relationship import RelationshipEngine
from ai_core.services.tts_client import TTSClient

logger = structlog.get_logger()

_cache: CacheService | None = None
_prompt_builder: PromptBuilder | None = None
_rag_engine: RagEngine | None = None
_rag_failed: bool = False
_llm_client: LLMClient | None = None
_tts_client: TTSClient | None = None
_asr_client: ASRClient | None = None
_emotion_engine: EmotionEngine | None = None
_memory_service: MemoryService | None = None
_relationship_engine: RelationshipEngine | None = None
_personality_drift: PersonalityDriftService | None = None
_proactive_trigger: ProactiveTriggerService | None = None


def get_cache() -> CacheService:
    global _cache
    if _cache is None:
        _cache = CacheService()
    return _cache


async def get_rag_engine() -> RagEngine | None:
    global _rag_engine, _rag_failed
    if _rag_failed:
        return None
    if _rag_engine is None:
        try:
            _rag_engine = RagEngine()
            await _rag_engine.connect()
            logger.info("rag.connected")
        except Exception as e:
            logger.warning("rag.connect_failed", error=str(e))
            _rag_failed = True
            return None
    return _rag_engine


async def get_prompt_builder() -> PromptBuilder:
    global _prompt_builder
    if _prompt_builder is None:
        pool = await get_pool()
        rag = await get_rag_engine()
        cache = get_cache()
        _prompt_builder = PromptBuilder(pool, rag, cache)
    return _prompt_builder


async def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


async def get_tts_client() -> TTSClient:
    global _tts_client
    if _tts_client is None:
        _tts_client = TTSClient()
    return _tts_client


async def get_asr_client() -> ASRClient:
    global _asr_client
    if _asr_client is None:
        _asr_client = ASRClient()
    return _asr_client


def get_emotion_engine() -> EmotionEngine:
    global _emotion_engine
    if _emotion_engine is None:
        _emotion_engine = EmotionEngine(get_cache())
    return _emotion_engine


async def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        pool = await get_pool()
        llm = await get_llm_client()
        cache = get_cache()
        _memory_service = MemoryService(pool, llm, cache)
    return _memory_service


async def get_relationship_engine() -> RelationshipEngine:
    global _relationship_engine
    if _relationship_engine is None:
        pool = await get_pool()
        cache = get_cache()
        _relationship_engine = RelationshipEngine(pool, cache)
    return _relationship_engine


async def get_personality_drift() -> PersonalityDriftService:
    global _personality_drift
    if _personality_drift is None:
        pool = await get_pool()
        cache = get_cache()
        _personality_drift = PersonalityDriftService(pool, cache)
    return _personality_drift


def get_proactive_trigger() -> ProactiveTriggerService:
    global _proactive_trigger
    if _proactive_trigger is None:
        _proactive_trigger = ProactiveTriggerService(get_cache())
    return _proactive_trigger
