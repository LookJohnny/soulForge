#!/usr/bin/env python3
"""Vidu component edition: SoulForge drives the voice, Vidu only renders the face.

Unlike the realtime edition, nothing here hands the conversation to Vidu. We open
its WebSocket, push PCM we produced ourselves, and it returns a talking head into
an Agora channel the browser watches. The brain stays on our side.

    AGORA_APP_ID=... AGORA_APP_CERTIFICATE=... VIDU_API_KEY=vda_... \
        python scripts/vidu_component.py --avatar-image ~/Desktop/vtuber-1.jpg

Open the printed URL, then type a line — ai-core's TTS speaks it through the
avatar. Billing is per second of session, so it hangs up when you stop it.
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

# 24kHz mono s16le, 20ms per frame — the cadence Vidu documents.
SAMPLE_RATE = 24000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000  # 960

STATE: dict = {}


# ── audio ────────────────────────────────────────────────────


def stream_tts_pcm(
    text: str, ai_core_url: str, service_token: str, voice: str | None, sink
) -> dict:
    """Synthesize and hand PCM to ``sink`` as it is produced, not at the end.

    Waiting for the full clip is what made the avatar sit still: one 6.8s
    sentence took 16.7s to synthesize, so the face did nothing for 16.7s. Fish
    emits progressive MP3, and ffmpeg decodes a pipe as it fills, so the first
    frames can reach Vidu while the rest is still being generated.
    """
    body = json.dumps({"text": text, "voice": voice} if voice else {"text": text}).encode()
    req = urllib.request.Request(
        f"{ai_core_url.rstrip('/')}/tts/stream",
        data=body,
        headers={"X-Service-Token": service_token, "Content-Type": "application/json"},
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
        """Forward decoded PCM the moment ffmpeg emits it."""
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
        suffix = Path(avatar).suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}[suffix]
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


async def drive(live_id: str, secret: str) -> None:
    """Hold the WebSocket open, keep the character fed, speak what is queued."""
    conn = f"sf-{int(time.time())}"
    url = f"{VIDU_WS}/live/v1/external-lives/{live_id}/stream?conn_id={conn}&client_secret={secret}"
    seq = [0]

    async with websockets.connect(url, proxy=None) as ws:
        STATE["ws"] = ws

        async def conn_init():
            seq[0] += 1
            await ws.send(json.dumps({
                "type": 1, "live_id": str(live_id), "conn_id": conn,
                "seq_id": seq[0], "payload": {"conn_init": {"version": 1}},
            }))

        await conn_init()

        async def pump():
            """Send one 20ms frame every 20ms — speech when there is some, else silence.

            The character needs a continuous 24kHz feed; a gap reads as the audio
            having stopped rather than as a pause. Frames arrive from the TTS
            decoder thread while synthesis is still running, so speech starts as
            soon as the first frame lands instead of after the whole sentence.
            """
            silence = b"\x00" * FRAME_BYTES
            while True:
                frame = STATE["frames"].popleft() if STATE["frames"] else silence
                await ws.send(frame)
                await asyncio.sleep(FRAME_MS / 1000)

        pump_task = None
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            t = msg.get("type")
            if t == 2:
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
            elif t == 6:
                print("← 对方挂断:", json.dumps(msg.get("payload"), ensure_ascii=False), flush=True)
                if pump_task:
                    pump_task.cancel()
                return
            elif t in (9, 10):
                for holder in msg.get("payload", {}).values():
                    if isinstance(holder, dict) and holder.get("content"):
                        print(f"[{'用户' if t == 9 else '角色'}] {holder['content']}", flush=True)


# ── browser side ─────────────────────────────────────────────

PAGE = """<!doctype html>
<meta charset="utf-8"><title>SoulForge × Vidu 组件版</title>
<script src="__SDK__"></script>
<style>
 body{margin:0;font:14px -apple-system,system-ui,sans-serif;background:#0f1115;color:#e6e6e6}
 .wrap{max-width:760px;margin:0 auto;padding:24px}
 #stage{width:100%;aspect-ratio:3/4;max-height:70vh;background:#181b22;border-radius:12px;overflow:hidden}
 .row{display:flex;gap:8px;margin-top:16px}
 input{flex:1;padding:10px 12px;border-radius:8px;border:1px solid #2c313c;background:#161920;color:#e6e6e6}
 button{padding:10px 18px;border-radius:8px;border:0;background:#4c7dff;color:#fff;cursor:pointer}
 button:disabled{opacity:.5;cursor:default}
 #log{margin-top:16px;font-family:ui-monospace,monospace;font-size:12px;color:#8b93a7;white-space:pre-wrap;max-height:220px;overflow:auto}
</style>
<div class="wrap">
  <div id="stage"></div>
  <div class="row">
    <input id="text" placeholder="说点什么，数字人会念出来…" autocomplete="off">
    <button id="send">说</button>
  </div>
  <div id="log"></div>
</div>
<script>
const log = (m) => { document.getElementById('log').textContent += m + "\\n"; };
let client;

async function start() {
  const cfg = await (await fetch('/session')).json();
  log(`频道 ${cfg.channel}，以 uid=${cfg.uid} 加入`);
  client = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });

  client.on('user-published', async (user, mediaType) => {
    await client.subscribe(user, mediaType);
    log(`订阅到 ${user.uid} 的 ${mediaType}`);
    if (mediaType === 'video') user.videoTrack.play('stage');
    if (mediaType === 'audio') user.audioTrack.play();
  });
  client.on('user-unpublished', (u, t) => log(`${u.uid} 停止了 ${t}`));

  await client.join(cfg.appId, cfg.channel, cfg.token, cfg.uid);
  log('已加入频道，等待数字人推流…');
}

document.getElementById('send').onclick = async () => {
  const el = document.getElementById('text');
  const text = el.value.trim();
  if (!text) return;
  el.value = '';
  log(`→ ${text}`);
  const r = await fetch('/say', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  const d = await r.json();
  log(d.ok ? `  首帧 ${d.first_audio_ms}ms · 全部 ${d.total_ms}ms · ${d.frames} 帧` : `  失败：${d.error}`);
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
                "appId": STATE["app_id"],
                "channel": STATE["channel"],
                "uid": STATE["viewer_uid"],
                "token": STATE["viewer_token"],
            })
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
        try:
            stats = stream_tts_pcm(
                text,
                STATE["ai_core_url"],
                STATE["service_token"],
                STATE["voice"],
                STATE["frames"].append,
            )
        except Exception as exc:  # noqa: BLE001 - report to the page, keep serving
            self._json({"ok": False, "error": str(exc)[:200]}, 500)
            return
        print(
            f"[TTS] 首帧 {stats['first_audio_ms']}ms，全部 {stats['total_ms']}ms，"
            f"{stats['frames']} 帧",
            flush=True,
        )
        self._json({"ok": True, **stats})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar-image", default="/Users/lovelyjoy/Desktop/vtuber-1.jpg")
    parser.add_argument("--model", default="vidu-s2", choices=["vidu-s1", "vidu-s2"])
    parser.add_argument("--port", type=int, default=28891)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--vidu-uid", type=int, default=1001)
    parser.add_argument("--viewer-uid", type=int, default=2002)
    parser.add_argument("--voice", default=None)
    parser.add_argument(
        "--ai-core-url", default=os.environ.get("SOULFORGE_AI_CORE_URL", "http://127.0.0.1:8100")
    )
    args = parser.parse_args()

    vidu_key = os.environ.get("VIDU_API_KEY", "")
    if not vidu_key:
        print("VIDU_API_KEY 未设置", file=sys.stderr)
        return 2

    STATE.update({
        "vidu_key": vidu_key,
        "app_id": os.environ["AGORA_APP_ID"],
        "channel": f"sf{int(time.time())}",
        "viewer_uid": args.viewer_uid,
        # Single producer (TTS decoder thread), single consumer (pump) — deque
        # append/popleft are atomic, so no lock is needed across that boundary.
        "frames": deque(),
        "ready": False,
        "ai_core_url": args.ai_core_url,
        "service_token": os.environ.get("SERVICE_TOKEN", ""),
        "voice": args.voice,
    })
    STATE["viewer_token"] = mint_token(STATE["channel"], args.viewer_uid, publisher=False)
    vidu_token = mint_token(STATE["channel"], args.vidu_uid, publisher=True)

    print(f"频道       : {STATE['channel']}")
    print("创建组件版会话…", flush=True)
    result = create_session(args, vidu_token)
    live_id = result["live"]["id"]
    print(f"live_id    : {live_id}", flush=True)

    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"\n  打开：http://127.0.0.1:{args.port}/\n", flush=True)

    try:
        asyncio.run(drive(live_id, result["client_secret"]))
    except KeyboardInterrupt:
        pass
    finally:
        req = urllib.request.Request(
            f"{VIDU_HOST}/live/v1/lives/{live_id}",
            headers={"Authorization": f"Token {vidu_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                live = json.loads(r.read())["live"]
            print(f"\n本次 {live.get('billed_seconds')}s，{live.get('credits_cost')} credits")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
