"""ActionPlan DSL preview endpoint."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ai_core.services.action_plan import preview_action_plan

router = APIRouter(prefix="/actions", tags=["actions"])


class ActionPreviewRequest(BaseModel):
    action_plan: dict = Field(default_factory=dict)
    device_manifest: dict = Field(default_factory=dict)
    device_state: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


@router.post("/preview")
async def preview_actions(req: ActionPreviewRequest, request: Request):
    auth = getattr(request.state, "auth", None)
    if not auth or not auth.brand_id:  # F17 (audit): was the only unscoped endpoint
        raise HTTPException(status_code=403, detail="No brand context in auth token")
    return preview_action_plan(
        action_plan=req.action_plan,
        device_manifest=req.device_manifest,
        device_state=req.device_state,
        context=req.context,
    )
