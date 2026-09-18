#!/usr/bin/env python3
"""See and hear the companion: a browser client for a Vidu S2 realtime session.

Vidu ships a demo page that already does the hard part — joining the AliRTC
channel, publishing the microphone, rendering the character's video. What it does
not do is know anything about the person it is talking to.

So the page is served unmodified and this process sits in front of it as a proxy.
When the page creates a session, the request is intercepted on the way out and
SoulForge's memory is written into it: the preamble goes into ``avatar.persona``
and ``memory_retrieval`` is pointed back at ai-core. The browser never learns the
API key either — it posts a placeholder and the proxy swaps in the real one.

    VIDU_API_KEY=vda_... SERVICE_TOKEN=... \
        python scripts/vidu_web.py --user-id <uuid> \
            --public-base-url https://xxx.loca.lt

Then open the printed URL, click 创建并连接, and allow the microphone.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import socket
import ssl
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "packages",
        "ai-core",
        "src",
    ),
)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_core.api.vidu_retrieval import MEMORY_TOOL_INSTRUCTION  # noqa: E402
from ai_core.services.vidu_session_token import mint_session_token  # noqa: E402
from vidu_live import fetch_preamble  # noqa: E402

DEMO_URL = (
    "https://platform.vidu.com/live-doc/files/s2-avatar/realtime/quick-start/index.html"
)
CACHE_DIR = Path.home() / ".cache" / "soulforge" / "vidu-demo"
UPSTREAM = {"ovs": "https://api.vidu.com", "cn": "https://api.vidu.cn"}
CREATE_LIVE_PATH = "/live/s_avatar/realtime"

# The page refuses to submit an empty key, so it is given this and the proxy
# substitutes the real one. Keeps a live credential out of the browser and out of
# the URL bar.
KEY_PLACEHOLDER = "vda_soulforge_local_proxy"

# Set once in main(); the handler is instantiated per request.
CONFIG: dict = {}


def load_demo_page() -> bytes:
    """Fetch Vidu's demo page, cached. Not vendored — it is their file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "index.html"
    if cached.exists() and cached.stat().st_size > 1000:
        return patch_page(cached.read_bytes())
    print(f"下载 Vidu demo 页面 → {cached}")
    with urllib.request.urlopen(DEMO_URL, timeout=30) as resp:
        data = resp.read()
    cached.write_bytes(data)
    return patch_page(data)


# The demo publishes your own camera in video mode and treats any failure as
# fatal — it rethrows, which tears down the channel and the WebSocket with it.
# On a machine where Chrome cannot open the camera the session dies before the
# character ever appears.
#
# Subscribing to the character's video is set up earlier and separately
# (setDefaultSubscribeAllRemoteVideoStreams), so the local camera is not needed
# to see anything. Talking to a companion should not require pointing a camera
# at yourself, so the rethrow is removed: warn, then carry on to audio.
_CAMERA_FATAL = b"""            showMediaNotice("camera", error);
            throw error;"""
_CAMERA_SOFT = b"""            showMediaNotice("camera", error);
            console.warn("[soulforge] no local camera; continuing audio-only");"""


def patch_page(html: bytes) -> bytes:
    if _CAMERA_FATAL not in html:
        # Upstream changed shape: better a loud warning than a silently
        # un-patched page that dies on the next machine without a webcam.
        print(
            "warning: 摄像头补丁没匹配上，demo 页面可能已更新——"
            "没有摄像头的机器会连不上",
            file=sys.stderr,
        )
        return html
    return html.replace(_CAMERA_FATAL, _CAMERA_SOFT)


def inject_memory(body: bytes) -> bytes:
    """Rewrite a CreateLive body so the character starts out knowing the user.

    Everything SoulForge-specific lives here rather than in the page, so the page
    stays a stock vendor demo and the memory never travels through the browser or
    the URL.
    """
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return body

    avatar = payload.setdefault("avatar", {})

    # persona_enhance rewrites and expands the persona on Vidu's side, which
    # means it rewrites the memory block and the "不要编造" line with it. A first
    # live run with it on opened in English despite a Chinese persona. Memory
    # fidelity beats prompt polish, so it is forced off unless asked for.
    if avatar.pop("persona_enhance", False) and not CONFIG.get("allow_persona_enhance"):
        print("  → 关掉 persona_enhance（它会重写注入的记忆）", flush=True)

    preamble = CONFIG.get("preamble", "")
    persona = (avatar.get("persona") or "").strip()
    parts = [p for p in (preamble, persona, CONFIG.get("language_line", "")) if p]
    if parts:
        avatar["persona"] = "\n\n".join(parts)

    payload["memory_retrieval"] = {
        "enabled": True,
        "provider": "self",
        "endpoint": f"{CONFIG['public_base_url'].rstrip('/')}/vidu/memory/retrieve",
        "authorization": f"Bearer {CONFIG['session_token']}",
        "timeout_ms": CONFIG["memory_timeout_ms"],
        "tool_instruction": MEMORY_TOOL_INSTRUCTION,
    }
    payload.setdefault("audio", {})["enable_transcription"] = True

    facts = preamble.count("\n- ")
    print(f"  → 已注入记忆（{facts} 条）与 memory_retrieval 回调", flush=True)
    return json.dumps(payload).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 - quieter than the default
        if CONFIG.get("verbose"):
            super().log_message(fmt, *args)

    # ── routing ────────────────────────────────────────────────

    def do_GET(self):
        if self._is_websocket_upgrade():
            self._tunnel_websocket()
            return
        route = self._route()
        if route:
            self._proxy_http(route)
            return
        self._serve_page()

    def do_POST(self):
        self._proxy_or_404()

    def do_PUT(self):
        self._proxy_or_404()

    def do_DELETE(self):
        self._proxy_or_404()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _proxy_or_404(self):
        route = self._route()
        if route:
            self._proxy_http(route)
        else:
            self.send_error(404)

    def _route(self) -> tuple[str, str, str] | None:
        """Split /proxy/{env}/rest?query into (upstream, path, query)."""
        parsed = urllib.parse.urlsplit(self.path)
        parts = parsed.path.split("/", 3)
        if len(parts) < 4 or parts[1] != "proxy" or parts[2] not in UPSTREAM:
            return None
        return UPSTREAM[parts[2]], f"/{parts[3]}", parsed.query

    def _is_websocket_upgrade(self) -> bool:
        return "websocket" in self.headers.get("Upgrade", "").lower()

    # ── static ─────────────────────────────────────────────────

    def _serve_page(self):
        body = CONFIG["page"]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── HTTP proxy ─────────────────────────────────────────────

    def _proxy_http(self, route):
        upstream, path, query = route
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        if path == CREATE_LIVE_PATH and body:
            print("创建会话…", flush=True)
            body = inject_memory(body)

        target = f"{upstream}{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(target, data=body or None, method=self.command)
        req.add_header("Authorization", f"Token {CONFIG['api_key']}")
        req.add_header(
            "Content-Type", self.headers.get("Content-Type", "application/json")
        )
        req.add_header("Accept", "*/*")

        try:
            with urllib.request.urlopen(req, timeout=200) as resp:
                status, payload, ctype = (
                    resp.status,
                    resp.read(),
                    resp.headers.get("Content-Type"),
                )
        except urllib.error.HTTPError as exc:
            status, payload, ctype = (
                exc.code,
                exc.read(),
                exc.headers.get("Content-Type"),
            )
        except Exception as exc:  # noqa: BLE001 - surface upstream trouble to the page
            status, payload, ctype = (
                502,
                json.dumps({"error": str(exc)}).encode(),
                "application/json",
            )

        if path == CREATE_LIVE_PATH:
            print(f"  ← {status}", flush=True)

        self.send_response(status)
        self.send_header("Content-Type", ctype or "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    # ── WebSocket tunnel ───────────────────────────────────────

    def _tunnel_websocket(self):
        """Hand the socket over to Vidu, adding the auth header the browser can't."""
        route = self._route()
        if not route:
            self.send_error(404)
            return
        upstream, path, query = route

        # The page passes the key as a query param because a browser WebSocket
        # cannot set headers; upstream wants a header, so move it.
        params = urllib.parse.parse_qsl(query, keep_blank_values=True)
        params = [(k, v) for k, v in params if k != "authorization"]
        query = urllib.parse.urlencode(params)

        host = urllib.parse.urlsplit(upstream).hostname
        try:
            raw = socket.create_connection((host, 443), timeout=30)
            sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        except Exception as exc:  # noqa: BLE001
            self.send_error(502, f"upstream connect failed: {exc}")
            return

        target = path + (f"?{query}" if query else "")
        handshake = [
            f"GET {target} HTTP/1.1",
            f"Host: {host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Authorization: Token {CONFIG['api_key']}",
        ]
        for header in (
            "Sec-WebSocket-Key",
            "Sec-WebSocket-Version",
            "Sec-WebSocket-Protocol",
        ):
            if self.headers.get(header):
                handshake.append(f"{header}: {self.headers[header]}")
        sock.sendall(("\r\n".join(handshake) + "\r\n\r\n").encode())

        # Relay the upstream's 101 verbatim so the browser completes its own
        # handshake against the real Sec-WebSocket-Accept.
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                self.send_error(502, "upstream closed during handshake")
                sock.close()
                return
            response += chunk
        head, _, rest = response.partition(b"\r\n\r\n")
        self.connection.sendall(head + b"\r\n\r\n")
        if rest:
            self.connection.sendall(rest)

        self._pump(self.connection, sock)

    @staticmethod
    def _pump(a: socket.socket, b: socket.socket) -> None:
        """Copy bytes both ways until either side hangs up."""
        socks = [a, b]
        try:
            while True:
                readable, _, errored = select.select(socks, [], socks, 300)
                if errored or not readable:
                    return
                for src in readable:
                    dst = b if src is a else a
                    data = src.recv(65536)
                    if not data:
                        return
                    dst.sendall(data)
        except OSError:
            return
        finally:
            for s in socks:
                try:
                    s.close()
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="SoulForge end user uuid")
    parser.add_argument("--character-id", default=None)
    parser.add_argument(
        "--public-base-url",
        default=os.environ.get("SOULFORGE_PUBLIC_BASE_URL", ""),
        help="Public base URL of ai-core, reachable by Vidu",
    )
    parser.add_argument(
        "--ai-core-url",
        default=os.environ.get("SOULFORGE_AI_CORE_URL", "http://127.0.0.1:8100"),
    )
    parser.add_argument("--port", type=int, default=28890)
    parser.add_argument("--memory-timeout-ms", type=int, default=5000)
    parser.add_argument("--preamble-limit", type=int, default=6)
    parser.add_argument(
        "--avatar-image",
        default="https://scene.vidu.zone/media-asset/084945-xpk47RWYcBgJ27nJ.png",
    )
    parser.add_argument(
        "--persona", default="你是用户的长期陪伴角色。说话克制、口语化、允许留白。"
    )
    parser.add_argument(
        "--voice", default="Maia", help="Vidu voice id, see the Voice List doc"
    )
    parser.add_argument(
        "--language",
        default="请始终用中文对话，包括第一句开场白。",
        help="Appended to the persona; set empty to let the model choose",
    )
    parser.add_argument(
        "--allow-persona-enhance",
        action="store_true",
        help="Let Vidu rewrite the persona (it will rewrite the injected memory too)",
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("VIDU_API_KEY", "")
    if not api_key:
        print("VIDU_API_KEY is not set", file=sys.stderr)
        return 2
    if not args.public_base_url:
        parser.error("--public-base-url (or SOULFORGE_PUBLIC_BASE_URL) is required")

    preamble = ""
    service_token = os.environ.get("SERVICE_TOKEN", "")
    if service_token:
        # fetch_preamble already reports the counts, withheld ones included.
        preamble = fetch_preamble(args.ai_core_url, service_token, args)
    else:
        print(
            "warning: SERVICE_TOKEN not set — the character will know nothing",
            file=sys.stderr,
        )

    CONFIG.update(
        {
            "api_key": api_key,
            "preamble": preamble,
            "language_line": args.language,
            "allow_persona_enhance": args.allow_persona_enhance,
            "public_base_url": args.public_base_url,
            "memory_timeout_ms": args.memory_timeout_ms,
            "session_token": mint_session_token(
                end_user_id=args.user_id, character_id=args.character_id
            ),
            "page": load_demo_page(),
            "verbose": args.verbose,
        }
    )

    query = urllib.parse.urlencode(
        {
            "env": "ovs",
            "api_key": KEY_PLACEHOLDER,
            "call_mode": "video",
            "avatar_image_uri": args.avatar_image,
            # Only the base persona — the memories are injected server-side so
            # they never appear in the URL or the browser's history.
            "avatar_persona": args.persona,
            # The page ships "甜甜 Tina" in these two fields; left alone the
            # character introduces itself as someone else entirely.
            "avatar_name": "",
            "avatar_voice": args.voice,
        }
    )
    url = f"http://127.0.0.1:{args.port}/?{query}"

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True

    print()
    print(f"  打开：{url}")
    print("  页面上点「创建并连接」，允许麦克风（摄像头可以拒绝）。")
    print("  建会话约 1 分钟。Ctrl-C 关掉这个服务器。")
    print()
    if preamble:
        print("  角色开场会知道：")
        for line in preamble.splitlines():
            print(f"    {line}")
        print()

    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
