from fastapi import APIRouter

from ai_core.api.chat import router as chat_router
from ai_core.api.health import router as health_router
from ai_core.api.pipeline import router as pipeline_router
from ai_core.api.prompt import router as prompt_router
from ai_core.api.rag import router as rag_router
from ai_core.api.soul_packs import router as soul_packs_router
from ai_core.api.tts import router as tts_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(prompt_router)
api_router.include_router(rag_router)
api_router.include_router(pipeline_router)
api_router.include_router(tts_router)
api_router.include_router(chat_router)
api_router.include_router(soul_packs_router)
