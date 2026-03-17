"""Singleton service instances, lazily initialized."""

from ai_core.db import get_pool
from ai_core.services.asr_client import ASRClient
from ai_core.services.llm_client import LLMClient
from ai_core.services.prompt_builder import PromptBuilder
from ai_core.services.rag_engine import RagEngine
from ai_core.services.tts_client import TTSClient

_prompt_builder: PromptBuilder | None = None
_rag_engine: RagEngine | None = None
_llm_client: LLMClient | None = None
_tts_client: TTSClient | None = None
_asr_client: ASRClient | None = None


async def get_rag_engine() -> RagEngine:
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = RagEngine()
        await _rag_engine.connect()
    return _rag_engine


async def get_prompt_builder() -> PromptBuilder:
    global _prompt_builder
    if _prompt_builder is None:
        pool = await get_pool()
        rag = await get_rag_engine()
        _prompt_builder = PromptBuilder(pool, rag)
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
