"""Soul Pack builder — creates and reads encrypted .soulpack files.

A .soulpack is an encrypted ZIP containing:
  manifest.json        — version, checksum, metadata
  character.json       — complete character config
  prompt_template.j2   — custom prompt template (optional)
  voice_profile.json   — voice configuration
  voice_reference.wav  — voice clone reference audio (optional)
  rag_documents/       — knowledge base documents
  avatar.png           — character avatar
"""

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

import structlog

from ai_core.services.encryption import (
    decrypt_data,
    decrypt_dek,
    encrypt_data,
    encrypt_dek,
    generate_dek,
)

logger = structlog.get_logger()


class SoulPackBuilder:
    """Build and read .soulpack files."""

    VERSION = "1.0"

    def build(
        self,
        brand_id: str,
        character_data: dict,
        voice_profile: dict | None = None,
        voice_reference: bytes | None = None,
        prompt_template: str | None = None,
        rag_documents: list[tuple[str, str]] | None = None,
        avatar_data: bytes | None = None,
    ) -> bytes:
        """Build an encrypted .soulpack file.

        Args:
            brand_id: Brand UUID for encryption key derivation.
            character_data: Full character configuration dict.
            voice_profile: Voice profile dict.
            voice_reference: WAV bytes for voice cloning reference.
            prompt_template: Custom Jinja2 prompt template.
            rag_documents: List of (filename, content) tuples.
            avatar_data: PNG/JPG bytes for character avatar.

        Returns:
            Encrypted .soulpack bytes.
        """
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Character config
            zf.writestr("character.json", json.dumps(character_data, ensure_ascii=False, indent=2))

            # Voice profile
            if voice_profile:
                zf.writestr("voice_profile.json", json.dumps(voice_profile, ensure_ascii=False, indent=2))

            # Voice reference audio
            if voice_reference:
                zf.writestr("voice_reference.wav", voice_reference)

            # Custom prompt template
            if prompt_template:
                zf.writestr("prompt_template.j2", prompt_template)

            # RAG documents
            if rag_documents:
                for filename, content in rag_documents:
                    zf.writestr(f"rag_documents/{filename}", content)

            # Avatar
            if avatar_data:
                zf.writestr("avatar.png", avatar_data)

            # Manifest (added last with checksum)
            zip_buffer.seek(0)
            manifest = {
                "version": self.VERSION,
                "character_name": character_data.get("name", "unknown"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "has_voice": voice_profile is not None,
                "has_rag": bool(rag_documents),
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        # Encrypt the ZIP
        zip_bytes = zip_buffer.getvalue()
        checksum = hashlib.sha256(zip_bytes).hexdigest()

        dek = generate_dek()
        encrypted_zip = encrypt_data(zip_bytes, dek)
        encrypted_dek = encrypt_dek(dek, brand_id)

        # Pack format: [4 bytes dek_len][encrypted_dek][encrypted_zip]
        dek_len = len(encrypted_dek).to_bytes(4, "big")
        result = dek_len + encrypted_dek + encrypted_zip

        logger.info(
            "soulpack.built",
            character=character_data.get("name"),
            size=len(result),
            checksum=checksum[:12],
        )

        return result

    def read(self, soulpack_bytes: bytes, brand_id: str) -> dict:
        """Read and decrypt a .soulpack file.

        Args:
            soulpack_bytes: Raw .soulpack file bytes.
            brand_id: Brand UUID for decryption.

        Returns:
            Dict with keys: manifest, character, voice_profile, prompt_template, etc.
        """
        # Unpack format
        dek_len = int.from_bytes(soulpack_bytes[:4], "big")
        encrypted_dek = soulpack_bytes[4 : 4 + dek_len]
        encrypted_zip = soulpack_bytes[4 + dek_len :]

        # Decrypt
        dek = decrypt_dek(encrypted_dek, brand_id)
        zip_bytes = decrypt_data(encrypted_zip, dek)

        # Read ZIP
        result = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            if "manifest.json" in zf.namelist():
                result["manifest"] = json.loads(zf.read("manifest.json"))
            if "character.json" in zf.namelist():
                result["character"] = json.loads(zf.read("character.json"))
            if "voice_profile.json" in zf.namelist():
                result["voice_profile"] = json.loads(zf.read("voice_profile.json"))
            if "prompt_template.j2" in zf.namelist():
                result["prompt_template"] = zf.read("prompt_template.j2").decode()
            if "voice_reference.wav" in zf.namelist():
                result["voice_reference"] = zf.read("voice_reference.wav")
            if "avatar.png" in zf.namelist():
                result["avatar"] = zf.read("avatar.png")

            # RAG documents
            rag_docs = []
            for name in zf.namelist():
                if name.startswith("rag_documents/") and not name.endswith("/"):
                    rag_docs.append((name.split("/", 1)[1], zf.read(name).decode()))
            if rag_docs:
                result["rag_documents"] = rag_docs

        logger.info(
            "soulpack.read",
            character=result.get("character", {}).get("name"),
        )

        return result
