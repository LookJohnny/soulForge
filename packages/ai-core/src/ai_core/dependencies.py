"""Singleton service instances, lazily initialized."""

import structlog

from ai_core.db import get_pool
from ai_core.services.asr_client import ASRClient
from ai_core.services.cache import CacheService
from ai_core.services.llm_client import LLMClient
from ai_core.services.prompt_builder import PromptBuilder
from ai_core.services.rag_engine import RagEngine
from ai_core.services.tts_client import TTSClient

logger = structlog.get_logger()

_prompt_builder: PromptBuilder | None = None
_rag_engine: RagEngine | None = None
_rag_failed: bool = False
_llm_client: LLMClient | None = None
_tts_client: TTSClient | None = None
_asr_client: ASRClient | None = None


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
        rag = await get_rag_engine()  # None if Milvus unavailable
        cache = CacheService()
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
