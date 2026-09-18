#!/usr/bin/env python3
"""Create a Vidu S2-Avatar realtime session wired to SoulForge's memory layer.

The realtime edition runs ASR / LLM / TTS and renders the character on Vidu's
side. The one thing we do not hand over is memory: ``memory_retrieval.provider``
is set to ``self`` so Vidu's model calls back into ai-core's
``/vidu/memory/retrieve``, and the unified cognition layer stays the single
source of truth for what the companion knows about the user.

    VIDU_API_KEY=vda_... SOULFORGE_PUBLIC_BASE_URL=https://xxx.trycloudflare.com \
        python scripts/vidu_live.py --user-id u_123 --avatar-image https://.../face.jpg

The public base URL must be reachable from Vidu's servers — a tunnel, not
127.0.0.1. Use ``--dry-run`` to print the request body without creating a
session (creation alone is free; billing starts when a client connects).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# Importing from the package keeps token minting and verification in one place.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "packages",
        "ai-core",
        "src",
    ),
)

from ai_core.api.vidu_retrieval import MEMORY_TOOL_INSTRUCTION  # noqa: E402
from ai_core.services.vidu_session_token import mint_session_token  # noqa: E402

DEFAULT_HOST = "https://api.vidu.com"


def build_payload(args: argparse.Namespace, token: str) -> dict:
    payload: dict = {
        "model": args.model,
        "call_mode": args.call_mode,
        "avatar": {
            "image_uri": args.avatar_image,
            "persona": args.persona,
        },
        "memory_retrieval": {
            "enabled": True,
            # "self" is the whole point: Vidu asks us, it does not remember for us.
            "provider": "self",
            "endpoint": f"{args.public_base_url.rstrip('/')}/vidu/memory/retrieve",
            "authorization": f"Bearer {token}",
            "timeout_ms": args.memory_timeout_ms,
            "tool_instruction": MEMORY_TOOL_INSTRUCTION,
        },
    }
    if args.enable_transcription:
        # Without this the character's reply exists only as RTC audio, so a
        # headless check (scripts/vidu_live_probe.py) has nothing to read.
        payload["audio"] = {"enable_transcription": True}
    if args.voice:
        payload["avatar"]["voice"] = args.voice
    if args.idle_timeout_seconds:
        payload["idle_timeout_seconds"] = args.idle_timeout_seconds
    return payload


def create_live(host: str, api_key: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{host}/live/s_avatar/realtime",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # Avatar preparation takes the better part of a minute before this returns.
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="SoulForge end user id")
    parser.add_argument("--character-id", default=None)
    parser.add_argument(
        "--avatar-image", required=True, help="Publicly reachable image URL"
    )
    parser.add_argument("--persona", default="", help="Character persona prompt")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--model", default="vidu-s2", choices=["vidu-s1", "vidu-s2"])
    parser.add_argument("--call-mode", default="video", choices=["video", "audio"])
    parser.add_argument("--memory-timeout-ms", type=int, default=3000)
    parser.add_argument(
        "--no-transcription",
        dest="enable_transcription",
        action="store_false",
        help="Do not return reply text over the WebSocket",
    )
    parser.add_argument("--idle-timeout-seconds", type=int, default=0)
    parser.add_argument(
        "--public-base-url",
        default=os.environ.get("SOULFORGE_PUBLIC_BASE_URL", ""),
        help="Public base URL of ai-core, reachable by Vidu",
    )
    parser.add_argument("--host", default=os.environ.get("VIDU_HOST", DEFAULT_HOST))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.public_base_url:
        parser.error("--public-base-url (or SOULFORGE_PUBLIC_BASE_URL) is required")
    if not args.public_base_url.startswith(("http://", "https://")):
        parser.error("--public-base-url must be an absolute http(s) URL")

    # No live_id yet — CreateLive is what mints it. The token is therefore bound
    # to the user, not to a single session; verify_session_token treats an unset
    # live claim as "any session of this user".
    token = mint_session_token(end_user_id=args.user_id, character_id=args.character_id)
    payload = build_payload(args, token)

    if args.dry_run:
        redacted = json.loads(json.dumps(payload))
        redacted["memory_retrieval"]["authorization"] = "Bearer <session-token>"
        print(json.dumps(redacted, ensure_ascii=False, indent=2))
        return 0

    api_key = os.environ.get("VIDU_API_KEY", "")
    if not api_key:
        print("VIDU_API_KEY is not set", file=sys.stderr)
        return 2

    try:
        result = create_live(args.host, api_key, payload)
    except urllib.error.HTTPError as exc:
        print(f"CreateLive failed: HTTP {exc.code}", file=sys.stderr)
        print(exc.read().decode("utf-8", "replace"), file=sys.stderr)
        return 1

    live = result.get("live", {})
    rtc = result.get("rtc", {})
    print(f"live_id       : {live.get('id')}")
    print(f"status        : {live.get('status')}")
    print(f"model         : {live.get('model')}")
    print(f"live_duration : {live.get('live_duration')}s")
    print(f"rtc.app_id    : {rtc.get('app_id')}")
    print(f"rtc.channel   : {rtc.get('channel_id') or rtc.get('channel')}")
    print(f"client_secret : {(result.get('client_secret') or '')[:24]}...")
    print()
    print(
        "A session left without a WebSocket connection ends on timeout and is not billed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
