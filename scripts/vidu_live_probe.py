#!/usr/bin/env python3
"""Drive a Vidu S2-Avatar realtime session over WebSocket, without audio or RTC.

The WS control protocol carries ``text_msg`` (type 99), so the character can be
prompted with text alone. With ``audio.enable_transcription`` on, its reply comes
back over the same socket as type 10 events. That is enough to answer the one
question a unit test cannot: given a memory marked implicit-only, does the live
model actually keep it out of its mouth?

    VIDU_API_KEY=vda_... python scripts/vidu_live_probe.py \
        --live-id 998... --say "我今天下午有什么事来着？"

Pass ``--live-id`` for a session created by scripts/vidu_live.py, so this probe
never creates (or bills) one of its own.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import websockets

DEFAULT_WS_HOST = "wss://api.vidu.com"

# From the App WebSocket Control Protocol table.
T_CONN_INIT = 1
T_CONN_INIT_ACK = 2
T_CALL_HANGUP = 5
T_FORCE_HANGUP = 6
T_TEXT_MSG = 99
T_USER_TRANSCRIPT = 9
T_CHARACTER_TRANSCRIPT = 10

_TYPE_NAMES = {
    T_CONN_INIT_ACK: "conn_init_ack",
    T_FORCE_HANGUP: "force_hangup",
    T_USER_TRANSCRIPT: "user_transcript",
    T_CHARACTER_TRANSCRIPT: "character_transcript",
}


async def _say_next(
    ws, args, conn_id: str, seq: int, pending: list, turns: list
) -> None:
    if not pending:
        return
    content = pending.pop(0)
    await ws.send(
        _envelope(
            T_TEXT_MSG,
            args.live_id,
            conn_id,
            seq,
            {
                "text_msg": {
                    "msg_id": f"{conn_id}-{len(turns) + 1}",
                    "content": content,
                    "timestamp": int(time.time() * 1000),
                }
            },
        )
    )
    turns.append((content, ""))
    print(f"→ text_msg: {content}")


def _envelope(
    msg_type: int, live_id: str, conn_id: str, seq: int, payload: dict
) -> str:
    return json.dumps(
        {
            "type": msg_type,
            "live_id": live_id,
            "conn_id": conn_id,
            "seq_id": seq,
            "payload": payload,
        }
    )


async def run(args: argparse.Namespace) -> int:
    api_key = os.environ.get("VIDU_API_KEY", "")
    if not api_key:
        print("VIDU_API_KEY is not set", file=sys.stderr)
        return 2

    conn_id = args.conn_id or f"probe-{int(time.time())}"
    url = (
        f"{args.ws_host}/live/ws/live/connect?live_id={args.live_id}&conn_id={conn_id}"
    )
    pending = list(args.say)
    turns: list[tuple[str, str]] = []  # (said, heard)
    seq = 0

    # websockets honours the macOS system proxy, which on a dev machine is often a
    # local Clash/Surge listener that mangles the upgrade. curl reaches Vidu fine
    # without it, so go direct unless asked otherwise.
    async with websockets.connect(
        url,
        additional_headers={"Authorization": f"Token {api_key}"},
        proxy=None if not args.use_system_proxy else True,
    ) as ws:
        seq += 1
        await ws.send(
            _envelope(
                T_CONN_INIT, args.live_id, conn_id, seq, {"conn_init": {"version": 1}}
            )
        )
        print(f"→ conn_init (conn_id={conn_id})")

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=deadline - time.monotonic()
                )
            except asyncio.TimeoutError:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"← (non-JSON) {str(raw)[:200]}")
                continue

            mtype = msg.get("type")
            name = _TYPE_NAMES.get(mtype, str(mtype))
            payload = msg.get("payload", {})

            if mtype == T_CONN_INIT_ACK:
                ack = payload.get("conn_init_ack", {})
                print(
                    f"← conn_init_ack success={ack.get('success')} {ack.get('error_msg', '')}"
                )
                if not ack.get("success"):
                    return 1
                seq += 1
                await _say_next(ws, args, conn_id, seq, pending, turns)
                continue

            if mtype == T_FORCE_HANGUP:
                print(f"← force_hangup {json.dumps(payload, ensure_ascii=False)[:300]}")
                break

            text = ""
            for holder in payload.values():
                if isinstance(holder, dict) and holder.get("content"):
                    text = holder["content"]
                    break
            print(f"← {name} {text or json.dumps(payload, ensure_ascii=False)[:200]}")

            if mtype == T_CHARACTER_TRANSCRIPT and text:
                if turns and turns[-1][1] == "":
                    turns[-1] = (turns[-1][0], text)
                # The character has finished this turn, so the next question is
                # asked with the previous tool result already in its context —
                # that is what separates a first-turn race from a model that
                # simply ignores what it was handed.
                if pending:
                    seq += 1
                    await _say_next(ws, args, conn_id, seq, pending, turns)

        seq += 1
        await ws.send(_envelope(T_CALL_HANGUP, args.live_id, conn_id, seq, {}))
        print("→ call_hangup")

    if turns:
        print("\n--- transcript ---")
        for said, heard in turns:
            print(f"  user      : {said}")
            print(f"  character : {heard or '(no reply)'}")
    else:
        print("\n(no character transcript received)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-id", required=True)
    parser.add_argument(
        "--say",
        action="append",
        default=None,
        help="Message to send; repeat for a multi-turn probe",
    )
    parser.add_argument("--conn-id", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--ws-host", default=os.environ.get("VIDU_WS_HOST", DEFAULT_WS_HOST)
    )
    parser.add_argument(
        "--use-system-proxy",
        action="store_true",
        help="Route the WebSocket through the system proxy instead of going direct",
    )
    args = parser.parse_args()
    if not args.say:
        args.say = ["我今天下午有什么事来着？"]
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
