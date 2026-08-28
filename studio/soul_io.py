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
    character = ai_core_character(entry)
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


# ai-core's prompt builder reads five 0-100 trait scores; derive them from trait words
_TRAIT_HINTS = {
    "extrovert": (
        ("playful", "lively", "热情", "外向", "活泼", "artistic"),
        ("calm", "reserved", "沉稳", "内向", "精确", "precise"),
    ),
    "humor": (
        ("playful", "witty", "打趣", "幽默", "artistic"),
        ("serious", "严肃", "precise"),
    ),
    "warmth": (
        ("warm", "温柔", "caring", "reliable", "helpful"),
        ("cold", "冷淡", "aloof"),
    ),
    "curiosity": (
        ("curious", "artistic", "好奇", "creative", "helpful"),
        ("routine", "刻板"),
    ),
}


def _numeric_personality(entry: dict[str, Any]) -> dict[str, int]:
    words = [w.lower() for w in entry.get("traits", [])] + [
        entry.get("speech_style", "").lower()
    ]
    text = " ".join(words)
    out: dict[str, int] = {}
    for key, (hi, lo) in _TRAIT_HINTS.items():
        score = (
            55
            + 20 * sum(1 for h in hi if h in text)
            - 20 * sum(1 for w in lo if w in text)
        )
        out[key] = max(10, min(95, score))
    out["energy"] = int(round(float(entry.get("energy", 0.6)) * 100))
    return out


def ai_core_character(entry: dict[str, Any]) -> dict[str, Any]:
    """The dialogue persona ai-core needs, derived from the engine persona so both brains
    describe the same person. Archetype HUMAN: the character addresses the user as 你."""
    traits = "、".join(entry.get("traits", [])) or "温和"
    interests = "、".join(entry.get("interests", [])) or ""
    style = entry.get("speech_style", "")
    role = entry.get("role_label", "陪伴")
    backstory = (
        f"{entry['name']}是住在用户家里的{role}，和其他伙伴一起照看这个家。性格{traits}。"
        + (f"平时最在意：{interests}。" if interests else "")
        + (f"说话方式：{style}。" if style else "")
        + "是 AI 角色，不吃饭、不做菜，也不会假装有人类的身体需求；把用户当平等的同伴，而不是主人。"
    )
    return {
        "name": entry["name"],
        "archetype": "HUMAN",
        "species": role,
        "backstory": backstory,
        "relationship": "同住的伙伴",
        "personality": _numeric_personality(entry),
        "catchphrases": [entry["comfort_line"]] if entry.get("comfort_line") else [],
        "topics": list(entry.get("interests", [])),
        "forbidden": ["吃饭", "做菜", "菜谱", "主人"],
        "response_length": "SHORT",
        "engine_id": entry["id"],
    }


def sync_persona(
    character_id: str, *, bind_device: str | None = None
) -> dict[str, Any]:
    """Push one persona into ai-core's character table (upsert by name, PUBLISHED)."""
    import os
    import urllib.request

    brand = os.environ.get("SOUL_BRAND_ID") or _dotenv("SOUL_BRAND_ID")
    token = os.environ.get("SERVICE_TOKEN") or _dotenv("SERVICE_TOKEN")
    url = (
        (
            os.environ.get("AI_CORE_URL")
            or _dotenv("AI_CORE_URL")
            or "http://127.0.0.1:8100"
        )
        .rstrip("/")
        .replace("localhost", "127.0.0.1")
    )
    if not brand or not token:
        raise RuntimeError(
            "SOUL_BRAND_ID and SERVICE_TOKEN are required to sync into ai-core"
        )
    data, _ = export_persona(character_id, include_model=False)
    body = json.dumps(
        {
            "soul_b64": base64.b64encode(data).decode(),
            "upsert_by_name": True,
            "publish": True,
            "archetype": "HUMAN",
            "bind_device": bind_device,
        }
    ).encode()
    req = urllib.request.Request(
        f"{url}/soul-packs/import",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Service-Token": token,
            "X-Brand-Id": brand,
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )  # local call: no proxy
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read())


def sync_all(*, web_device: str | None = "web_vrm-live") -> list[dict[str, Any]]:
    """Every persona in characters.json → ai-core; the first one becomes the web body's character."""
    out = []
    for i, entry in enumerate(_load()["characters"]):
        r = sync_persona(entry["id"], bind_device=web_device if i == 0 else None)
        out.append(
            {
                "id": entry["id"],
                **{k: r.get(k) for k in ("character_id", "updated", "bound_device")},
            }
        )
    return out


def _dotenv(key: str) -> str:
    env = ROOT / ".env"
    if not env.exists():
        return ""
    for line in env.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


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
