"""Fake gateway speaking the web_audio wire protocol, for browser smoke tests.

Usage: uv run python studio/tests/fake_gateway.py [port]

On every `text` message it replays a full turn: emotion + relationship control
frames, `start` state, one sentence, real Opus frames (24 kHz, 60 ms), `stop`,
and — if the text contains "事件" — an `event` scene card.
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path

from aiohttp import web

HERE = Path(__file__).parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8081


def load_frames() -> list[bytes]:
    frames = []
    with open(HERE / "opus_frames_24k.bin", "rb") as f:
        while True:
            head = f.read(4)
            if len(head) < 4:
                break
            (n,) = struct.unpack("<I", head)
            frames.append(f.read(n))
    return frames


FRAMES = load_frames()

RELATIONSHIP = {
    "type": "relationship",
    "stage": "FRIEND",
    "app_mode": "dating_sim",
    "axes": {
        "affection": 312,
        "trust": 54,
        "intimacy": 12,
        "comfort": 40,
        "respect": 30,
        "energy": 88,
    },
    "deltas": {"affection": 4, "trust": 1},
    "stage_changed": False,
    "from_stage": None,
}

EVENT = {
    "type": "event",
    "event_id": "first_deep_conversation",
    "name": "第一次深谈",
    "event_type": "milestone",
    "scene": {
        "intro": "夜深了，她忽然安静下来。",
        "dialogue": "……其实我一直想问你，你为什么愿意每天来找我说话？",
        "choices": [{"text": "因为和你聊天很开心"}, {"text": "我也说不清"}],
    },
    "state_changes": {"intimacy": 5},
}


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async for msg in ws:
        if msg.type != web.WSMsgType.TEXT:
            continue
        m = json.loads(msg.data)
        t = m.get("type")
        if t == "web_hello":
            await ws.send_json(
                {
                    "type": "web_hello",
                    "device_id": "web_" + m.get("session_name", "x"),
                    "protocol": "web_audio",
                }
            )
            await ws.send_json({"type": "control", "payload": RELATIONSHIP})
        elif t == "text":
            content = m.get("content", "")
            await ws.send_json(
                {
                    "type": "control",
                    "payload": {
                        "type": "emotion",
                        "emotion": "happy",
                        "pad": {"p": 0.8, "a": 0.5, "d": 0.3},
                        "hardware": {},
                        "causes": ["你说了好听的话"],
                        "energy": 88,
                    },
                }
            )
            await ws.send_json(
                {
                    "type": "control",
                    "payload": {**RELATIONSHIP, "deltas": {"affection": 3}},
                }
            )
            await ws.send_json({"type": "text", "content": "", "state": "start"})
            await ws.send_json(
                {"type": "text", "content": "echo: " + content, "state": "sentence"}
            )
            for fr in FRAMES:
                await ws.send_bytes(fr)
                await asyncio.sleep(0.06)
            await ws.send_json({"type": "text", "content": "", "state": "stop"})
            await ws.send_json(
                {"type": "control", "payload": {"type": "tts", "state": "stop"}}
            )
            if "事件" in content:
                await ws.send_json({"type": "control", "payload": EVENT})
        elif t == "event_choice":
            await ws.send_json(
                {
                    "type": "control",
                    "payload": {
                        **RELATIONSHIP,
                        "axes": {**RELATIONSHIP["axes"], "intimacy": 17},
                        "deltas": {"intimacy": 5},
                    },
                }
            )
    return ws


def main() -> None:
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
