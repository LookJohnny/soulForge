"""studio.soul_io: persona ⇄ .soul round trip against a temp characters.json."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from studio import soul_io  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    cfg = tmp_path / "characters.json"
    model = tmp_path / "assets" / "vtubers" / "x.vrm"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"VRM-BYTES")
    cfg.write_text(
        json.dumps(
            {
                "archetypes": {"$note": "x", "creative_care": {}},
                "characters": [
                    {
                        "id": "luna",
                        "name": "Luna",
                        "archetype": "creative_care",
                        "traits": ["warm"],
                        "daily_goals": ["画画"],
                        "energy": 0.7,
                        "relationships": {"user": 0.8},
                        "role_label": "创作陪伴",
                        "color": "#fff",
                        "comfort_line": "听到啦。",
                        "voice": {"edge": {"voice": "zh-CN-XiaoxiaoNeural"}},
                        "embodiment": {
                            "kind": "vrm",
                            "model": "/assets/vtubers/x.vrm",
                            "target_height": 1.58,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    monkeypatch.setattr(soul_io, "ROOT", tmp_path)
    monkeypatch.setattr(soul_io, "CHARACTERS_JSON", cfg)
    monkeypatch.setattr(soul_io, "SOULS_DIR", tmp_path / "assets" / "vtubers" / "souls")
    return cfg


def test_export_stamps_soul_id_and_packs_model(store):
    data, filename = soul_io.export_persona("luna", passphrase="k")
    assert filename == "Luna.soul" and data.startswith(b"SOUL2\n")
    sid = json.loads(store.read_text())["characters"][0]["soul_id"]
    assert soul_io.SoulPackBuilder.peek(data)["soul_id"] == sid
    r = soul_io._builder.read(data, passphrase="k")
    assert r["model_bytes"] == b"VRM-BYTES" and r["voice_profile"]["edge"][
        "voice"
    ].startswith("zh")
    assert r["studio"]["daily_goals"] == ["画画"] and "voice" not in r["studio"]


def test_import_new_and_reimport_updates_in_place(store):
    data, _ = soul_io.export_persona("luna")
    # simulate a foreign install: drop the original entry
    raw = json.loads(store.read_text())
    raw["characters"] = []
    store.write_text(json.dumps(raw))
    r1 = soul_io.import_persona(data)
    assert (
        r1["id"] == "luna"
        and r1["updated"] is False
        and r1["model_url"].endswith("/model.vrm")
    )
    assert (
        soul_io.SOULS_DIR / r1["soul_id"] / "model.vrm"
    ).read_bytes() == b"VRM-BYTES"
    entry = json.loads(store.read_text())["characters"][0]
    assert entry["embodiment"]["model"] == r1["model_url"] and entry["voice"]["edge"]
    assert entry["archetype"] == "creative_care" and entry["comfort_line"] == "听到啦。"
    r2 = soul_io.import_persona(data)
    assert (
        r2["updated"] is True and len(json.loads(store.read_text())["characters"]) == 1
    )


def test_import_unknown_archetype_falls_back_and_slug_dedups(store):
    data, _ = soul_io.export_persona("luna")
    raw = json.loads(store.read_text())
    raw["characters"][0]["soul_id"] = (
        "different"  # same name/id, different soul → new entry
    )
    raw["archetypes"] = {"$note": "x", "other": {}}
    store.write_text(json.dumps(raw))
    r = soul_io.import_persona(data)
    assert r["id"] == "luna-2"
    entry = json.loads(store.read_text())["characters"][1]
    assert entry["archetype"] == "other"


def test_import_wrong_passphrase(store):
    data, _ = soul_io.export_persona("luna", passphrase="right")
    with pytest.raises(ValueError):
        soul_io.import_persona(data, passphrase="wrong")
