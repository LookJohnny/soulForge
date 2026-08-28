"""`.soul` export / import for the engine-side persona store (configs/characters.json).

A `.soul` is the whole character — personality, voice, embodiment (+ model file),
expression tuning, engine persona — so this module maps between the engine's
persona entry and the SoulPackBuilder container, installs model files under
assets/vtubers/souls/<soul_id>/, and (best effort) mirrors the character into
ai-core's DB so the gateway can serve it.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CHARACTERS_JSON = ROOT / "configs" / "characters.json"
SOULS_DIR = ROOT / "assets" / "vtubers" / "souls"

try:
    from ai_core.services.soul_pack_builder import SoulPackBuilder
except ImportError:  # studio run outside the uv workspace
    sys.path.insert(0, str(ROOT / "packages" / "ai-core" / "src"))
    from ai_core.services.soul_pack_builder import SoulPackBuilder

_builder = SoulPackBuilder()
_PERSONA_ONLY = ("voice", "embodiment", "expression", "id")


def _load() -> dict[str, Any]:
    return json.loads(CHARACTERS_JSON.read_text("utf-8"))


def _save(raw: dict[str, Any]) -> None:
    CHARACTERS_JSON.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )


def _model_path(url: str | None) -> Path | None:
    if not url or not url.startswith("/assets/"):
        return None
    p = (ROOT / "assets" / url[len("/assets/") :]).resolve()
    return p if p.is_file() and ROOT in p.parents else None


def export_persona(
    character_id: str, *, passphrase: str | None = None, include_model: bool = True
) -> tuple[bytes, str]:
    """Return (`.soul` bytes, filename) for one entry of configs/characters.json."""
    raw = _load()
    entry = next((c for c in raw["characters"] if c["id"] == character_id), None)
    if entry is None:
        raise KeyError(character_id)

    if not entry.get(
        "soul_id"
    ):  # stamp once so re-exports/re-imports refer to the same soul
        import uuid

        entry["soul_id"] = str(uuid.uuid4())
        _save(raw)
    studio = {k: v for k, v in entry.items() if k not in _PERSONA_ONLY}
    character = {
        "name": entry["name"],
        "archetype": entry.get("archetype", ""),
        "personality": {
            "traits": entry.get("traits", []),
            "energy": entry.get("energy", 0.5),
        },
        "catchphrases": [entry["comfort_line"]] if entry.get("comfort_line") else [],
    }
    embodiment = dict(entry.get("embodiment") or {})
    model_bytes, model_ext = None, "vrm"
    path = _model_path(embodiment.get("model")) if include_model else None
    if path is not None:
        model_bytes, model_ext = path.read_bytes(), path.suffix.lstrip(".").lower()
    data = _builder.build(
        character_data=character,
        voice_profile=entry.get("voice"),
        embodiment=embodiment or None,
        model_bytes=model_bytes,
        model_ext=model_ext,
        expression=entry.get("expression"),
        studio=studio,
        author=entry.get("author"),
        license_text=entry.get("license"),
        soul_id=entry.get("soul_id"),
        passphrase=passphrase,
    )
    return data, f"{entry['name']}.soul"


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "soul"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


def import_persona(blob: bytes, *, passphrase: str | None = None) -> dict[str, Any]:
    """Unpack a `.soul`, install its model, add/replace the persona entry. Returns summary."""
    data = _builder.read(blob, passphrase=passphrase)
    manifest = data.get("manifest", {})
    character = data.get("character", {})
    studio = dict(data.get("studio") or {})
    raw = _load()
    soul_id = manifest.get("soul_id")

    # same soul_id re-imported → update in place; else new id from the name
    existing = next((c for c in raw["characters"] if c.get("soul_id") == soul_id), None)
    if existing is not None:
        cid = existing["id"]
    else:
        cid = studio.get("id") or _slug(character.get("name", "soul"), set())
        if any(c["id"] == cid for c in raw["characters"]):
            cid = _slug(
                character.get("name", "soul"), {c["id"] for c in raw["characters"]}
            )

    archetypes = raw.get("archetypes") or {}
    archetype = studio.get("archetype") or character.get("archetype")
    if archetypes and archetype not in archetypes:
        archetype = next(k for k in archetypes if not k.startswith("$"))
    personality = character.get("personality") or {}
    entry: dict[str, Any] = {
        "id": cid,
        "name": character.get("name", cid),
        "archetype": archetype,
        "traits": studio.get("traits") or personality.get("traits") or [],
        "daily_goals": studio.get("daily_goals") or ["陪用户聊天"],
        "energy": studio.get("energy", personality.get("energy", 0.6)),
        "relationships": studio.get("relationships") or {"user": 0.5},
        "role_label": studio.get("role_label", "陪伴"),
        "color": studio.get("color", "#8ecae6"),
        "comfort_line": studio.get("comfort_line")
        or (character.get("catchphrases") or [None])[0]
        or "我在这儿。",
        "soul_id": soul_id,
    }
    for k in ("author", "license"):
        if manifest.get(k):
            entry[k] = manifest[k]
    if data.get("voice_profile"):
        entry["voice"] = data["voice_profile"]
    if data.get("expression"):
        entry["expression"] = data["expression"]

    model_url = None
    embodiment = dict(data.get("embodiment") or {})
    if data.get("model_bytes"):
        target = SOULS_DIR / soul_id
        target.mkdir(parents=True, exist_ok=True)
        fname = f"model.{data.get('model_ext', 'vrm')}"
        (target / fname).write_bytes(data["model_bytes"])
        model_url = f"/assets/vtubers/souls/{soul_id}/{fname}"
        embodiment["model"] = model_url
    elif embodiment.get("model") and not str(embodiment["model"]).startswith(
        ("/", "http")
    ):
        embodiment.pop(
            "model"
        )  # package-relative name without the file → nothing to load
    if embodiment:
        entry["embodiment"] = embodiment

    if existing is not None:
        existing.clear()
        existing.update(entry)
    else:
        raw["characters"].append(entry)
    _save(raw)
    return {
        "id": cid,
        "name": entry["name"],
        "soul_id": soul_id,
        "version": manifest.get("version"),
        "model_url": model_url,
        "model_kind": embodiment.get("kind", "vrm"),
        "updated": existing is not None,
        "character": character,
        "soul_b64": base64.b64encode(blob).decode(),
    }
