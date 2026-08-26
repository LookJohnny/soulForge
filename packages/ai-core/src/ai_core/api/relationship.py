"""Relationship API — five-axis bond state, app mode, and (Phase 4) event choices."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_core.dependencies import get_relationship_engine
from ai_core.models.schemas import RelationshipStateSchema
from ai_core.services.relationship import relationship_payload

router = APIRouter(prefix="/relationship", tags=["relationship"])


class AppModeRequest(BaseModel):
    app_mode: Literal["dating_sim", "companion"]


@router.get("/{end_user_id}/{character_id}", response_model=RelationshipStateSchema)
async def get_relationship(end_user_id: str, character_id: str):
    engine = await get_relationship_engine()
    state = await engine.get_state(end_user_id, character_id)
    return relationship_payload(state)


@router.patch("/{end_user_id}/{character_id}", response_model=RelationshipStateSchema)
async def set_app_mode(end_user_id: str, character_id: str, req: AppModeRequest):
    engine = await get_relationship_engine()
    try:
        state = await engine.set_app_mode(end_user_id, character_id, req.app_mode)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return relationship_payload(state)
