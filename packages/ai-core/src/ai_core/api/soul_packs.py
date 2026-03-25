"""Soul Pack API endpoints — export, import, deploy."""

import base64
import json

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


class ImportRequest(BaseModel):
    soulpack_b64: str  # base64-encoded .soulpack bytes


@router.post("/export")
async def export_soul_pack(req: ExportRequest, request: Request):
    """Export a character as an encrypted .soulpack file."""
    brand_id = _get_brand_id(request)
    pool = await get_pool()

    # Fetch character — must belong to the authenticated brand
    row = await pool.fetchrow(
        "SELECT * FROM characters WHERE id = $1 AND brand_id = $2",
        req.character_id,
        brand_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")

    character_data = dict(row)
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
        brand_id=brand_id,
        character_data=character_data,
        voice_profile=voice_profile,
    )

    # Record the export in soul_packs table
    import hashlib
    checksum = hashlib.sha256(soulpack_bytes).hexdigest()
    try:
        await pool.execute(
            """INSERT INTO soul_packs
                   (id, brand_id, character_id, version, checksum, file_url, file_size, metadata, created_at)
               VALUES (gen_random_uuid(), $1, $2, '1.0', $3, '', $4, $5, now())""",
            brand_id,
            req.character_id,
            checksum,
            len(soulpack_bytes),
            json.dumps({"source": "export", "character_name": character_data.get("name", "")}),
        )
    except Exception:
        logger.warning("soulpack.record_export_failed", exc_info=True)

    return {
        "soulpack_b64": base64.b64encode(soulpack_bytes).decode(),
        "size": len(soulpack_bytes),
        "character_name": character_data.get("name", ""),
    }


@router.post("/export.bin")
async def export_soul_pack_binary(req: ExportRequest, request: Request):
    """Export as raw binary download."""
    brand_id = _get_brand_id(request)
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT * FROM characters WHERE id = $1 AND brand_id = $2",
        req.character_id,
        brand_id,
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
        brand_id=brand_id,
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
async def import_soul_pack(req: ImportRequest, request: Request):
    """Import a .soulpack file: decrypt, restore character to DB, record import."""
    brand_id = _get_brand_id(request)

    try:
        soulpack_bytes = base64.b64decode(req.soulpack_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data")

    try:
        data = builder.read(soulpack_bytes, brand_id)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to decrypt/read soulpack: {e}",
        )

    character_data = data.get("character", {})
    manifest = data.get("manifest", {})

    if not character_data.get("name"):
        raise HTTPException(status_code=400, detail="Soulpack contains no valid character data")

    pool = await get_pool()

    # Insert character into DB under the importing brand
    import uuid as _uuid
    new_id = str(_uuid.uuid4())
    try:
        await pool.execute(
            """INSERT INTO characters
                   (id, brand_id, name, archetype, species, backstory, relationship,
                    personality, catchphrases, suffix, topics, forbidden,
                    response_length, voice_speed, status, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, 'DRAFT', now(), now())""",
            new_id,
            brand_id,
            character_data.get("name", "Imported Character"),
            character_data.get("archetype", "ANIMAL"),
            character_data.get("species"),
            character_data.get("backstory"),
            character_data.get("relationship"),
            json.dumps(character_data.get("personality", {})),
            character_data.get("catchphrases", []),
            character_data.get("suffix"),
            character_data.get("topics", []),
            character_data.get("forbidden", []),
            character_data.get("response_length", "SHORT"),
            character_data.get("voice_speed", 1.0),
        )
    except Exception as e:
        logger.exception("soulpack.import_character_failed")
        raise HTTPException(status_code=500, detail="Failed to import character") from e

    # Record the import in soul_packs table
    import hashlib
    checksum = hashlib.sha256(soulpack_bytes).hexdigest()
    try:
        await pool.execute(
            """INSERT INTO soul_packs
                   (id, brand_id, character_id, version, checksum, file_url, file_size, metadata, created_at)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, now())""",
            brand_id,
            new_id,
            manifest.get("version", "1.0"),
            checksum,
            "",  # no file URL for imports (data came inline)
            len(soulpack_bytes),
            json.dumps({"source": "import", "original_name": character_data.get("name", "")}),
        )
    except Exception:
        logger.warning("soulpack.record_import_failed", exc_info=True)
        # Non-fatal: character was already created

    logger.info(
        "soulpack.imported",
        character_id=new_id,
        brand_id=brand_id,
        name=character_data.get("name"),
    )

    return {
        "character_id": new_id,
        "manifest": manifest,
        "character_name": character_data.get("name", ""),
        "has_rag": bool(data.get("rag_documents")),
        "has_prompt_template": bool(data.get("prompt_template")),
    }
