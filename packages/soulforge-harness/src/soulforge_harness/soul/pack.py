"""Soul Pack builder — `.soul` (v2.0) and legacy `.soulpack` (v1.0) files.

A soul is everything that makes a character *that* character, with none of any
user's data: personality, voice, 3D/plush embodiment, expression tuning,
knowledge, optional custom events. Relationship/memory state lives in the
separate companion save file (`/relationship/{u}/{c}/export`).

v2.0 container (`.soul`)
    magic "SOUL2\\n" + JSON header line + payload
    header: {"enc": "none" | "pass", "salt": b64?}
    payload: ZIP (plain) or ZIP encrypted with a key derived from a
             passphrase (PBKDF2-HMAC-SHA256, 200k rounds) — the passphrase is
             the distribution key: whoever has file + key can load the soul,
             on any brand, any body.
    ZIP layout:
      manifest.json          version, soul_id, name, author, license, created_at,
                             compat, capabilities, files{path: sha256}, checksum
      character.json         personality / archetype / phrases (portable fields only)
      prompt_template.j2     optional
      voice/profile.json     voice config (fish/edge/dashscope …)
      voice/reference.wav    optional clone reference
      embodiment/embodiment.json   kind, model file or URL, height, rest pose, toon, idle clips
      embodiment/model.<ext>       optional VRM/GLB/FBX bytes
      expression.json        PAD baseline/intensity/mouth style
      events.json            optional event overrides
      studio.json            engine-side persona (traits, goals, role_label, color, comfort_line)
      rag/<name>             knowledge documents
      avatar.png

v1.0 (`.soulpack`) = brand-key-encrypted ZIP; still readable via read().
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

import logging

from soulforge_harness.soul._crypto import decrypt_data, encrypt_data

logger = logging.getLogger("soulforge.soul")

MAGIC_V2 = b"SOUL2\n"
_PBKDF2_ROUNDS = 200_000

# character.json keeps only what describes the character — never ids/brands/timestamps.
PORTABLE_CHARACTER_FIELDS = (
    "name",
    "archetype",
    "species",
    "backstory",
    "relationship",
    "personality",
    "catchphrases",
    "suffix",
    "topics",
    "forbidden",
    "response_length",
    "voice_speed",
    "language_mode",
    "vocalization_palette",
    "age_setting",
    "emotion_config",
    "audio_clips",
    "llm_provider",
    "llm_model",
    "tts_provider",
)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def portable_character(row: dict) -> dict:
    """Strip a characters-table row (or any dict) down to portable fields."""
    out = {}
    for k in PORTABLE_CHARACTER_FIELDS:
        if k in row and row[k] is not None:
            v = row[k]
            if isinstance(v, str) and k in (
                "personality",
                "emotion_config",
                "audio_clips",
            ):
                with contextlib.suppress(ValueError):
                    v = json.loads(v)
            out[k] = v
    return out


def _derive_pass_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt, _PBKDF2_ROUNDS, dklen=32
    )


class LegacyBrandCodec:
    """v1 `.soulpack` brand-key envelope. The reference implementation lives in
    ai-core (needs the brand master secret); the open harness only reads v2."""

    def encrypt(self, zip_bytes: bytes, brand_id: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def decrypt(self, data: bytes, brand_id: str) -> bytes:  # pragma: no cover
        raise NotImplementedError


class SoulPackBuilder:
    """Build and read `.soul` (v2) files; read legacy `.soulpack` (v1)."""

    VERSION = "2.0"
    LEGACY_VERSION = "1.0"

    # ── v2 build ──────────────────────────────────────

    def __init__(self, legacy_codec: "LegacyBrandCodec | None" = None):
        # v1 `.soulpack` support is host-provided (ai-core wires the brand codec);
        # the open harness itself only speaks v2.
        self.legacy_codec = legacy_codec

    def build(
        self,
        brand_id: str | None = None,
        character_data: dict | None = None,
        voice_profile: dict | None = None,
        voice_reference: bytes | None = None,
        prompt_template: str | None = None,
        rag_documents: list[tuple[str, str]] | None = None,
        avatar_data: bytes | None = None,
        *,
        embodiment: dict | None = None,
        model_bytes: bytes | None = None,
        model_ext: str = "vrm",
        expression: dict | None = None,
        events: dict | list | None = None,
        studio: dict | None = None,
        author: str = "",
        license_text: str = "",
        soul_id: str | None = None,
        passphrase: str | None = None,
    ) -> bytes:
        """Build a `.soul` file. `brand_id` is accepted for API compatibility but v2
        is portable — protection comes from `passphrase` (optional)."""
        character_data = portable_character(character_data or {})
        if not character_data.get("name"):
            raise ValueError("character_data.name is required")
        soul_id = soul_id or str(uuid.uuid4())

        files: dict[str, bytes] = {"character.json": _json(character_data).encode()}
        if voice_profile:
            files["voice/profile.json"] = _json(voice_profile).encode()
        if voice_reference:
            files["voice/reference.wav"] = voice_reference
        if prompt_template:
            files["prompt_template.j2"] = prompt_template.encode()
        if rag_documents:
            for filename, content in rag_documents:
                files[f"rag/{filename}"] = (
                    content.encode() if isinstance(content, str) else content
                )
        if avatar_data:
            files["avatar.png"] = avatar_data
        emb = dict(embodiment or {})
        if model_bytes:
            ext = (model_ext or "vrm").lower().lstrip(".")
            emb["model"] = f"model.{ext}"
            files[f"embodiment/model.{ext}"] = model_bytes
        if emb:
            files["embodiment/embodiment.json"] = _json(emb).encode()
        if expression:
            files["expression.json"] = _json(expression).encode()
        if events:
            files["events.json"] = _json(events).encode()
        if studio:
            files["studio.json"] = _json(studio).encode()

        capabilities = sorted(
            {
                "voice" if voice_profile else "",
                "voice_clone" if voice_reference else "",
                "embodiment" if emb else "",
                "model" if model_bytes else "",
                "expression" if expression else "",
                "events" if events else "",
                "knowledge" if rag_documents else "",
                "studio" if studio else "",
            }
            - {""}
        )
        file_hashes = {p: _sha(b) for p, b in files.items()}
        manifest = {
            "version": self.VERSION,
            "soul_id": soul_id,
            "name": character_data["name"],
            "author": author,
            "license": license_text,
            "created_at": datetime.now(UTC).isoformat(),
            "compat": {"protocol": "0.2", "vrm": "1.0", "soulforge": ">=2026.08"},
            "capabilities": capabilities,
            "files": file_hashes,
            "checksum": _sha(
                "".join(f"{p}:{h}\n" for p, h in sorted(file_hashes.items())).encode()
            ),
        }

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", _json(manifest))
            for path, blob in files.items():
                zf.writestr(path, blob)
        zip_bytes = zip_buffer.getvalue()

        if passphrase:
            salt = os.urandom(16)
            key = _derive_pass_key(passphrase, salt)
            header = {
                "enc": "pass",
                "salt": base64.b64encode(salt).decode(),
                "soul_id": soul_id,
            }
            payload = encrypt_data(zip_bytes, key)
        else:
            header = {"enc": "none", "soul_id": soul_id}
            payload = zip_bytes
        out = MAGIC_V2 + json.dumps(header).encode() + b"\n" + payload
        logger.info(
            "soul.built id=%s name=%s size=%d caps=%s",
            soul_id,
            manifest["name"],
            len(out),
            capabilities,
        )
        return out

    # ── read (v2 + legacy) ────────────────────────────

    @staticmethod
    def detect_version(data: bytes) -> str:
        return "2.0" if data.startswith(MAGIC_V2) else "1.0"

    @staticmethod
    def peek(data: bytes) -> dict:
        """Header only (no decryption): version, soul_id, whether a passphrase is needed."""
        if not data.startswith(MAGIC_V2):
            return {"version": "1.0", "encrypted": True, "needs": "brand"}
        header, _ = SoulPackBuilder._split_v2(data)
        return {
            "version": "2.0",
            "soul_id": header.get("soul_id"),
            "encrypted": header.get("enc") == "pass",
            "needs": "passphrase" if header.get("enc") == "pass" else None,
        }

    @staticmethod
    def _split_v2(data: bytes) -> tuple[dict, bytes]:
        body = data[len(MAGIC_V2) :]
        nl = body.index(b"\n")
        return json.loads(body[:nl]), body[nl + 1 :]

    def read(
        self, data: bytes, brand_id: str | None = None, passphrase: str | None = None
    ) -> dict:
        """Read a `.soul` (v2) or `.soulpack` (v1) → dict of parsed parts.

        Raises ValueError on wrong passphrase / tampering.
        """
        if data.startswith(MAGIC_V2):
            header, payload = self._split_v2(data)
            if header.get("enc") == "pass":
                if not passphrase:
                    raise ValueError("this soul needs a passphrase")
                key = _derive_pass_key(passphrase, base64.b64decode(header["salt"]))
                try:
                    zip_bytes = decrypt_data(payload, key)
                except Exception as e:
                    raise ValueError("wrong passphrase or corrupted soul") from e
            else:
                zip_bytes = payload
            return self._read_zip_v2(zip_bytes)
        # legacy v1 (brand-key encrypted) — host-provided codec
        if not brand_id:
            raise ValueError("legacy .soulpack needs brand_id")
        if self.legacy_codec is None:
            raise ValueError("legacy .soulpack support is not enabled in this host")
        zip_bytes = self.legacy_codec.decrypt(data, brand_id)
        return self._read_zip_v1(zip_bytes)

    def _read_zip_v2(self, zip_bytes: bytes) -> dict:
        result: dict[str, Any] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
            # integrity: every listed file present and unmodified
            for path, digest in manifest.get("files", {}).items():
                if path not in names:
                    raise ValueError(f"soul is missing {path}")
                if _sha(zf.read(path)) != digest:
                    raise ValueError(f"soul file tampered: {path}")
            result["manifest"] = manifest
            result["character"] = json.loads(zf.read("character.json"))
            if "voice/profile.json" in names:
                result["voice_profile"] = json.loads(zf.read("voice/profile.json"))
            if "voice/reference.wav" in names:
                result["voice_reference"] = zf.read("voice/reference.wav")
            if "prompt_template.j2" in names:
                result["prompt_template"] = zf.read("prompt_template.j2").decode()
            if "avatar.png" in names:
                result["avatar"] = zf.read("avatar.png")
            if "embodiment/embodiment.json" in names:
                emb = json.loads(zf.read("embodiment/embodiment.json"))
                result["embodiment"] = emb
                model = emb.get("model")
                if model and f"embodiment/{model}" in names:
                    result["model_bytes"] = zf.read(f"embodiment/{model}")
                    result["model_ext"] = model.rsplit(".", 1)[-1]
            for key, path in (
                ("expression", "expression.json"),
                ("events", "events.json"),
                ("studio", "studio.json"),
            ):
                if path in names:
                    result[key] = json.loads(zf.read(path))
            rag = [
                (n.split("/", 1)[1], zf.read(n).decode())
                for n in names
                if n.startswith("rag/") and not n.endswith("/")
            ]
            if rag:
                result["rag_documents"] = rag
        logger.info(
            "soul.read id=%s name=%s",
            result["manifest"].get("soul_id"),
            result["character"].get("name"),
        )
        return result

    def _read_zip_v1(self, zip_bytes: bytes) -> dict:
        result: dict[str, Any] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
            if "manifest.json" in names:
                result["manifest"] = json.loads(zf.read("manifest.json"))
            if "character.json" in names:
                result["character"] = json.loads(zf.read("character.json"))
            if "voice_profile.json" in names:
                result["voice_profile"] = json.loads(zf.read("voice_profile.json"))
            if "prompt_template.j2" in names:
                result["prompt_template"] = zf.read("prompt_template.j2").decode()
            if "voice_reference.wav" in names:
                result["voice_reference"] = zf.read("voice_reference.wav")
            if "avatar.png" in names:
                result["avatar"] = zf.read("avatar.png")
            rag = [
                (n.split("/", 1)[1], zf.read(n).decode())
                for n in names
                if n.startswith("rag_documents/") and not n.endswith("/")
            ]
            if rag:
                result["rag_documents"] = rag
        logger.info(
            "soulpack.read_legacy character=%s", result.get("character", {}).get("name")
        )
        return result

    # ── legacy v1 build (kept for tests / old clients) ─

    def build_legacy(
        self, brand_id: str, character_data: dict, voice_profile: dict | None = None
    ) -> bytes:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("character.json", _json(character_data))
            if voice_profile:
                zf.writestr("voice_profile.json", _json(voice_profile))
            zf.writestr(
                "manifest.json",
                _json(
                    {
                        "version": self.LEGACY_VERSION,
                        "character_name": character_data.get("name", "unknown"),
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                ),
            )
        zip_bytes = zip_buffer.getvalue()
        if self.legacy_codec is None:
            raise ValueError("legacy .soulpack support is not enabled in this host")
        return self.legacy_codec.encrypt(zip_bytes, brand_id)
