"""Memory management API for five-layer companion memory."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ai_core.db import get_pool
from ai_core.dependencies import get_memory_service
from ai_core.services.companion_reaction import CompanionReactionPlanner

router = APIRouter(prefix="/memory", tags=["memory"])


MemoryLayerLiteral = Literal["PROFILE", "EPISODIC", "SEMANTIC", "RELATIONAL"]
SensitivityLiteral = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


async def _load_reaction_persona(character_id: str | None) -> dict:
    if not character_id:
        return {}
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT archetype::TEXT, species, personality, response_length::TEXT,
                          language_mode::TEXT, vocalization_palette
                   FROM characters
                   WHERE id = $1
                   LIMIT 1""",
                character_id,
            )
    except Exception:
        return {}
    if not row:
        return {}
    return {
        "archetype": row["archetype"],
        "species": row["species"],
        "personality": row["personality"] or {},
        "response_length": row["response_length"],
        "language_mode": row["language_mode"],
        "vocalization_palette": row["vocalization_palette"] or [],
    }


class CreateMemoryRequest(BaseModel):
    user_id: str
    character_id: str | None = None
    memory_type: MemoryLayerLiteral = "EPISODIC"
    content: str = Field(min_length=1, max_length=2000)
    raw_source: dict = Field(default_factory=dict)
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0)
    sensitivity_level: SensitivityLiteral | None = None
    permission_level: str = "AUTO"
    evidence_count: int = Field(default=0, ge=0)


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, max_length=2000)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    implicit_only: bool | None = None
    can_surface_directly: bool | None = None
    update_reason: str = "api_update"


class RetrieveMemoryRequest(BaseModel):
    user_id: str
    character_id: str | None = None
    query: str = Field(default="", max_length=2000)
    context: dict = Field(default_factory=dict)
    token_budget: int = Field(default=1000, ge=200, le=4000)
    limit: int = Field(default=10, ge=1, le=50)
    response_id: str | None = None


class RawEventRequest(BaseModel):
    user_id: str
    character_id: str | None = None
    device_id: str | None = None
    session_id: str | None = None
    event_type: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="api", max_length=50)
    payload: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    importance_score: int | None = Field(default=None, ge=1, le=10)
    sensitivity_level: SensitivityLiteral | None = None
    observed_at: datetime | None = None


class CompileMemoryRequest(BaseModel):
    user_id: str
    character_id: str | None = None
    trigger: str = "manual"


class ReflectMemoryRequest(BaseModel):
    user_id: str
    character_id: str | None = None
    trigger: str = "manual"
    dry_run: bool = False
    limit: int = Field(default=100, ge=10, le=500)
    min_importance_sum: int = Field(default=12, ge=1, le=500)


class DecayMemoryRequest(BaseModel):
    user_id: str
    dry_run: bool = True


class FeedbackMemoryRequest(BaseModel):
    memory_id: str
    feedback: Literal["wrong", "sensitive", "use_less", "good"]
    comment: str | None = Field(default=None, max_length=1000)


class BehaviorWithMemoryRequest(BaseModel):
    user_id: str
    character_id: str | None = None
    context: dict = Field(default_factory=dict)


class CompanionReactionRequest(BaseModel):
    user_id: str | None = None
    character_id: str | None = None
    event_type: str = Field(min_length=1, max_length=80)
    event: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=30)


@router.get("/graph")
async def memory_graph(
    end_user_id: str = Query(...),
    character_id: str = Query(...),
    threshold: float = Query(0.6, ge=0.0, le=1.0),
    limit: int = Query(200, ge=1, le=500),
):
    """Memory graph: nodes = memories, edges = semantic similarity ≥ threshold."""
    svc = await get_memory_service()
    return await svc.memory_graph(end_user_id, character_id, threshold=threshold, limit=limit)


@router.post("/embed-backfill")
async def embed_backfill(
    end_user_id: str | None = Query(None), limit: int = Query(500, ge=1, le=5000)
):
    """Embed memory rows that have no vector yet (after enabling the model / migration 007)."""
    svc = await get_memory_service()
    return await svc.embed_backfill(end_user_id=end_user_id, limit=limit)


@router.post("")
async def create_memory(req: CreateMemoryRequest):
    svc = await get_memory_service()
    try:
        result = await svc.create_memory(req.model_dump())
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return result


@router.patch("/{memory_id}")
async def update_memory(memory_id: str, req: UpdateMemoryRequest):
    svc = await get_memory_service()
    try:
        return await svc.update_memory(
            memory_id,
            req.model_dump(exclude_none=True),
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail="memory not found") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/retrieve")
async def retrieve_memory(req: RetrieveMemoryRequest):
    svc = await get_memory_service()
    return await svc.retrieve_memory_pack(
        end_user_id=req.user_id,
        character_id=req.character_id,
        query=req.query,
        context=req.context,
        limit=req.limit,
        response_id=req.response_id,
    )


@router.post("/events")
async def record_raw_event(req: RawEventRequest):
    svc = await get_memory_service()
    try:
        return await svc.record_raw_event(req.model_dump(exclude_none=True))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/events")
async def list_raw_events(
    user_id: str,
    character_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    svc = await get_memory_service()
    try:
        return await svc.list_raw_events(user_id, character_id, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/compile")
async def compile_memory(req: CompileMemoryRequest):
    svc = await get_memory_service()
    try:
        return await svc.compile_memory(req.user_id, req.character_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/reflect")
async def reflect_memory(req: ReflectMemoryRequest):
    svc = await get_memory_service()
    try:
        return await svc.reflect_memory(
            user_id=req.user_id,
            character_id=req.character_id,
            trigger=req.trigger,
            dry_run=req.dry_run,
            limit=req.limit,
            min_importance_sum=req.min_importance_sum,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/reflections")
async def list_reflections(
    user_id: str,
    character_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    svc = await get_memory_service()
    try:
        return await svc.list_reflections(user_id, character_id, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/decay")
async def decay_memory(req: DecayMemoryRequest):
    svc = await get_memory_service()
    try:
        return await svc.decay_memory(req.user_id, dry_run=req.dry_run)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    cascade_compiled_rules: bool = Query(default=True),
):
    svc = await get_memory_service()
    try:
        return await svc.delete_memory(memory_id, cascade_compiled_rules=cascade_compiled_rules)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="memory not found") from e


@router.get("/usage/{usage_id}")
async def explain_memory_usage(usage_id: str):
    svc = await get_memory_service()
    try:
        return await svc.explain_memory_usage(usage_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="usage log not found") from e


@router.post("/feedback")
async def user_feedback_on_memory(req: FeedbackMemoryRequest):
    svc = await get_memory_service()
    try:
        return await svc.feedback_on_memory(req.memory_id, req.feedback, req.comment)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="memory not found") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/reaction")
async def decide_companion_reaction(req: CompanionReactionRequest):
    context = dict(req.context)
    if req.character_id and "persona" not in context and "character" not in context:
        persona = await _load_reaction_persona(req.character_id)
        if persona:
            context["persona"] = persona

    memory_pack: dict = {}
    if req.user_id:
        svc = await get_memory_service()
        try:
            memory_pack = await svc.retrieve_memory_pack(
                end_user_id=req.user_id,
                character_id=req.character_id,
                query=f"{req.event_type} {req.event}",
                context=context,
                limit=req.limit,
            )
        except RuntimeError:
            memory_pack = {}

    planner = CompanionReactionPlanner()
    return planner.decide(
        event_type=req.event_type,
        event=req.event,
        memory_pack=memory_pack,
        context=context,
    ).to_dict()


@router.post("/behavior")
async def generate_robot_behavior_with_memory(req: BehaviorWithMemoryRequest):
    svc = await get_memory_service()
    pack = await svc.retrieve_memory_pack(
        end_user_id=req.user_id,
        character_id=req.character_id,
        query="",
        context=req.context,
        limit=10,
    )
    return {
        "robot_behavior_hints": pack.get("robot_behavior_hints", {}),
        "policy_summary": {
            "direct_surface_count": len(pack.get("direct", [])),
            "implicit_count": len(pack.get("implicit", [])),
            "compiled_rule_count": len(pack.get("compiled_rules", [])),
            "blocked_count": pack.get("blocked_count", 0),
        },
    }
