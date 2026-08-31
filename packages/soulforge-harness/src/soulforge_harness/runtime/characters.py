"""Character registry — the single source of truth is configs/characters.json.

Everything that needs a character (planner personas, runtime server, timeline
generator, TTS voice map, renderer embodiments) loads from here so adding or
swapping a character never touches code.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from soulforge_harness.runtime.models import Persona


def _default_path() -> Path:
    """SDK 化后不再假设包内相对路径：环境变量优先，其次从 CWD 向上找 configs/characters.json。"""
    env = os.environ.get("SOULFORGE_CHARACTERS")
    if env:
        return Path(env)
    cur = Path.cwd()
    for parent in (cur, *cur.parents):
        candidate = parent / "configs" / "characters.json"
        if candidate.exists():
            return candidate
    return cur / "configs" / "characters.json"


_DEFAULT_PATH = _default_path()


class CharacterConfigError(ValueError):
    """Raised when characters.json is missing required fields."""


@lru_cache(maxsize=4)
def _load_raw(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError as exc:
        raise CharacterConfigError(f"character config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CharacterConfigError(
            f"character config is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data.get("characters"), list) or not data["characters"]:
        raise CharacterConfigError(
            "character config needs a non-empty 'characters' list"
        )
    for entry in data["characters"]:
        for key in ("id", "name", "archetype"):
            if not entry.get(key):
                raise CharacterConfigError(
                    f"character entry missing required field {key!r}: {entry}"
                )
    return data


def load_characters(path: str | Path = _DEFAULT_PATH) -> dict[str, Any]:
    """Full raw config (characters + archetypes)."""
    return _load_raw(str(path))


def load_personas(path: str | Path = _DEFAULT_PATH) -> list[Persona]:
    personas = []
    for entry in load_characters(path)["characters"]:
        personas.append(
            Persona(
                agent_id=entry["id"],
                name=entry["name"],
                archetype=entry["archetype"],
                traits=list(entry.get("traits", [])),
                voice=entry.get("voice", {}).get("edge", {}).get("voice", ""),
                energy=float(entry.get("energy", 0.8)),
                relationships=dict(entry.get("relationships", {})),
                daily_goals=list(entry.get("daily_goals", [])),
                meta={
                    "role_label": entry.get("role_label", ""),
                    "color": entry.get("color", "#8ecae6"),
                    "comfort_line": entry.get("comfort_line", ""),
                    "voice": entry.get("voice", {}),
                    "embodiment": entry.get("embodiment", {}),
                    "interests": list(entry.get("interests", [])),
                    "speech_style": entry.get("speech_style", ""),
                },
            )
        )
    return personas


def load_archetypes(path: str | Path = _DEFAULT_PATH) -> dict[str, Any]:
    """Archetype day-plan profiles with a guaranteed `default` entry."""
    archetypes = dict(load_characters(path).get("archetypes", {}))
    archetypes.pop("$note", None)
    archetypes.setdefault(
        "default", {"focus": [["study", "自由学习"]], "evening": "chatting"}
    )
    return archetypes


def character_entry(agent_id: str, path: str | Path = _DEFAULT_PATH) -> dict[str, Any]:
    for entry in load_characters(path)["characters"]:
        if entry["id"] == agent_id:
            return entry
    raise KeyError(f"unknown character id: {agent_id}")
