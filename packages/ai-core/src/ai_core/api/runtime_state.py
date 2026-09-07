"""Internal tenant-scoped character projection, identity and runtime state API."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from soulforge_harness.runtime.identity import RuntimeIdentity

from ai_core.db import get_pool
from ai_core.dependencies import get_cache
from ai_core.services.character_projection import CharacterProjectionService
from ai_core.services.runtime_state import RuntimeStateService

router = APIRouter(prefix="/runtime", tags=["runtime-state"])
Layer = Literal["profile", "episodic", "semantic", "relational", "compiled_behavior"]


def require_service_brand(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth is None or auth.source != "service":
        raise HTTPException(status_code=403, detail="Service authentication required")
    try:
        return str(UUID(auth.brand_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Valid brand context is required") from exc


class IdentityInput(BaseModel):
    user_id: UUID
    character_id: UUID
    agent_id: str = Field(min_length=1, max_length=64)
    body_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)

    def identity(self) -> RuntimeIdentity:
        return RuntimeIdentity(**self.model_dump(mode="json"))


class ProjectCharactersInput(BaseModel):
    characters: list[dict] = Field(min_length=1, max_length=256)
    user_id: UUID
    brand_name: str = Field(default="SoulForge", min_length=1, max_length=100)


class ResolveIdentityInput(BaseModel):
    user_id: UUID
    agent_id: str = Field(min_length=1, max_length=64)
    body_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)
    characters: list[dict] = Field(default_factory=list, max_length=256)
    brand_name: str = Field(default="SoulForge", min_length=1, max_length=100)


class RecallInput(BaseModel):
    identity: IdentityInput
    layer: Layer


class UpsertInput(RecallInput):
    key: str = Field(min_length=1, max_length=256)
    value: Any


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/characters/project")
async def project_characters(req: ProjectCharactersInput, request: Request):
    brand_id = require_service_brand(request)
    service = CharacterProjectionService(await get_pool(), get_cache())
    try:
        return await service.project(brand_id, str(req.user_id), req.characters, req.brand_name)
    except (ValueError, KeyError, PermissionError) as exc:
        raise _http_error(exc) from exc


@router.post("/resolve")
async def resolve_identity(req: ResolveIdentityInput, request: Request):
    brand_id = require_service_brand(request)
    service = CharacterProjectionService(await get_pool(), get_cache())
    try:
        if req.characters:
            await service.project(brand_id, str(req.user_id), req.characters, req.brand_name)
        return await service.resolve(
            brand_id, str(req.user_id), req.agent_id, req.body_id, req.session_id
        )
    except (ValueError, KeyError, PermissionError) as exc:
        raise _http_error(exc) from exc


@router.post("/memory/recall")
async def recall_state(req: RecallInput, request: Request):
    brand_id = require_service_brand(request)
    service = RuntimeStateService(await get_pool())
    try:
        return await service.recall(brand_id, req.identity.identity(), req.layer)
    except (ValueError, KeyError, PermissionError) as exc:
        raise _http_error(exc) from exc


@router.post("/memory/upsert")
async def upsert_state(req: UpsertInput, request: Request):
    brand_id = require_service_brand(request)
    service = RuntimeStateService(await get_pool())
    try:
        return await service.upsert(
            brand_id, req.identity.identity(), req.layer, req.key, req.value
        )
    except (ValueError, KeyError, PermissionError) as exc:
        raise _http_error(exc) from exc
