"""ai-core adapter over soulforge_harness.soul.pack.

The open harness reads/writes v2 `.soul`; this adapter wires the proprietary
v1 `.soulpack` brand envelope (master-secret KEK) so old packs keep working.
All previous import paths from this module stay valid.
"""

from soulforge_harness.soul.pack import (  # noqa: F401
    MAGIC_V2,
    LegacyBrandCodec,
    _derive_pass_key,  # noqa: F401  (tests reach in)
    portable_character,
)
from soulforge_harness.soul.pack import (
    SoulPackBuilder as _HarnessSoulPackBuilder,
)

from ai_core.services.encryption import (
    decrypt_data,
    decrypt_dek,
    encrypt_data,
    encrypt_dek,
    generate_dek,
)


class BrandCodec(LegacyBrandCodec):
    """v1 envelope: len(dek_ct) + dek_ct(KEK-wrapped) + AESGCM(zip, dek)."""

    def encrypt(self, zip_bytes: bytes, brand_id: str) -> bytes:
        dek = generate_dek()
        encrypted_dek = encrypt_dek(dek, brand_id)
        return len(encrypted_dek).to_bytes(4, "big") + encrypted_dek + encrypt_data(zip_bytes, dek)

    def decrypt(self, data: bytes, brand_id: str) -> bytes:
        dek_len = int.from_bytes(data[:4], "big")
        dek = decrypt_dek(data[4 : 4 + dek_len], brand_id)
        return decrypt_data(data[4 + dek_len :], dek)


class SoulPackBuilder(_HarnessSoulPackBuilder):
    """Drop-in: same API as before, with v1 brand support enabled."""

    def __init__(self):
        super().__init__(legacy_codec=BrandCodec())
