"""Virtual Idol API — preset listing, scene triggering, quick character creation."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ai_core.services.idol_presets import (
    IDOL_PRESETS, IDOL_VOICE_PRESETS, SCENE_PROMPTS,
    get_preset, list_presets,
)

router = APIRouter(prefix="/idol", tags=["idol"])


@router.get("/presets")
async def get_idol_presets():
    """List all available virtual idol character presets."""
    return {"presets": list_presets()}


@router.get("/presets/{key}")
async def get_idol_preset_detail(key: str):
    """Get full details of a specific idol preset."""
    preset = get_preset(key)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{key}' not found")
    return {"preset": preset, "voice": IDOL_VOICE_PRESETS.get(preset.get("voice_preset", ""))}


@router.get("/scenes")
async def list_scenes():
    """List available interaction scenes."""
    return {
        "scenes": [
            {"key": key, "description": desc}
            for key, desc in SCENE_PROMPTS.items()
        ]
    }


@router.get("/voices")
async def list_idol_voices():
    """List voice presets for idol archetypes."""
    return {
        "voices": [
            {
                "key": key,
                "gender": v.get("gender_hint", "neutral"),
                "pitch": v.get("pitch", 1.0),
                "rate": v.get("rate", 1.0),
                "effect": v.get("effect", ""),
            }
            for key, v in IDOL_VOICE_PRESETS.items()
        ]
    }
