#!/usr/bin/env python3
"""Vidu as a body of the Character Runtime — the brain decides, Vidu renders.

The component edition put SoulForge's TTS in charge of the voice, but the words
still came from whatever called it. This closes the loop: an utterance becomes a
Runtime event, the Runtime asks unified cognition for one decision, and the
dialogue that comes back — shaped by persona projection, memory, PAD emotion and
relationship stage — is what the avatar says.

    scripts/vidu_body.py --avatar-image ~/Desktop/vtuber-1.jpg

Requires the Runtime (ws://127.0.0.1:8765) and ai-core. Vidu billing is per
second of session, so it hangs up when you stop it.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

from ai_core.services.agora_token import mint_token  # noqa: E402

VIDU_HOST = "https://api.vidu.com"
VIDU_WS = "wss://api.vidu.com"
AGORA_SDK = "https://download.agora.io/sdk/release/AgoraRTC_N-4.23.0.js"

SAMPLE_RATE = 24000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000  # 960

STATE: dict = {}


# ── Runtime body ─────────────────────────────────────────────


class RuntimeBody:
    """One WebSocket to the Runtime, spoken to as a body.

    Deliberately thin, in the spirit of the gateway's CharacterBridge: "the
    bridge holds no persona/memory state; it is a body, not a brain." Everything
    that makes the character itself stays behind /cognition/decide.
    """

    def __init__(self, url: str, agent_id: str, body_id: str):
        self.url = url.rstrip("/")
        self.agent_id = agent_id
        self.body_id = body_id
        self.ws = None

    async def connect(self) -> None:
        self.ws = await websockets.connect(f"{self.url}/body", proxy=None)
        await self.ws.send(json.dumps({
            "type": "hello",
            "protocol": "0.2",
            "body_id": self.body_id,
            "backend": "vidu",
            "agent_ids": [self.agent_id],
            "manifest": {
                # Only speech: gaze, nav and motion belong to bodies that have
                # them. Step negotiation is the capability gate.
                "supported_steps": ["speak_line"],
                "supported_templates": [],
                "features": {
                    "speech": True,
                    "speech_only": True,
                    "autonomous_speech": True,
                    "gaze": False,
                    "nav": False,
                },
            },
        }, ensure_ascii=False))
        welcome = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=20))
        accepted = welcome.get("accepted_agents") or []
        if self.agent_id not in accepted:
            raise RuntimeError(f"Runtime 未接受 agent {self.agent_id}；可用: {accepted}")
        print(f"已作为身体接入 Runtime（agent={self.agent_id}）", flush=True)

    async def say_to_character(self, text: str) -> str:
        """Send one utterance, return the dialogue the brain decided on."""
        event_id = uuid.uuid4().hex[:12]
        await self.ws.send(json.dumps({
            "type": "event",
            "kind": "user_utterance",
            "source": self.body_id,
            "text": text,
            "target_agent": self.agent_id,
            "payload": {"event_id": event_id},
        }, ensure_ascii=False))
        return event_id

    async def reader(self, on_dialogue) -> None:
        """Dispatch dialogue to the mouth and acknowledge every command.

        Unsolicited dialogue — from perception or the Runtime's own schedule —
        arrives through the same path, which is how proactive speech will work
        without a second mechanism.
        """
        async for raw in self.ws:
            try:
                msg = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            if msg.get("type") != "action":
                continue
            params = msg.get("params") or {}
            line = params.get("dialogue")
            command_id = msg.get("command_id", "")
            if not line:
                await self._observe(command_id, "accepted")
                continue
            cog = params.get("cognitive_state") or {}
            rel = (cog.get("relationship") or {}).get("stage")
            print(
                f"[角色] {line}\n"
                f"       情绪={cog.get('emotion')} PAD={cog.get('pad')} 关系={rel}",
                flush=True,
            )
            try:
                await on_dialogue(line, params)
                await self._observe(command_id, "accepted")
            except Exception as exc:  # noqa: BLE001
                await self._observe(command_id, "failed", str(exc)[:120])

    async def _observe(self, command_id: str, status: str, error: str = "") -> None:
        if not command_id:
            return
        await self.ws.send(json.dumps({
            "type": "observation",
            "command_id": command_id,
            "agent_id": self.agent_id,
            "status": status,
            "error": error,
        }, ensure_ascii=False))


# ── mouth: TTS → PCM → Vidu ──────────────────────────────────


def stream_tts_pcm(text: str, voice: str | None, sink) -> dict:
    body = json.dumps({"text": text, "voice": voice} if voice else {"text": text}).encode()
    req = urllib.request.Request(
        f"{STATE['ai_core_url'].rstrip('/')}/tts/stream",
        data=body,
        headers={"X-Service-Token": STATE["service_token"], "Content-Type": "application/json"},
        method="POST",
    )
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    stats = {"first_audio_ms": None, "total_bytes": 0}
    started = time.time()

    def drain():
        while True:
            pcm = ff.stdout.read(FRAME_BYTES)
            if not pcm:
                return
            if stats["first_audio_ms"] is None:
                stats["first_audio_ms"] = int((time.time() - started) * 1000)
            stats["total_bytes"] += len(pcm)
            sink(pcm.ljust(FRAME_BYTES, b"\x00"))

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    with urllib.request.urlopen(req, timeout=120) as resp:
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            ff.stdin.write(chunk)
            ff.stdin.flush()
    ff.stdin.close()
    reader.join(timeout=30)
    ff.wait(timeout=10)
    stats["total_ms"] = int((time.time() - started) * 1000)
    stats["frames"] = stats["total_bytes"] // FRAME_BYTES
    return stats


# ── Vidu session ─────────────────────────────────────────────


def create_session(args, vidu_token: str) -> dict:
    avatar = args.avatar_image
    if avatar and not avatar.startswith(("http://", "https://", "data:")):
        raw = Path(avatar).expanduser().read_bytes()
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}[
            Path(avatar).suffix.lower().lstrip(".")
        ]
        avatar = f"data:image/{mime};base64," + base64.b64encode(raw).decode()

    body = json.dumps({
        "model": args.model,
        "image_uri": avatar,
        "rtc_info": {
            "provider": "agora",
            "app_id": STATE["app_id"],
            "channel_id": STATE["channel"],
            "user_id": str(args.vidu_uid),
            "token": vidu_token,
        },
    }).encode()
    req = urllib.request.Request(
        f"{VIDU_HOST}/live/s_avatar/component",
        data=body,
        headers={"Authorization": f"Token {STATE['vidu_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=200) as r:
        return json.loads(r.read())


async def drive_vidu(live_id: str, secret: str) -> None:
    conn = f"sf-{int(time.time())}"
    url = f"{VIDU_WS}/live/v1/external-lives/{live_id}/stream?conn_id={conn}&client_secret={secret}"
    seq = [0]
    async with websockets.connect(url, proxy=None) as ws:
        async def conn_init():
            seq[0] += 1
            await ws.send(json.dumps({
                "type": 1, "live_id": str(live_id), "conn_id": conn,
                "seq_id": seq[0], "payload": {"conn_init": {"version": 1}},
            }))

        await conn_init()

        async def pump():
            silence = b"\x00" * FRAME_BYTES
            while True:
                await ws.send(STATE["frames"].popleft() if STATE["frames"] else silence)
                await asyncio.sleep(FRAME_MS / 1000)

        pump_task = None
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            if msg.get("type") == 2:
                ack = msg["payload"]["conn_init_ack"]
                if ack.get("success"):
                    STATE["ready"] = True
                    print("✅ 数字人就绪", flush=True)
                    if not pump_task:
                        pump_task = asyncio.create_task(pump())
                elif ack.get("error_code") == "NOT_READY":
                    await asyncio.sleep(2)
                    await conn_init()
                else:
                    print("conn_init 失败:", ack.get("error_code"), flush=True)
                    return
            elif msg.get("type") == 6:
                print("← Vidu 挂断:", json.dumps(msg.get("payload"), ensure_ascii=False), flush=True)
                if pump_task:
                    pump_task.cancel()
                return


# ── browser ──────────────────────────────────────────────────

PAGE = """<!doctype html>
<meta charset="utf-8"><title>SoulForge 身体 × Vidu</title>
<script src="__SDK__"></script>
<style>
 body{margin:0;font:14px -apple-system,system-ui,sans-serif;background:#0f1115;color:#e6e6e6}
 .wrap{max-width:760px;margin:0 auto;padding:24px}
 #stage{width:100%;aspect-ratio:3/4;max-height:70vh;background:#181b22;border-radius:12px;overflow:hidden}
 .row{display:flex;gap:8px;margin-top:16px}
 input{flex:1;padding:10px 12px;border-radius:8px;border:1px solid #2c313c;background:#161920;color:#e6e6e6}
 button{padding:10px 18px;border-radius:8px;border:0;background:#4c7dff;color:#fff;cursor:pointer}
 #log{margin-top:16px;font-family:ui-monospace,monospace;font-size:12px;color:#8b93a7;white-space:pre-wrap;max-height:240px;overflow:auto}
</style>
<div class="wrap">
  <div id="stage"></div>
  <div class="row">
    <input id="text" placeholder="说点什么，统一认知来决定它怎么回…" autocomplete="off">
    <button id="send">说</button>
  </div>
  <div id="log"></div>
</div>
<script>
const log = (m) => { const el=document.getElementById('log'); el.textContent += m + "\\n"; el.scrollTop=el.scrollHeight; };
async function start() {
  const cfg = await (await fetch('/session')).json();
  log(`频道 ${cfg.channel}，uid=${cfg.uid}`);
  const client = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
  client.on('user-published', async (user, kind) => {
    await client.subscribe(user, kind);
    log(`订阅到 ${user.uid} 的 ${kind}`);
    if (kind === 'video') user.videoTrack.play('stage');
    if (kind === 'audio') user.audioTrack.play();
  });
  await client.join(cfg.appId, cfg.channel, cfg.token, cfg.uid);
  log('已加入频道，等待数字人推流…');
  poll();
}
async function poll() {
  try {
    const r = await fetch('/events');
    const d = await r.json();
    for (const line of d.lines) log(line);
  } catch (e) {}
  setTimeout(poll, 1000);
}
document.getElementById('send').onclick = async () => {
  const el = document.getElementById('text');
  const text = el.value.trim();
  if (!text) return;
  el.value = '';
  log(`你 ${text}`);
  const d = await (await fetch('/say', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })).json();
  if (!d.ok) log(`  失败：${d.error}`);
};
document.getElementById('text').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('send').click();
});
start().catch(e => log('启动失败：' + e.message));
</script>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/session"):
            self._json({
                "appId": STATE["app_id"], "channel": STATE["channel"],
                "uid": STATE["viewer_uid"], "token": STATE["viewer_token"],
            })
            return
        if self.path.startswith("/events"):
            lines, STATE["log"] = STATE["log"], []
            self._json({"lines": lines})
            return
        body = PAGE.replace("__SDK__", AGORA_SDK).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/say"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        text = json.loads(self.rfile.read(length) or b"{}").get("text", "").strip()
        if not text:
            self._json({"ok": False, "error": "empty"}, 400)
            return
        if not STATE.get("ready"):
            self._json({"ok": False, "error": "数字人尚未就绪"}, 409)
            return
        # The brain answers on its own timeline; the page hears about it through
        # /events rather than blocking this request.
        asyncio.run_coroutine_threadsafe(
            STATE["body"].say_to_character(text), STATE["loop"]
        )
        self._json({"ok": True})


# ── wiring ───────────────────────────────────────────────────


async def run(args) -> None:
    STATE["loop"] = asyncio.get_running_loop()
    body = RuntimeBody(args.runtime_url, args.agent, args.body_id)
    STATE["body"] = body
    await body.connect()

    async def speak(line: str, params: dict) -> None:
        STATE["log"].append(f"角色 {line}")
        cog = params.get("cognitive_state") or {}
        rel = (cog.get("relationship") or {}).get("stage")
        STATE["log"].append(f"  情绪={cog.get('emotion')} 关系={rel}")
        stats = await asyncio.to_thread(
            stream_tts_pcm, line, args.voice, STATE["frames"].append
        )
        STATE["log"].append(f"  首帧 {stats['first_audio_ms']}ms · {stats['frames']} 帧")

    await asyncio.gather(
        body.reader(speak),
        drive_vidu(STATE["live_id"], STATE["client_secret"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar-image", default="/Users/lovelyjoy/Desktop/vtuber-1.jpg")
    parser.add_argument("--model", default="vidu-s2", choices=["vidu-s1", "vidu-s2"])
    parser.add_argument("--runtime-url", default=os.environ.get("CHARACTER_RUNTIME_URL", "ws://127.0.0.1:8765"))
    parser.add_argument("--agent", default=os.environ.get("CHARACTER_RUNTIME_AGENT", "joi"))
    parser.add_argument("--body-id", default="vidu")
    parser.add_argument("--ai-core-url", default=os.environ.get("SOULFORGE_AI_CORE_URL", "http://127.0.0.1:8100"))
    parser.add_argument("--voice", default=None)
    parser.add_argument("--port", type=int, default=28892)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--vidu-uid", type=int, default=1001)
    parser.add_argument("--viewer-uid", type=int, default=2002)
    args = parser.parse_args()

    if not os.environ.get("VIDU_API_KEY"):
        print("VIDU_API_KEY 未设置", file=sys.stderr)
        return 2

    STATE.update({
        "vidu_key": os.environ["VIDU_API_KEY"],
        "app_id": os.environ["AGORA_APP_ID"],
        "channel": f"sf{int(time.time())}",
        "viewer_uid": args.viewer_uid,
        "frames": deque(),
        "log": [],
        "ready": False,
        "ai_core_url": args.ai_core_url,
        "service_token": os.environ.get("SERVICE_TOKEN", ""),
    })
    STATE["viewer_token"] = mint_token(STATE["channel"], args.viewer_uid, publisher=False)
    vidu_token = mint_token(STATE["channel"], args.vidu_uid, publisher=True)

    print("创建 Vidu 会话…", flush=True)
    result = create_session(args, vidu_token)
    STATE["live_id"] = result["live"]["id"]
    STATE["client_secret"] = result["client_secret"]
    print(f"live_id    : {STATE['live_id']}", flush=True)

    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"\n  打开：http://127.0.0.1:{args.port}/\n", flush=True)

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
