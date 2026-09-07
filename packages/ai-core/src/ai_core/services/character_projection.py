"""Project the authored character roster into the existing tenant schema.

The file remains the authoring source. PostgreSQL holds its serving projection
and stable identities, never a separately edited copy of the persona.
"""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID, uuid5

from soulforge_harness.runtime.identity import (
    RuntimeIdentity,
    character_id_for_agent,
    validate_agent_id,
)

_TRAIT_HINTS = {
    "extrovert": (
        ("playful", "lively", "热情", "外向", "活泼", "artistic"),
        ("calm", "reserved", "沉稳", "内向", "精确", "precise"),
    ),
    "humor": (("playful", "witty", "打趣", "幽默", "artistic"), ("serious", "严肃", "precise")),
    "warmth": (("warm", "温柔", "caring", "reliable", "helpful"), ("cold", "冷淡", "aloof")),
    "curiosity": (("curious", "artistic", "好奇", "creative", "helpful"), ("routine", "刻板")),
}


def json_object(value: Any) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


def project_character_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Match the existing Studio roster-to-dialogue persona transformation."""
    validate_agent_id(entry.get("id"))
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 50:
        raise ValueError("character name must contain 1-50 characters")
    traits = entry.get("traits", [])
    interests = entry.get("interests", [])
    if not all(
        isinstance(items, list) and all(isinstance(v, str) for v in items)
        for items in (traits, interests)
    ):
        raise ValueError("traits and interests must be string lists")
    style = str(entry.get("speech_style", ""))
    role = str(entry.get("role_label", "陪伴"))
    energy = float(entry.get("energy", 0.6))
    if not math.isfinite(energy) or not 0 <= energy <= 1:
        raise ValueError("character energy must be between 0 and 1")
    text = " ".join([w.lower() for w in traits] + [style.lower()])
    personality = {
        key: max(
            10, min(95, 55 + 20 * sum(h in text for h in hi) - 20 * sum(w in text for w in lo))
        )
        for key, (hi, lo) in _TRAIT_HINTS.items()
    }
    personality["energy"] = int(round(energy * 100))
    # Imported souls may already carry designer-authored numeric traits.
    authored_personality = entry.get("personality") or {}
    if not isinstance(authored_personality, dict):
        raise ValueError("personality must be an object")
    for key, value in authored_personality.items():
        if key in personality and isinstance(value, (int, float)) and math.isfinite(value):
            personality[key] = max(0, min(100, value))
    backstory = (
        f"{name}是住在用户家里的{role}，和其他伙伴一起照看这个家。"
        f"性格{'、'.join(traits) or '温和'}。"
        + (f"平时最在意：{'、'.join(interests)}。" if interests else "")
        + (f"说话方式：{style}。" if style else "")
        + "是 AI 角色，不吃饭、不做菜，也不会假装有人类的身体需求；把用户当平等的同伴，而不是主人。"
    )
    return {
        "name": name,
        "archetype": "HUMAN",
        "species": role[:30],
        "backstory": str(entry.get("backstory") or backstory),
        "relationship": str(entry.get("relationship") or "同住的伙伴")[:20],
        "personality": personality,
        "catchphrases": list(
            entry["catchphrases"]
            if entry.get("catchphrases") is not None
            else ([entry["comfort_line"]] if entry.get("comfort_line") else [])
        ),
        "topics": list(entry.get("topics") or interests),
        "forbidden": list(entry.get("forbidden") or ["吃饭", "做菜", "菜谱", "主人"]),
        "response_length": "SHORT",
        "engine_id": entry["id"],
    }


async def ensure_runtime_user(conn, user_id: str) -> None:
    await conn.execute(
        "INSERT INTO end_users (id, created_at, updated_at) "
        "VALUES ($1, now(), now()) ON CONFLICT (id) DO NOTHING",
        str(UUID(user_id)),
    )


async def validate_runtime_identity(conn, brand_id: str, identity: RuntimeIdentity) -> dict:
    """Verify tenant, roster identity and user before any state read or write."""
    row = await conn.fetchrow(
        """SELECT c.id, c.emotion_config FROM characters c
           WHERE c.id = $1 AND c.brand_id = $2
             AND EXISTS (SELECT 1 FROM end_users WHERE id = $3)""",
        identity.character_id,
        str(UUID(brand_id)),
        identity.user_id,
    )
    if row is None:
        raise PermissionError("Unknown user or character in this brand")
    marker = json_object(row.get("emotion_config")).get("runtime_projection", {})
    if marker.get("agent_id") != identity.agent_id:
        raise PermissionError("agent_id does not match the projected character")
    return dict(row)


class CharacterProjectionService:
    def __init__(self, pool, cache=None):
        self.pool, self.cache = pool, cache

    async def project(
        self, brand_id: str, user_id: str, characters: list[dict], brand_name: str = "SoulForge"
    ) -> dict:
        brand_id, user_id = str(UUID(brand_id)), str(UUID(user_id))
        entries = [(entry, project_character_fields(entry)) for entry in characters]
        ids = [entry["id"] for entry, _ in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate agent_id in character roster")
        mapping = {}
        voice_ids = []
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                "soulforge:roster:" + brand_id,
            )
            await conn.execute(
                """INSERT INTO brands (id, name, slug, created_at, updated_at)
                   VALUES ($1, $2, $3, now(), now()) ON CONFLICT (id) DO NOTHING""",
                brand_id,
                brand_name,
                "runtime-" + brand_id,
            )
            await ensure_runtime_user(conn, user_id)
            for entry, fields in entries:
                agent_id = entry["id"]
                rows = await conn.fetch(
                    "SELECT id, name, emotion_config FROM characters "
                    "WHERE brand_id = $1 ORDER BY created_at",
                    brand_id,
                )
                claimed = [
                    row
                    for row in rows
                    if json_object(row.get("emotion_config"))
                    .get("runtime_projection", {})
                    .get("agent_id")
                    == agent_id
                ]
                # Adopt an unambiguous legacy Studio-by-name projection once;
                # subsequent reloads use the agent marker even after a rename.
                legacy = [
                    row
                    for row in rows
                    if row["name"] == fields["name"]
                    and not json_object(row.get("emotion_config")).get("runtime_projection")
                ]
                existing = claimed or legacy
                if len(existing) > 1:
                    raise ValueError(f"ambiguous existing character projection for {agent_id}")
                character_id = (
                    str(existing[0]["id"])
                    if existing
                    else character_id_for_agent(brand_id, agent_id)
                )
                emotion_config = json_object(entry.get("emotion_config"))
                emotion_config["runtime_projection"] = {
                    "version": 1,
                    "agent_id": agent_id,
                    "source": "characters.json",
                    "config": entry,
                }
                voice = json_object(entry.get("voice"))
                fish = json_object(voice.get("fish"))
                edge = json_object(voice.get("edge"))
                fish_id = str(fish.get("reference_id") or voice.get("fish_audio_id") or "")
                edge_id = str(edge.get("voice") or voice.get("dashscope_voice_id") or "")
                if len(fish_id) > 64 or len(edge_id) > 100:
                    raise ValueError("voice identifier exceeds the schema limit")
                voice_id = str(uuid5(UUID(character_id), "soulforge:voice"))
                await conn.execute(
                    """INSERT INTO voice_profiles
                       (id, name, reference_audio, description, dashscope_voice_id,
                        fish_audio_id, created_at, updated_at)
                       VALUES ($1, $2, '', $3, $4, $5, now(), now())
                       ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,
                         description=EXCLUDED.description,
                         dashscope_voice_id=EXCLUDED.dashscope_voice_id,
                         fish_audio_id=EXCLUDED.fish_audio_id, updated_at=now()""",
                    voice_id,
                    fields["name"],
                    "characters.json voice projection",
                    edge_id or None,
                    fish_id or None,
                )
                voice_speed = float(fish.get("speed", entry.get("voice_speed", 1.0)))
                if not math.isfinite(voice_speed) or not 0.25 <= voice_speed <= 4:
                    raise ValueError("voice speed must be between 0.25 and 4")
                await conn.execute(
                    """INSERT INTO characters
                       (id, brand_id, name, archetype, species, backstory, relationship,
                        personality,
                        catchphrases, topics, forbidden, response_length, voice_id, voice_speed,
                        emotion_config, status, tts_provider, voice_clone_ref_id,
                        created_at, updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13,$14,
                               $15::jsonb,'PUBLISHED',$16,$17,now(),now())
                       ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,
                         archetype=EXCLUDED.archetype, species=EXCLUDED.species,
                         backstory=EXCLUDED.backstory, relationship=EXCLUDED.relationship,
                         personality=EXCLUDED.personality, catchphrases=EXCLUDED.catchphrases,
                         topics=EXCLUDED.topics, forbidden=EXCLUDED.forbidden,
                         response_length=EXCLUDED.response_length,
                         voice_id=EXCLUDED.voice_id, voice_speed=EXCLUDED.voice_speed,
                         emotion_config=EXCLUDED.emotion_config, status=EXCLUDED.status,
                         tts_provider=EXCLUDED.tts_provider,
                         voice_clone_ref_id=EXCLUDED.voice_clone_ref_id, updated_at=now()
                       WHERE characters.brand_id = EXCLUDED.brand_id""",
                    character_id,
                    brand_id,
                    fields["name"],
                    fields["archetype"],
                    fields["species"],
                    fields["backstory"],
                    fields["relationship"],
                    json.dumps(fields["personality"], ensure_ascii=False),
                    fields["catchphrases"],
                    fields["topics"],
                    fields["forbidden"],
                    fields["response_length"],
                    voice_id,
                    voice_speed,
                    json.dumps(emotion_config, ensure_ascii=False, allow_nan=False),
                    entry.get("tts_provider") or ("fish" if fish_id else "edge"),
                    fish_id or None,
                )
                mapping[agent_id] = character_id
                voice_ids.append(voice_id)
        if self.cache is not None:
            for character_id in mapping.values():
                await self.cache.delete(f"char:{brand_id}:{character_id}")
            for voice_id in voice_ids:
                await self.cache.delete(f"voice:{voice_id}")
        return {"brand_id": brand_id, "user_id": user_id, "character_map": mapping}

    async def resolve(
        self, brand_id: str, user_id: str, agent_id: str, body_id: str = "", session_id: str = ""
    ) -> dict:
        validate_agent_id(agent_id)
        brand_id, user_id = str(UUID(brand_id)), str(UUID(user_id))
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                "SELECT id, emotion_config FROM characters WHERE brand_id = $1",
                brand_id,
            )
            mapping = {}
            for row in rows:
                marker = json_object(row.get("emotion_config")).get("runtime_projection", {})
                if marker.get("agent_id"):
                    if marker["agent_id"] in mapping:
                        raise ValueError("duplicate projected agent identity")
                    mapping[marker["agent_id"]] = str(row["id"])
            if agent_id not in mapping:
                raise KeyError("agent has not been projected from the character file")
            await ensure_runtime_user(conn, user_id)
            identity = RuntimeIdentity(user_id, mapping[agent_id], agent_id, body_id, session_id)
        return {"identity": identity.to_dict(), "character_map": mapping, "brand_id": brand_id}
