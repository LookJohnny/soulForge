from fastapi import APIRouter, HTTPException, Request

from ai_core.dependencies import get_prompt_builder
from ai_core.middleware.rate_limit import limiter
from ai_core.models.schemas import PromptBuildRequest, PromptBuildResponse

router = APIRouter(prefix="/prompt", tags=["prompt"])


def _get_brand_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if not auth or not auth.brand_id:
        raise HTTPException(status_code=403, detail="No brand context in auth token")
    return auth.brand_id


@router.post("/build", response_model=PromptBuildResponse)
@limiter.limit("30/minute")
async def build_prompt(req: PromptBuildRequest, request: Request):
    brand_id = _get_brand_id(request)
    builder = await get_prompt_builder()
    try:
        result = await builder.build(
            character_id=req.character_id,
            brand_id=brand_id,
            end_user_id=req.end_user_id,
            user_input=req.user_input,
        )
        return PromptBuildResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
