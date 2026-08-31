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
    # sync mode: the .soul is the source of truth for a character that may already exist
    upsert_by_name: bool = (
        False  # update the brand's character with the same name instead of inserting
    )
    publish: bool = False  # PUBLISHED instead of DRAFT
    archetype: str | None = None  # override (e.g. HUMAN → the character says 你, never 主人)
    bind_device: str | None = None  # point this device at the (up)serted character

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


async def upsert_character_row(
    pool,
    brand_id: str,
    fields: dict,
    *,
    upsert_by_name: bool = False,
    bind_device: str | None = None,
) -> tuple[str, bool]:
    """Insert or (by name) update a character row; invalidates prompt/device caches.

    Returns (character_id, updated). Shared by .soul import and the soul quiz.
    """
    existing = None
    if upsert_by_name:
        existing = await pool.fetchrow(
            "SELECT id FROM characters WHERE brand_id = $1 AND name = $2 "
            "ORDER BY created_at LIMIT 1",
            brand_id,
            fields["name"],
        )
    new_id = str(existing["id"]) if existing else str(uuid.uuid4())
    cols = list(fields)
    if existing:
        sets = ", ".join(f"{c} = ${i + 1}" for i, c in enumerate(cols))
        await pool.execute(
            f"UPDATE characters SET {sets}, updated_at = now() WHERE id = ${len(cols) + 1}",
            *[fields[c] for c in cols],
            new_id,
        )
    else:
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols) + 2))
        await pool.execute(
            f"INSERT INTO characters (id, brand_id, {', '.join(cols)}, created_at, updated_at) "
            f"VALUES ({placeholders}, now(), now())",
            new_id,
            brand_id,
            *[fields[c] for c in cols],
        )
    if existing:  # the prompt builder caches the character row for an hour
        try:
            from ai_core.services.cache import CacheService

            await CacheService().delete(f"char:{brand_id}:{new_id}")
        except Exception:
            logger.warning("soul.char_cache_invalidate_failed", exc_info=True)
    if bind_device:
        await pool.execute(
            "UPDATE devices SET character_id = $1, updated_at = now() WHERE id = $2",
            new_id,
            bind_device,
        )
        try:
            from ai_core.services.cache import _get_redis

            await (await _get_redis()).delete(f"device:{bind_device}")
        except Exception:
            logger.warning("soul.device_cache_invalidate_failed", exc_info=True)
    return new_id, bool(existing)


async def ensure_edge_voice(pool, character_id: str, edge_voice: str, label: str = "") -> None:
    """Persist a picked edge voice as a voice_profile and point the character at it.

    Without this, prompt_builder auto-matches a DashScope voice by species/personality —
    which is how a gentle female pick ends up sounding like longqiang_v3 (male). The edge
    provider accepts *Neural names directly, so we store it in dashscope_voice_id.
    """
    if not edge_voice or not edge_voice.endswith("Neural"):
        return
    row = await pool.fetchrow(
        "SELECT id FROM voice_profiles WHERE dashscope_voice_id = $1 AND name = $2 LIMIT 1",
        edge_voice,
        label or edge_voice,
    )
    if row:
        vid = str(row["id"])
    else:
        vid = str(uuid.uuid4())
        await pool.execute(
            """INSERT INTO voice_profiles
                   (id, name, reference_audio, description, dashscope_voice_id,
                    created_at, updated_at)
               VALUES ($1, $2, '', $3, $4, now(), now())""",
            vid,
            label or edge_voice,
            "soul quiz / .soul edge voice",
            edge_voice,
        )
    await pool.execute(
        "UPDATE characters SET voice_id = $1, updated_at = now() WHERE id = $2",
        vid,
        character_id,
    )


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
    personality = character.get("personality", {})
    fields = {
        "name": character.get("name"),
        "archetype": req.archetype or character.get("archetype", "ANIMAL"),
        "species": character.get("species"),
        "backstory": character.get("backstory"),
        "relationship": character.get("relationship"),
        "personality": personality if isinstance(personality, str) else json.dumps(personality),
        "catchphrases": list(character.get("catchphrases") or []),
        "suffix": character.get("suffix"),
        "topics": list(character.get("topics") or []),
        "forbidden": list(character.get("forbidden") or []),
        "response_length": character.get("response_length", "SHORT"),
        "voice_speed": float(character.get("voice_speed") or 1.0),
        "status": "PUBLISHED" if req.publish else "DRAFT",
    }
    if character.get("emotion_config") is not None:
        fields["emotion_config"] = json.dumps(character["emotion_config"])
    try:
        new_id, existing = await upsert_character_row(
            pool,
            brand_id,
            fields,
            upsert_by_name=req.upsert_by_name,
            bind_device=req.bind_device,
        )
    except Exception as e:
        logger.exception("soul.import_character_failed")
        raise HTTPException(status_code=500, detail="Failed to import character") from e

    edge = (data.get("voice_profile") or {}).get("edge") or {}
    if edge.get("voice"):
        try:
            await ensure_edge_voice(pool, new_id, edge["voice"], f"{character['name']} · edge")
        except Exception:
            logger.warning("soul.voice_profile_failed", exc_info=True)

    await _record(
        pool, brand_id, new_id, blob, "import", character["name"], manifest.get("version", "1.0")
    )
    logger.info("soul.imported", character_id=new_id, brand_id=brand_id, name=character["name"])

    return {
        "character_id": new_id,
        "updated": existing,
        "bound_device": req.bind_device,
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
