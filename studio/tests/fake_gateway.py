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
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8082


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
# Real gateway web_audio sessions send one whole MP3 per sentence; a raw-Opus
# frame burst is what xiaozhi-style devices get. The fixture exercises both.
MP3_CLIP = (
    (HERE / "clip_24k.mp3").read_bytes() if (HERE / "clip_24k.mp3").exists() else b""
)

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
            await ws.send_json(
                {
                    "type": "control",
                    "payload": {
                        "type": "session",
                        "session_id": "fake",
                        "end_user_id": "u-1",
                        "character_id": "c-1",
                        "character_name": "小星",
                    },
                }
            )
            await ws.send_json({"type": "control", "payload": RELATIONSHIP})
        elif t == "set_app_mode":
            mode = m.get("app_mode", "dating_sim")
            await ws.send_json(
                {
                    "type": "control",
                    "payload": {
                        **RELATIONSHIP,
                        "app_mode": mode,
                        "stage": "COMPANION" if mode == "companion" else "FRIEND",
                    },
                }
            )
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
            if MP3_CLIP:  # sentence 1 as a whole MP3 clip (real web_audio behaviour)
                await ws.send_bytes(MP3_CLIP)
                await asyncio.sleep(0.3)
            for fr in FRAMES:  # sentence 2 as raw Opus frames
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


# ── fake ai-core (what studio's /api/core proxy talks to) ──
GRAPH = {
    "nodes": [
        {
            "id": "m1",
            "layer": "PROFILE",
            "content": "喜欢喝抹茶拿铁",
            "importance": 6,
            "created_at": "2026-08-20T10:00:00+00:00",
        },
        {
            "id": "m2",
            "layer": "EPISODIC",
            "content": "上周去了海边看日落",
            "importance": 8,
            "created_at": "2026-08-24T10:00:00+00:00",
        },
        {
            "id": "m3",
            "layer": "EPISODIC",
            "content": "考试前很紧张",
            "importance": 5,
            "created_at": "2026-06-01T10:00:00+00:00",
        },
        {
            "id": "m4",
            "layer": "RELATIONAL",
            "content": "难过时希望被安静陪着",
            "importance": 9,
            "created_at": "2026-08-25T10:00:00+00:00",
        },
    ],
    "edges": [{"a": "m2", "b": "m4", "w": 0.72}, {"a": "m1", "b": "m2", "w": 0.61}],
    "source": "vector",
}


async def http_graph(_request: web.Request) -> web.Response:
    return web.json_response(GRAPH)


async def http_near(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "near": [
                {
                    "event_id": "shared_vulnerability",
                    "name": "彼此的软肋",
                    "progress": 66,
                    "missing": ["已经历「first_deep_conversation」"],
                }
            ]
        }
    )


async def http_export(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "version": 1,
            "relationship": RELATIONSHIP["axes"],
            "events": [],
            "memories": GRAPH["nodes"],
        }
    )


async def body_handler(request: web.Request) -> web.WebSocketResponse:
    """Minimal Protocol 0.2 runtime: welcome, plan_state, then a burst of actions."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    hello = json.loads((await ws.receive()).data)
    assert hello.get("type") == "hello" and hello.get("backend") == "web"
    steps = hello.get("manifest", {}).get("supported_steps", [])
    await ws.send_json(
        {
            "type": "welcome",
            "protocol": "0.2",
            "body_id": hello["body_id"],
            "accepted_agents": hello.get("agent_ids") or ["luna"],
            "supported_steps": steps,
        }
    )
    await ws.send_json(
        {
            "type": "plan_state",
            "agent_id": "luna",
            "clock": "20:47",
            "hour_goal": "陪你聊天",
            "activities": [],
            "day_blocks": [],
            "last_decision": {},
        }
    )
    observations = []
    plan = [
        ("look_at_user", 0.5),
        ("wave", 0.8),
        ("stir_pan", 0.6),
        ("listening_nod", 0.4),
    ]

    async def send_action(i, name, dur):
        await ws.send_json(
            {
                "type": "action",
                "agent_id": "luna",
                "name": name,
                "command_id": f"cmd-{i}",
                "duration_s": dur,
                "sequence": i,
                "params": {},
                "adapter_command": {},
                "interruptible": True,
                "safety_class": "expressive",
                "ack_policy": "on_complete",
            }
        )

    # ack_policy on_complete: the next step goes out when the body reports done
    idx = 0
    await send_action(idx, *plan[idx])
    async for msg in ws:
        if msg.type != web.WSMsgType.TEXT:
            continue
        data = json.loads(msg.data)
        if data.get("type") != "observation":
            continue
        observations.append(data)
        await ws.send_json(
            {
                "type": "tick",
                "sim_minute": 1247,
                "clock": "20:47",
                "observed": len(observations),
                "statuses": [o["status"] for o in observations],
            }
        )
        if (
            data.get("status") in ("done", "failed", "interrupted")
            and data.get("command_id") == f"cmd-{idx}"
        ):
            idx += 1
            if idx < len(plan):
                await send_action(idx, *plan[idx])
    return ws


def main() -> None:
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/body", body_handler)
    app.router.add_get("/memory/graph", http_graph)
    app.router.add_get("/relationship/{u}/{c}/events/near", http_near)
    app.router.add_get("/relationship/{u}/{c}/export", http_export)
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
