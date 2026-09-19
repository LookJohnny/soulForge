#!/usr/bin/env python3
"""Talk to a Vidu S2 companion from the terminal, with SoulForge memory wired in.

Creates a live session (memory preamble in the persona, retrieval callback
pointed at ai-core), then gives you a prompt. Type, press enter, read what the
character says back. No microphone, no RTC — the point is the memory, not the
face.

    VIDU_API_KEY=vda_... SERVICE_TOKEN=... \
        python scripts/vidu_try.py --user-id <uuid> \
            --public-base-url https://xxx.loca.lt

Billing runs on connection time, not turns, so this hangs up as soon as you
leave. Type /quit (or Ctrl-D) to end; /mem shows what the character was given.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
import urllib.request

import websockets

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "packages",
        "ai-core",
        "src",
    ),
)

from ai_core.services.vidu_session_token import mint_session_token  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vidu_live import create_live, fetch_preamble  # noqa: E402
from vidu_live_probe import (  # noqa: E402
    T_CALL_HANGUP,
    T_CHARACTER_TRANSCRIPT,
    T_CONN_INIT,
    T_CONN_INIT_ACK,
    T_FORCE_HANGUP,
    T_TEXT_MSG,
    T_USER_TRANSCRIPT,
    _envelope,
)

DEFAULT_AVATAR = "https://scene.vidu.zone/media-asset/084945-xpk47RWYcBgJ27nJ.png"
DEFAULT_PERSONA = "你是用户的长期陪伴角色。说话克制、口语化、允许留白。"

BOLD, DIM, CYAN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[36m", "\033[33m", "\033[0m"


class Session:
    """One live session plus the WebSocket that drives it."""

    def __init__(self, args, preamble: str, live_id: str):
        self.args = args
        self.preamble = preamble
        self.live_id = live_id
        self.conn_id = f"try-{int(time.time())}"
        self.seq = 0
        self.ready = asyncio.Event()
        self.speaking = asyncio.Event()
        self.closed = asyncio.Event()

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq

    async def send_text(self, ws, content: str) -> None:
        self.speaking.clear()
        await ws.send(
            _envelope(
                T_TEXT_MSG,
                self.live_id,
                self.conn_id,
                self._next_seq(),
                {
                    "text_msg": {
                        "msg_id": f"{self.conn_id}-{self.seq}",
                        "content": content,
                        "timestamp": int(time.time() * 1000),
                    }
                },
            )
        )

    async def reader(self, ws) -> None:
        """Print whatever the character says; everything else stays quiet."""
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                payload = msg.get("payload", {})

                if mtype == T_CONN_INIT_ACK:
                    ack = payload.get("conn_init_ack", {})
                    if ack.get("success"):
                        self.ready.set()
                    else:
                        print(f"{YELLOW}连接失败: {ack.get('error_msg')}{RESET}")
                        self.closed.set()
                    continue

                if mtype == T_FORCE_HANGUP:
                    reason = json.dumps(payload, ensure_ascii=False)
                    print(f"\n{YELLOW}对方挂断了: {reason[:200]}{RESET}")
                    self.closed.set()
                    return

                if mtype == T_USER_TRANSCRIPT:
                    continue

                if mtype == T_CHARACTER_TRANSCRIPT:
                    text = ""
                    for holder in payload.values():
                        if isinstance(holder, dict) and holder.get("content"):
                            text = holder["content"]
                            break
                    if text:
                        print(f"{CYAN}角色{RESET} {text}\n")
                        self.speaking.set()
        except websockets.exceptions.ConnectionClosed:
            self.closed.set()

    async def hangup(self, ws) -> None:
        with contextlib.suppress(Exception):
            await ws.send(
                _envelope(
                    T_CALL_HANGUP, self.live_id, self.conn_id, self._next_seq(), {}
                )
            )


async def chat(args, preamble: str, live_id: str) -> None:
    api_key = os.environ["VIDU_API_KEY"]
    session = Session(args, preamble, live_id)
    url = (
        f"{args.ws_host}/live/ws/live/connect"
        f"?live_id={live_id}&conn_id={session.conn_id}"
    )

    # Direct, not via the macOS system proxy — a local Clash/Surge listener
    # mangles the upgrade.
    async with websockets.connect(
        url, additional_headers={"Authorization": f"Token {api_key}"}, proxy=None
    ) as ws:
        reader = asyncio.create_task(session.reader(ws))
        await ws.send(
            _envelope(
                T_CONN_INIT,
                live_id,
                session.conn_id,
                session._next_seq(),
                {"conn_init": {"version": 1}},
            )
        )

        try:
            await asyncio.wait_for(session.ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            print(f"{YELLOW}连接超时{RESET}")
            reader.cancel()
            return

        print(
            f"{DIM}已连接。直接打字说话，/mem 看角色拿到了什么，/quit 结束。{RESET}\n"
        )

        loop = asyncio.get_running_loop()
        try:
            while not session.closed.is_set():
                line = await loop.run_in_executor(None, _read_line)
                if line is None or line.strip() in {"/quit", "/exit"}:
                    break
                text = line.strip()
                if not text:
                    continue
                if text == "/mem":
                    print(f"{DIM}{preamble or '(开场没有记忆)'}{RESET}\n")
                    continue
                await session.send_text(ws, text)
                # Give the character its turn before showing the next prompt.
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(session.speaking.wait(), timeout=45)
        finally:
            await session.hangup(ws)
            reader.cancel()


def _read_line() -> str | None:
    try:
        return input(f"{BOLD}你{RESET} ")
    except EOFError:
        return None


def report_billing(live_id: str, api_key: str, host: str) -> None:
    req = urllib.request.Request(
        f"{host}/live/v1/lives/{live_id}", headers={"Authorization": f"Token {api_key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            live = json.loads(resp.read())["live"]
    except Exception:  # noqa: BLE001 - a billing readout is never worth an error
        return
    print(
        f"{DIM}本次会话 {live.get('billed_seconds')}s，"
        f"{live.get('credits_cost')} credits（{live.get('close_reason')}）{RESET}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="SoulForge end user uuid")
    parser.add_argument("--character-id", default=None)
    parser.add_argument("--avatar-image", default=DEFAULT_AVATAR)
    parser.add_argument("--persona", default=DEFAULT_PERSONA)
    parser.add_argument(
        "--public-base-url", default=os.environ.get("SOULFORGE_PUBLIC_BASE_URL", "")
    )
    parser.add_argument(
        "--ai-core-url",
        default=os.environ.get("SOULFORGE_AI_CORE_URL", "http://127.0.0.1:8100"),
    )
    parser.add_argument(
        "--host", default=os.environ.get("VIDU_HOST", "https://api.vidu.com")
    )
    parser.add_argument(
        "--ws-host", default=os.environ.get("VIDU_WS_HOST", "wss://api.vidu.com")
    )
    parser.add_argument("--memory-timeout-ms", type=int, default=5000)
    parser.add_argument("--preamble-limit", type=int, default=6)
    args = parser.parse_args()
    args.preamble = True
    args.enable_transcription = True
    args.voice = None
    args.model = "vidu-s2"
    args.call_mode = "video"
    args.idle_timeout_seconds = 0

    if not os.environ.get("VIDU_API_KEY"):
        print("VIDU_API_KEY is not set", file=sys.stderr)
        return 2
    if not args.public_base_url:
        parser.error("--public-base-url (or SOULFORGE_PUBLIC_BASE_URL) is required")

    service_token = os.environ.get("SERVICE_TOKEN", "")
    preamble = ""
    if service_token:
        preamble = fetch_preamble(args.ai_core_url, service_token, args)
    else:
        print(
            "warning: SERVICE_TOKEN not set — the character starts with no memory",
            file=sys.stderr,
        )

    token = mint_session_token(end_user_id=args.user_id, character_id=args.character_id)

    # Imported rather than rebuilt so the try-it-out path and the scripted path
    # cannot drift into sending different session config.
    from vidu_live import build_payload  # noqa: PLC0415

    payload = build_payload(args, token, preamble)

    print(f"{DIM}正在创建会话，约需 1 分钟（数字人预处理）…{RESET}")
    result = create_live(args.host, os.environ["VIDU_API_KEY"], payload)
    live_id = result["live"]["id"]
    print(f"{DIM}live_id={live_id}{RESET}")

    try:
        asyncio.run(chat(args, preamble, live_id))
    except KeyboardInterrupt:
        pass
    finally:
        report_billing(live_id, os.environ["VIDU_API_KEY"], args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
