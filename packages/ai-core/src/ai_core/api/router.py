from fastapi import APIRouter

from ai_core.api.cache_admin import router as cache_admin_router
from ai_core.api.chat import router as chat_router
from ai_core.api.health import router as health_router
from ai_core.api.idol import router as idol_router
from ai_core.api.pipeline import router as pipeline_router
from ai_core.api.prompt import router as prompt_router
from ai_core.api.rag import router as rag_router
from ai_core.api.soul_packs import router as soul_packs_router
from ai_core.api.tts import router as tts_router
from ai_core.api.voice_clone import router as voice_clone_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(cache_admin_router)
api_router.include_router(prompt_router)
api_router.include_router(rag_router)
api_router.include_router(pipeline_router)
api_router.include_router(tts_router)
api_router.include_router(chat_router)
api_router.include_router(soul_packs_router)
api_router.include_router(idol_router)
api_router.include_router(voice_clone_router)
