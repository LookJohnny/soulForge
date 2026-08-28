"""`.soul` v2 container: round trip, passphrase, tamper detection, legacy v1 read."""

import base64
import io
import json
import zipfile

import pytest

from ai_core.services.soul_pack_builder import (
    MAGIC_V2,
    SoulPackBuilder,
    portable_character,
)

CHAR = {
    "id": "should-be-dropped",
    "brand_id": "dropped-too",
    "name": "棉花糖",
    "archetype": "ANIMAL",
    "species": "兔子",
    "personality": '{"warmth": 90, "energy": 60}',
    "catchphrases": ["嘿嘿"],
    "created_at": "2026-08-28T00:00:00",
}


def _build(**kw):
    b = SoulPackBuilder()
    return b, b.build(
        character_data=CHAR,
        voice_profile={"provider": "fish", "reference_id": "abc"},
        embodiment={"kind": "vrm", "target_height": 1.58, "pose": {"upperZ": 1.3}},
        model_bytes=b"glTF-fake-bytes",
        model_ext="vrm",
        expression={"intensity": 0.4, "mouth_style": "mixed"},
        studio={"traits": ["温柔"], "role_label": "陪伴"},
        rag_documents=[("facts.md", "喜欢抹茶")],
        author="LovelyJoy",
        license_text="internal",
        **kw,
    )


def test_portable_character_strips_ids_and_parses_json():
    p = portable_character(CHAR)
    assert "id" not in p and "brand_id" not in p and "created_at" not in p
    assert p["personality"] == {"warmth": 90, "energy": 60}
    assert p["name"] == "棉花糖"


def test_v2_round_trip_plain():
    b, data = _build()
    assert data.startswith(MAGIC_V2)
    assert SoulPackBuilder.peek(data)["encrypted"] is False
    r = b.read(data)
    m = r["manifest"]
    assert m["version"] == "2.0" and m["name"] == "棉花糖" and m["author"] == "LovelyJoy"
    assert set(m["capabilities"]) >= {
        "voice",
        "embodiment",
        "model",
        "expression",
        "studio",
        "knowledge",
    }
    assert r["character"]["species"] == "兔子" and "id" not in r["character"]
    assert r["voice_profile"]["reference_id"] == "abc"
    assert r["embodiment"]["model"] == "model.vrm" and r["model_bytes"] == b"glTF-fake-bytes"
    assert r["expression"]["mouth_style"] == "mixed" and r["studio"]["role_label"] == "陪伴"
    assert r["rag_documents"] == [("facts.md", "喜欢抹茶")]
    assert len(m["files"]) == 7 and m["checksum"]


def test_v2_passphrase_required_and_checked():
    b, data = _build(passphrase="SF-7K2M-9QXA")
    assert SoulPackBuilder.peek(data)["encrypted"] is True
    with pytest.raises(ValueError, match="passphrase"):
        b.read(data)
    with pytest.raises(ValueError, match="wrong passphrase"):
        b.read(data, passphrase="nope")
    assert b.read(data, passphrase="SF-7K2M-9QXA")["character"]["name"] == "棉花糖"


def test_v2_detects_tampering():
    b, data = _build()
    header, payload = SoulPackBuilder._split_v2(data)
    # rewrite one file inside the zip without touching the manifest
    src = zipfile.ZipFile(io.BytesIO(payload))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for n in src.namelist():
            zf.writestr(n, b'{"name":"evil"}' if n == "character.json" else src.read(n))
    forged = MAGIC_V2 + json.dumps(header).encode() + b"\n" + out.getvalue()
    with pytest.raises(ValueError, match="tampered"):
        b.read(forged)


def test_soul_id_stable_when_given():
    b, data = _build(soul_id="11111111-2222-4333-8444-555555555555")
    assert b.read(data)["manifest"]["soul_id"] == "11111111-2222-4333-8444-555555555555"
    assert SoulPackBuilder.peek(data)["soul_id"] == "11111111-2222-4333-8444-555555555555"


def test_legacy_v1_still_readable():
    b = SoulPackBuilder()
    brand = "7f73e0aa-be9b-4927-8d6e-dd35ad74bc89"
    legacy = b.build_legacy(brand, {"name": "旧角色", "archetype": "HUMAN"}, {"provider": "edge"})
    assert SoulPackBuilder.detect_version(legacy) == "1.0"
    assert SoulPackBuilder.peek(legacy)["needs"] == "brand"
    r = b.read(legacy, brand_id=brand)
    assert r["character"]["name"] == "旧角色" and r["voice_profile"]["provider"] == "edge"
    with pytest.raises(ValueError, match="brand_id"):
        b.read(legacy)


def test_b64_transport_safe():
    b, data = _build()
    again = base64.b64decode(base64.b64encode(data))
    assert b.read(again)["manifest"]["version"] == "2.0"
