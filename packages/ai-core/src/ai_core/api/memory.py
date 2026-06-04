"""Memory management API for five-layer companion memory."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ai_core.dependencies import get_memory_service

router = APIRouter(prefix="/memory", tags=["memory"])


MemoryLayerLiteral = Literal["PROFILE", "EPISODIC", "SEMANTIC", "RELATIONAL"]
SensitivityLiteral = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


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


class CompileMemoryRequest(BaseModel):
    user_id: str
    character_id: str | None = None
    trigger: str = "manual"


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


@router.post("/compile")
async def compile_memory(req: CompileMemoryRequest):
    svc = await get_memory_service()
    try:
        return await svc.compile_memory(req.user_id, req.character_id)
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
