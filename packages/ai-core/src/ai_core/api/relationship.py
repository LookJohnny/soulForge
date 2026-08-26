"""Relationship API — five-axis bond state, app mode, and (Phase 4) event choices."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_core.dependencies import get_event_engine, get_relationship_engine
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


class EventChoiceRequest(BaseModel):
    choice_index: int


@router.post("/{end_user_id}/{character_id}/events/{event_id}/choice")
async def choose_event(end_user_id: str, character_id: str, event_id: str, req: EventChoiceRequest):
    """Resolve a pending scene choice → companion line + updated relationship."""
    engine = await get_event_engine()
    try:
        return await engine.choose(end_user_id, character_id, event_id, req.choice_index)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown event {event_id}") from None
    except IndexError:
        raise HTTPException(status_code=422, detail="choice_index out of range") from None


@router.get("/{end_user_id}/{character_id}/events/near")
async def near_events(end_user_id: str, character_id: str):
    """Events that are more than half-way to triggering (UI hints)."""
    rel = await get_relationship_engine()
    engine = await get_event_engine()
    state = await rel.get_state(end_user_id, character_id)
    return {"near": await engine.near(end_user_id, character_id, state)}
