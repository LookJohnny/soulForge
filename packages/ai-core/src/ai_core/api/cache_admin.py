"""Internal cache administration endpoints."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ai_core.dependencies import get_cache

router = APIRouter(prefix="/internal/cache", tags=["internal-cache"])


class CharacterCacheInvalidateRequest(BaseModel):
    character_id: str = Field(min_length=1, max_length=64)


def _require_service_brand(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if not auth or auth.source != "service":
        raise HTTPException(status_code=403, detail="Service authentication required")
    if not auth.brand_id:
        raise HTTPException(status_code=400, detail="Missing brand context")
    return auth.brand_id


@router.post("/character/invalidate")
async def invalidate_character_cache(req: CharacterCacheInvalidateRequest, request: Request):
    """Invalidate the cached base character config used by PromptBuilder."""
    brand_id = _require_service_brand(request)
    cache = get_cache()
    await cache.delete(f"char:{brand_id}:{req.character_id}")
    return {"ok": True}
