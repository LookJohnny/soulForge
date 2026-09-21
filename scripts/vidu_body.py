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
import socket
import ssl
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
SDK_CACHE = Path.home() / ".cache" / "soulforge" / Path(AGORA_SDK).name


def load_sdk() -> bytes:
    """Serve the RTC SDK ourselves; the page must not need the open internet.

    A phone or laptop on the same wifi may have no working route to
    download.agora.io. A blocking <script> to a host it cannot reach leaves the
    browser on a white page with no error — indistinguishable from the server
    being down, which is how an afternoon gets spent on the wrong problem.
    """
    if SDK_CACHE.exists() and SDK_CACHE.stat().st_size > 100_000:
        return SDK_CACHE.read_bytes()
    with urllib.request.urlopen(AGORA_SDK, timeout=120) as resp:
        data = resp.read()
    SDK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SDK_CACHE.write_bytes(data)
    return data

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
        await self.ws.send(
            json.dumps(
                {
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
                },
                ensure_ascii=False,
            )
        )
        welcome = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=20))
        accepted = welcome.get("accepted_agents") or []
        if self.agent_id not in accepted:
            raise RuntimeError(
                f"Runtime 未接受 agent {self.agent_id}；可用: {accepted}"
            )
        print(f"已作为身体接入 Runtime（agent={self.agent_id}）", flush=True)

    async def say_to_character(self, text: str) -> str:
        """Send one utterance, return the dialogue the brain decided on."""
        event_id = uuid.uuid4().hex[:12]
        await self.ws.send(
            json.dumps(
                {
                    "type": "event",
                    "kind": "user_utterance",
                    "source": self.body_id,
                    "text": text,
                    "target_agent": self.agent_id,
                    "payload": {"event_id": event_id},
                },
                ensure_ascii=False,
            )
        )
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
            # dialogue is a top-level field of ActionCommand; only cognitive_state
            # and the rest of the decision ride in params. Reading it from params
            # silently acknowledged every line and the body never spoke.
            line = msg.get("dialogue")
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
        await self.ws.send(
            json.dumps(
                {
                    "type": "observation",
                    "command_id": command_id,
                    "agent_id": self.agent_id,
                    "status": status,
                    "error": error,
                },
                ensure_ascii=False,
            )
        )


# ── mouth: TTS → PCM → Vidu ──────────────────────────────────


def stream_tts_pcm(text: str, voice: str | None, sink) -> dict:
    body = json.dumps(
        {"text": text, "voice": voice} if voice else {"text": text}
    ).encode()
    req = urllib.request.Request(
        f"{STATE['ai_core_url'].rstrip('/')}/tts/stream",
        data=body,
        headers={
            "X-Service-Token": STATE["service_token"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    ff = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "pipe:1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
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


def _image_mime(raw: bytes, path: Path) -> str:
    """Decide the media type from the bytes, not the file name.

    Generated art often lands with the wrong extension — the avatar chosen here
    was saved as .png but is JPEG. Vidu rejects a data URI whose declared type
    disagrees with its payload, and the error does not say so.
    """
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    raise ValueError(f"不支持的图片格式: {path.name}")


def create_session(args, vidu_token: str) -> dict:
    avatar = args.avatar_image
    if avatar and not avatar.startswith(("http://", "https://", "data:")):
        raw = Path(avatar).expanduser().read_bytes()
        mime = _image_mime(raw, Path(avatar))
        avatar = f"data:image/{mime};base64," + base64.b64encode(raw).decode()

    body = json.dumps(
        {
            "model": args.model,
            "image_uri": avatar,
            "rtc_info": {
                "provider": "agora",
                "app_id": STATE["app_id"],
                "channel_id": STATE["channel"],
                "user_id": str(args.vidu_uid),
                "token": vidu_token,
            },
        }
    ).encode()
    req = urllib.request.Request(
        f"{VIDU_HOST}/live/s_avatar/component",
        data=body,
        headers={
            "Authorization": f"Token {STATE['vidu_key']}",
            "Content-Type": "application/json",
        },
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
            await ws.send(
                json.dumps(
                    {
                        "type": 1,
                        "live_id": str(live_id),
                        "conn_id": conn,
                        "seq_id": seq[0],
                        "payload": {"conn_init": {"version": 1}},
                    }
                )
            )

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
                print(
                    "← Vidu 挂断:",
                    json.dumps(msg.get("payload"), ensure_ascii=False),
                    flush=True,
                )
                if pump_task:
                    pump_task.cancel()
                return


# ── browser ──────────────────────────────────────────────────

PAGE = """<!doctype html>
<meta charset="utf-8"><title>SoulForge 身体 × Vidu</title>
<script src="/agora.js" defer></script>
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
// The SDK is deferred so the page paints first: a failure here must show up as
// a line in the log, never as a white screen.
window.addEventListener('DOMContentLoaded', () => {
  if (typeof AgoraRTC === 'undefined') {
    log('RTC SDK 没加载出来，页面已经打开但看不到人。刷新试试。');
    return;
  }
  start().catch(e => log('启动失败：' + e.message));
});
</script>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # /events polls once a second, so the default access log is noise. But
        # without any log there is no way to tell "the request never arrived"
        # from "it arrived and the response was wrong" — which is exactly the
        # question when a page loads on one machine and not another.
        #
        # getattr, not self.path: on a malformed request line `path` was never
        # assigned, and an AttributeError in here escapes through send_error and
        # kills the connection thread before the client is told anything.
        if "/events" in (getattr(self, "path", "") or ""):
            return
        print(f"[http] {self.client_address[0]} {fmt % args}", flush=True)

    def handle_one_request(self):
        """Name what a garbled request line actually was.

        A browser that decided to speak TLS to a plaintext port produces an
        unparseable request line and nothing else; without this the server just
        logs a stack trace and the page looks unreachable.
        """
        try:
            super().handle_one_request()
        except ValueError:
            raw = getattr(self, "raw_requestline", b"")[:24]
            who = self.client_address[0]
            if raw[:1] == b"\x16":
                print(
                    f"[http] {who} 发来的是 TLS 握手——浏览器在用 https 访问，"
                    f"这个端口只说 http。请明确输入 http://",
                    flush=True,
                )
            else:
                print(f"[http] {who} 请求行无法解析：{raw!r}", flush=True)
            self.close_connection = True

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/session"):
            self._json(
                {
                    "appId": STATE["app_id"],
                    "channel": STATE["channel"],
                    "uid": STATE["viewer_uid"],
                    "token": STATE["viewer_token"],
                }
            )
            return
        if self.path.startswith("/events"):
            lines, STATE["log"] = STATE["log"], []
            self._json({"lines": lines})
            return
        if self.path.startswith("/agora.js"):
            sdk = STATE["sdk"]
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(sdk)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(sdk)
            return
        body = PAGE.encode()
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


# ── one port, either protocol ────────────────────────────────

LAN_CERT = Path.home() / ".cache" / "soulforge" / "lan-cert.pem"
LAN_KEY = Path.home() / ".cache" / "soulforge" / "lan-key.pem"


def local_ips() -> list[str]:
    """Every IPv4 this machine answers on.

    A Mac with both ethernet and wifi sits on two subnets, and the one the
    phone can reach is not always the one `ipconfig getifaddr en0` prints.
    """
    ips = {"127.0.0.1"}
    for iface in ("en0", "en1", "en2", "en3"):
        try:
            out = subprocess.run(
                ["ipconfig", "getifaddr", iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        addr = out.stdout.strip()
        if addr:
            ips.add(addr)
    return sorted(ips)


def lan_tls_context(bind_ips: list[str]) -> ssl.SSLContext | None:
    """A self-signed context for this machine's addresses, or None."""
    if not (LAN_CERT.exists() and LAN_KEY.exists()):
        sans = ",".join(f"IP:{ip}" for ip in bind_ips)
        LAN_CERT.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-days", "825", "-subj", "/CN=soulforge-lan",
                    "-addext", f"subjectAltName={sans},DNS:localhost",
                    "-keyout", str(LAN_KEY), "-out", str(LAN_CERT),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ctx.load_cert_chain(str(LAN_CERT), str(LAN_KEY))
    except (OSError, ssl.SSLError):
        return None
    return ctx


class DualProtocolServer(ThreadingHTTPServer):
    """Answer http and https on the same port.

    Browsers decide on their own whether a bare `host:port` means http or
    https, and a phone or laptop that picks https gets nothing back from a
    plaintext port — no error the user can act on, just a page that will not
    load. Peeking at the first byte costs nothing and removes the guess: 0x16
    is a TLS handshake, anything else is a request line.
    """

    tls: ssl.SSLContext | None = None

    def get_request(self):
        sock, addr = super().get_request()
        if self.tls is None:
            return sock, addr
        try:
            sock.settimeout(10)
            first = sock.recv(1, socket.MSG_PEEK)
        except OSError:
            return sock, addr
        finally:
            sock.settimeout(None)
        if first == b"\x16":
            print(f"[http] {addr[0]} 用 https 进来，已用自签证书接住", flush=True)
            return self.tls.wrap_socket(sock, server_side=True), addr
        return sock, addr

    def handle_error(self, request, client_address):
        # A refused certificate is the user clicking "go back", not a crash.
        exc = sys.exception()
        if isinstance(exc, ssl.SSLError):
            print(f"[http] {client_address[0]} TLS 握手未完成：{exc.reason}", flush=True)
            return
        super().handle_error(request, client_address)


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
        if not STATE["live_id"]:
            STATE["log"].append("  （dry-run：跳过语音合成）")
            return
        stats = await asyncio.to_thread(
            stream_tts_pcm, line, args.voice, STATE["frames"].append
        )
        STATE["log"].append(
            f"  首帧 {stats['first_audio_ms']}ms · {stats['frames']} 帧"
        )

    tasks = [body.reader(speak)]
    if STATE["live_id"]:
        tasks.append(drive_vidu(STATE["live_id"], STATE["client_secret"]))
    await asyncio.gather(*tasks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--avatar-image", default="/Users/lovelyjoy/Desktop/sf-idol-1.png"
    )
    parser.add_argument("--model", default="vidu-s2", choices=["vidu-s1", "vidu-s2"])
    parser.add_argument(
        "--runtime-url",
        default=os.environ.get("CHARACTER_RUNTIME_URL", "ws://127.0.0.1:8765"),
    )
    parser.add_argument(
        "--agent", default=os.environ.get("CHARACTER_RUNTIME_AGENT", "joi")
    )
    parser.add_argument("--body-id", default="vidu")
    parser.add_argument(
        "--ai-core-url",
        default=os.environ.get("SOULFORGE_AI_CORE_URL", "http://127.0.0.1:8100"),
    )
    parser.add_argument("--voice", default=None)
    parser.add_argument("--port", type=int, default=28892)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--vidu-uid", type=int, default=1001)
    parser.add_argument("--viewer-uid", type=int, default=2002)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只起网页与 Runtime 身体，不建 Vidu 会话（不计费，用于排查网络）",
    )
    args = parser.parse_args()

    if not os.environ.get("VIDU_API_KEY"):
        print("VIDU_API_KEY 未设置", file=sys.stderr)
        return 2

    STATE.update(
        {
            "vidu_key": os.environ["VIDU_API_KEY"],
            "app_id": os.environ["AGORA_APP_ID"],
            "channel": f"sf{int(time.time())}",
            "viewer_uid": args.viewer_uid,
            "frames": deque(),
            "log": [],
            "ready": False,
            "ai_core_url": args.ai_core_url,
            "service_token": os.environ.get("SERVICE_TOKEN", ""),
        }
    )
    STATE["viewer_token"] = mint_token(
        STATE["channel"], args.viewer_uid, publisher=False
    )
    vidu_token = mint_token(STATE["channel"], args.vidu_uid, publisher=True)

    STATE["sdk"] = load_sdk()
    print(f"RTC SDK 本地就绪（{len(STATE['sdk']) // 1024} KB）", flush=True)

    # Serve before creating the session: uploading the avatar takes seconds, and
    # a browser that knocks during that window gets connection refused, which
    # looks exactly like the server never started.
    server = DualProtocolServer((args.bind, args.port), Handler)
    server.tls = lan_tls_context(local_ips())
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("", flush=True)
    for ip in local_ips():
        print(f"  打开：http://{ip}:{args.port}/", flush=True)
    if server.tls is not None:
        print("  （同一端口也接受 https，用的是自签证书，浏览器会先警告）", flush=True)
    print("", flush=True)

    if args.dry_run:
        # Vidu bills per second from conn_init, so anything that is not about the
        # avatar itself — page reachability, Runtime wiring — is debugged free.
        STATE["live_id"] = STATE["client_secret"] = ""
        STATE["ready"] = True
        print("dry-run：不创建 Vidu 会话，不计费", flush=True)
    else:
        print("创建 Vidu 会话…", flush=True)
        result = create_session(args, vidu_token)
        STATE["live_id"] = result["live"]["id"]
        STATE["client_secret"] = result["client_secret"]
        print(f"live_id    : {STATE['live_id']}", flush=True)

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
