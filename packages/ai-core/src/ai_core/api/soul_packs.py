"""Soul Pack API — `.soul` v2 export / peek / import (legacy `.soulpack` v1 still importable)."""

import base64
import hashlib
import json
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ai_core.db import get_pool
from ai_core.services.soul_pack_builder import SoulPackBuilder

router = APIRouter(prefix="/soul-packs", tags=["soul-packs"])
logger = structlog.get_logger()
builder = SoulPackBuilder()


def _get_brand_id(request: Request) -> str:
    """Extract brand_id from auth context. Never trust client-provided brand_id."""
    auth = getattr(request.state, "auth", None)
    if not auth or not auth.brand_id:
        raise HTTPException(status_code=403, detail="No brand context in auth token")
    return auth.brand_id


class ExportRequest(BaseModel):
    character_id: str
    # optional body/expression/engine persona supplied by the caller (studio, /live)
    embodiment: dict | None = None
    model_b64: str | None = None
    model_ext: str = "vrm"
    expression: dict | None = None
    events: dict | None = None
    studio: dict | None = None
    author: str | None = None
    license: str | None = None
    passphrase: str | None = None
    soul_id: str | None = None


class ImportRequest(BaseModel):
    soul_b64: str | None = None
    soulpack_b64: str | None = None  # legacy field name
    passphrase: str | None = None

    @property
    def blob_b64(self) -> str:
        return self.soul_b64 or self.soulpack_b64 or ""


class PeekRequest(BaseModel):
    soul_b64: str


def _jsonable(row) -> dict:
    out = dict(row)
    for k, v in out.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out


async def _load_character(pool, character_id: str, brand_id: str) -> tuple[dict, dict | None]:
    row = await pool.fetchrow(
        "SELECT * FROM characters WHERE id = $1 AND brand_id = $2", character_id, brand_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")
    voice_profile = None
    if row.get("voice_id"):
        vrow = await pool.fetchrow("SELECT * FROM voice_profiles WHERE id = $1", row["voice_id"])
        if vrow:
            voice_profile = _jsonable(vrow)
    return _jsonable(row), voice_profile


async def _build_from_request(req: ExportRequest, request: Request) -> tuple[bytes, dict]:
    brand_id = _get_brand_id(request)
    pool = await get_pool()
    character_data, voice_profile = await _load_character(pool, req.character_id, brand_id)
    model_bytes = None
    if req.model_b64:
        try:
            model_bytes = base64.b64decode(req.model_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail="Invalid model_b64") from e
    data = builder.build(
        character_data=character_data,
        voice_profile=voice_profile,
        embodiment=req.embodiment,
        model_bytes=model_bytes,
        model_ext=req.model_ext,
        expression=req.expression,
        events=req.events,
        studio=req.studio,
        author=req.author,
        license_text=req.license,
        soul_id=req.soul_id,
        passphrase=req.passphrase,
    )
    await _record(pool, brand_id, req.character_id, data, "export", character_data.get("name", ""))
    return data, character_data


async def _record(pool, brand_id, character_id, blob: bytes, source: str, name: str, version="2.0"):
    try:
        await pool.execute(
            """INSERT INTO soul_packs
                   (id, brand_id, character_id, version, checksum, file_url, file_size,
                    metadata, created_at)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, '', $5, $6, now())""",
            brand_id,
            character_id,
            version,
            hashlib.sha256(blob).hexdigest(),
            len(blob),
            json.dumps({"source": source, "character_name": name}),
        )
    except Exception:
        logger.warning("soul.record_failed", source=source, exc_info=True)


@router.post("/export")
async def export_soul(req: ExportRequest, request: Request):
    """Export a character as a `.soul` (base64 in JSON)."""
    data, character = await _build_from_request(req, request)
    return {
        "soul_b64": base64.b64encode(data).decode(),
        "size": len(data),
        "character_name": character.get("name", ""),
        "encrypted": bool(req.passphrase),
    }


@router.post("/export.bin")
async def export_soul_binary(req: ExportRequest, request: Request):
    """Export as a raw `.soul` download."""
    data, character = await _build_from_request(req, request)
    name = character.get("name", "character")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}.soul"'},
    )


@router.post("/peek")
async def peek_soul(req: PeekRequest):
    """Read only the container header: version, soul_id, whether a passphrase is required."""
    try:
        return SoulPackBuilder.peek(base64.b64decode(req.soul_b64))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a soul file: {e}") from e


@router.post("/import")
async def import_soul(req: ImportRequest, request: Request):
    """Import a `.soul` (v2, optional passphrase) or legacy `.soulpack` (v1, brand key)."""
    brand_id = _get_brand_id(request)
    try:
        blob = base64.b64decode(req.blob_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid base64 data") from e

    try:
        data = builder.read(blob, brand_id=brand_id, passphrase=req.passphrase)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read soul file: {e}") from e

    character = data.get("character", {})
    manifest = data.get("manifest", {})
    if not character.get("name"):
        raise HTTPException(status_code=400, detail="Soul file contains no character")

    pool = await get_pool()
    new_id = str(uuid.uuid4())
    personality = character.get("personality", {})
    try:
        await pool.execute(
            """INSERT INTO characters
                   (id, brand_id, name, archetype, species, backstory, relationship,
                    personality, catchphrases, suffix, topics, forbidden,
                    response_length, voice_speed, status, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                       'DRAFT', now(), now())""",
            new_id,
            brand_id,
            character.get("name"),
            character.get("archetype", "ANIMAL"),
            character.get("species"),
            character.get("backstory"),
            character.get("relationship"),
            personality if isinstance(personality, str) else json.dumps(personality),
            list(character.get("catchphrases") or []),
            character.get("suffix"),
            list(character.get("topics") or []),
            list(character.get("forbidden") or []),
            character.get("response_length", "SHORT"),
            float(character.get("voice_speed") or 1.0),
        )
    except Exception as e:
        logger.exception("soul.import_character_failed")
        raise HTTPException(status_code=500, detail="Failed to import character") from e

    await _record(
        pool, brand_id, new_id, blob, "import", character["name"], manifest.get("version", "1.0")
    )
    logger.info("soul.imported", character_id=new_id, brand_id=brand_id, name=character["name"])

    return {
        "character_id": new_id,
        "manifest": manifest,
        "character_name": character["name"],
        # the caller (studio) persists these on its own side — DB has no columns for them
        "embodiment": data.get("embodiment"),
        "expression": data.get("expression"),
        "studio": data.get("studio"),
        "voice_profile": data.get("voice_profile"),
        "has_model": "model_bytes" in data,
        "has_rag": bool(data.get("rag_documents")),
        "has_prompt_template": bool(data.get("prompt_template")),
    }
