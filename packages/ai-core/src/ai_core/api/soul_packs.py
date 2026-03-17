"""Soul Pack API endpoints — export, import, deploy."""

import base64

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ai_core.db import get_pool
from ai_core.services.soul_pack_builder import SoulPackBuilder

router = APIRouter(prefix="/soul-packs", tags=["soul-packs"])
logger = structlog.get_logger()
builder = SoulPackBuilder()


class ExportRequest(BaseModel):
    character_id: str
    brand_id: str


class ImportRequest(BaseModel):
    brand_id: str
    soulpack_b64: str  # base64-encoded .soulpack bytes


@router.post("/export")
async def export_soul_pack(req: ExportRequest):
    """Export a character as an encrypted .soulpack file."""
    pool = await get_pool()

    # Fetch character from DB
    row = await pool.fetchrow(
        "SELECT * FROM characters WHERE id = $1 AND brand_id = $2",
        req.character_id,
        req.brand_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")

    character_data = dict(row)
    # Convert non-serializable types
    for key in list(character_data.keys()):
        val = character_data[key]
        if hasattr(val, "isoformat"):
            character_data[key] = val.isoformat()

    # Fetch voice profile if linked
    voice_profile = None
    if row["voice_id"]:
        voice_row = await pool.fetchrow(
            "SELECT * FROM voice_profiles WHERE id = $1", row["voice_id"]
        )
        if voice_row:
            voice_profile = dict(voice_row)
            for key in list(voice_profile.keys()):
                val = voice_profile[key]
                if hasattr(val, "isoformat"):
                    voice_profile[key] = val.isoformat()

    # Build .soulpack
    soulpack_bytes = builder.build(
        brand_id=req.brand_id,
        character_data=character_data,
        voice_profile=voice_profile,
    )

    return {
        "soulpack_b64": base64.b64encode(soulpack_bytes).decode(),
        "size": len(soulpack_bytes),
        "character_name": character_data.get("name", ""),
    }


@router.post("/export.bin")
async def export_soul_pack_binary(req: ExportRequest):
    """Export as raw binary download."""
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT * FROM characters WHERE id = $1 AND brand_id = $2",
        req.character_id,
        req.brand_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")

    character_data = dict(row)
    for key in list(character_data.keys()):
        val = character_data[key]
        if hasattr(val, "isoformat"):
            character_data[key] = val.isoformat()

    voice_profile = None
    if row["voice_id"]:
        voice_row = await pool.fetchrow(
            "SELECT * FROM voice_profiles WHERE id = $1", row["voice_id"]
        )
        if voice_row:
            voice_profile = dict(voice_row)
            for key in list(voice_profile.keys()):
                val = voice_profile[key]
                if hasattr(val, "isoformat"):
                    voice_profile[key] = val.isoformat()

    soulpack_bytes = builder.build(
        brand_id=req.brand_id,
        character_data=character_data,
        voice_profile=voice_profile,
    )

    name = character_data.get("name", "character")
    return Response(
        content=soulpack_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}.soulpack"'},
    )


@router.post("/import")
async def import_soul_pack(req: ImportRequest):
    """Import a .soulpack file and restore the character."""
    try:
        soulpack_bytes = base64.b64decode(req.soulpack_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data")

    try:
        data = builder.read(soulpack_bytes, req.brand_id)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to decrypt/read soulpack: {e}",
        )

    character = data.get("character", {})
    voice = data.get("voice_profile")
    manifest = data.get("manifest", {})

    return {
        "manifest": manifest,
        "character": character,
        "voice_profile": voice,
        "has_rag": bool(data.get("rag_documents")),
        "has_prompt_template": bool(data.get("prompt_template")),
    }
