"""Relationship API — five-axis bond state, app mode, and (Phase 4) event choices."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_core.dependencies import get_event_engine, get_memory_service, get_relationship_engine
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


COMPANION_SAVE_VERSION = 1


class CompanionImportRequest(BaseModel):
    version: int = COMPANION_SAVE_VERSION
    mode: Literal["merge", "replace"] = "merge"
    relationship: dict | None = None
    events: list[dict] | None = None
    memories: list[dict] | None = None


@router.get("/{end_user_id}/{character_id}/export")
async def export_companion_state(end_user_id: str, character_id: str):
    """Everything that makes this bond *this* bond: axes, events, memories."""
    rel = await get_relationship_engine()
    events = await get_event_engine()
    mem = await get_memory_service()
    state = await rel.get_state(end_user_id, character_id)
    return {
        "version": COMPANION_SAVE_VERSION,
        "exported_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "end_user_id": end_user_id,
        "character_id": character_id,
        "relationship": {k: v for k, v in state.items() if not k.startswith("_")},
        "events": await events.history(end_user_id, character_id),
        "memories": await mem.export_memories(end_user_id, character_id),
    }


@router.post("/{end_user_id}/{character_id}/import")
async def import_companion_state(end_user_id: str, character_id: str, req: CompanionImportRequest):
    """Restore a save file. ``replace`` wipes the current bond first; ``merge`` keeps
    the higher of each axis and unions events/memories."""
    from ai_core.services.relationship import AXES, apply_deltas, compute_stage, default_state

    rel = await get_relationship_engine()
    mem = await get_memory_service()
    result: dict = {"mode": req.mode}
    if req.relationship:
        current = (
            default_state()
            if req.mode == "replace"
            else await rel.get_state(end_user_id, character_id)
        )
        incoming = {**default_state(), **req.relationship}
        merged = dict(current)
        for axis in AXES:
            merged[axis] = (
                max(current.get(axis, 0), incoming.get(axis, 0))
                if req.mode == "merge"
                else incoming.get(axis, 0)
            )
        for key in (
            "streak_days",
            "total_interactions",
            "app_mode",
            "saved_stage",
            "first_interaction_at",
            "last_interaction_at",
            "last_interaction_date",
        ):
            if incoming.get(key) is not None and (req.mode == "replace" or not current.get(key)):
                merged[key] = incoming[key]
        merged["completed_events"] = (
            sorted(
                set(current.get("completed_events") or [])
                | set(incoming.get("completed_events") or [])
            )
            if req.mode == "merge"
            else list(incoming.get("completed_events") or [])
        )
        merged = apply_deltas(merged, {})
        merged["stage"] = compute_stage(merged)
        await rel._save(end_user_id, character_id, merged)
        result["relationship"] = relationship_payload(merged)
    if req.events:
        rel_state = await rel.get_state(end_user_id, character_id)
        completed = set(rel_state.get("completed_events") or [])
        for ev in req.events:
            if ev.get("event_id") and ev["event_id"] not in completed:
                await rel.record_event(end_user_id, character_id, ev["event_id"], {})
                completed.add(ev["event_id"])
        result["events"] = len(completed)
    if req.memories:
        result["memories"] = await mem.import_memories(
            end_user_id, character_id, req.memories, replace=req.mode == "replace"
        )
    return result
