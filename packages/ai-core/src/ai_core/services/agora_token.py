"""Mint Agora RTC tokens for the channel Vidu's component edition joins.

Vidu renders the avatar into *our* channel, so it needs a publisher token for
it. Agora projects default to secured mode, and a join without a valid token
fails quietly on their side: Vidu reports only ``NOT_READY`` until the session
times out. Measured on this account — an empty token gave NOT_READY for 20s and
the session died; a real token acknowledged conn_init in 1.7s and held.

The signing itself is Agora's own vendored builder; this module only supplies
configuration and sane expiries.
"""

from __future__ import annotations

from ai_core.config import settings
from ai_core.vendor.agora_token_builder import Role_Publisher, Role_Subscriber, RtcTokenBuilder

# A live session tops out well under an hour, and a long-lived token is a long
# window for a leaked one.
DEFAULT_TTL_SECONDS = 3600


class AgoraConfigError(RuntimeError):
    """Raised when the Agora application credentials are not configured."""


def mint_token(
    channel: str,
    uid: int,
    *,
    publisher: bool = True,
    app_id: str = "",
    app_certificate: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Return an AccessToken2 ("007") token for one uid joining one channel.

    ``publisher`` is right for Vidu, which publishes the avatar video; a viewer
    that only watches should be given a subscriber token instead.
    """
    app_id = app_id or settings.agora_app_id
    app_certificate = app_certificate or settings.agora_app_certificate
    if not app_id or not app_certificate:
        raise AgoraConfigError("AGORA_APP_ID / AGORA_APP_CERTIFICATE are not set")
    if not channel:
        raise ValueError("channel is required")

    return RtcTokenBuilder.build_token_with_uid(
        app_id,
        app_certificate,
        channel,
        int(uid),
        Role_Publisher if publisher else Role_Subscriber,
        int(ttl_seconds),
        int(ttl_seconds),
    )
