"""SoulForge Studio — 人格 × 音色 × VTuber 模型自由组合的对话工作台。

The studio is a thin shell around the ONE Character Runtime: every reply comes
from CompanionRuntime + SafeDecisionLLM (real LLM when DEEPSEEK/OPENAI key is
configured, deterministic mock otherwise — the UI shows which). Voice and model
are body-level cosmetics; persona/memory live in the brain, so swapping model
or voice keeps the relationship state (that IS the one-brain-many-bodies pitch).

Run:  uv run python studio/server.py --port 8899
Open: http://127.0.0.1:8899
"""

from __future__ import annotations

import argparse
import base64
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from engine.planner import (  # noqa: E402
    CompanionRuntime,
    Event,
    EventKind,
    Persona,
    WorldState,
    load_characters,
    load_personas,
)
from engine.planner.llm_interface import SafeDecisionLLM, build_llm  # noqa: E402
from engine.planner.memory_store import InMemoryMemoryStore  # noqa: E402

STUDIO_WEB = Path(__file__).parent / "web"

EDGE_VOICE_CATALOG = [
    {"id": "zh-CN-XiaoxiaoNeural", "label": "晓晓 · 温暖女声"},
    {"id": "zh-CN-XiaoyiNeural", "label": "晓伊 · 活泼女声"},
    {"id": "zh-CN-YunxiNeural", "label": "云希 · 自然男声"},
    {"id": "zh-CN-YunyangNeural", "label": "云扬 · 播报男声"},
    {"id": "zh-CN-YunjianNeural", "label": "云健 · 低沉男声"},
    {"id": "zh-CN-YunxiaNeural", "label": "云夏 · 少年音"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "label": "晓北 · 东北女声"},
    {"id": "zh-TW-HsiaoChenNeural", "label": "曉臻 · 台湾女声"},
]


def load_dotenv_key(name: str) -> str:
    import os

    if os.environ.get(name):
        return os.environ[name]
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text("utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


AI_CORE_URL = (load_dotenv_key("AI_CORE_URL") or "http://127.0.0.1:8100").rstrip("/")
# Gateway WS the /live page connects to when the URL carries no ?gateway= (the
# desktop shell relies on this; 8080 is often taken by something else locally).
GATEWAY_WS_URL = load_dotenv_key("GATEWAY_WS_URL") or (
    f"ws://127.0.0.1:{load_dotenv_key('GATEWAY_PORT') or '8080'}/ws"
)
RUNTIME_WS_URL = load_dotenv_key(
    "RUNTIME_WS_URL"
)  # e.g. ws://127.0.0.1:8765/body (optional)
AI_CORE_TOKEN = load_dotenv_key("SERVICE_TOKEN")
FISH_KEY = load_dotenv_key("FISH_AUDIO_API_KEY")
FISH_MODEL = load_dotenv_key("FISH_AUDIO_MODEL") or "s1"


class StudioBrain:
    """One CompanionRuntime per agent; persona edits rebuild the runtime but
    the MemoryStore survives — the character remembers you across换装."""

    def __init__(self) -> None:
        self.stores: dict[str, InMemoryMemoryStore] = {}
        self.runtimes: dict[str, CompanionRuntime] = {}
        self.fingerprints: dict[str, str] = {}
        self.captured: dict[str, list] = {}
        self.sim_minute: float = 20 * 60 + 30
        inner = build_llm()
        self.llm = SafeDecisionLLM(inner, timeout_s=20.0)
        self.llm_kind = type(inner).__name__

    def _persona(self, agent_id: str, overrides: dict) -> Persona:
        base = next((p for p in load_personas() if p.agent_id == agent_id), None)
        if base is None:
            base = Persona(
                agent_id,
                overrides.get("name", agent_id.title()),
                overrides.get("archetype", "default"),
            )
        persona = Persona(
            agent_id=base.agent_id,
            name=overrides.get("name") or base.name,
            archetype=overrides.get("archetype") or base.archetype,
            traits=overrides.get("traits") or list(base.traits),
            voice=base.voice,
            energy=float(overrides.get("energy", base.energy)),
            relationships=dict(base.relationships),
            daily_goals=overrides.get("daily_goals") or list(base.daily_goals),
            meta={
                **base.meta,
                "comfort_line": overrides.get("comfort_line")
                or base.meta.get("comfort_line", ""),
            },
        )
        return persona

    def _runtime_for(self, agent_id: str, overrides: dict) -> CompanionRuntime:
        fingerprint = json.dumps(overrides, sort_keys=True, ensure_ascii=False)
        if agent_id in self.runtimes and self.fingerprints.get(agent_id) == fingerprint:
            return self.runtimes[agent_id]
        store = self.stores.setdefault(agent_id, InMemoryMemoryStore())
        persona = self._persona(agent_id, overrides)
        captured: list = []
        runtime = CompanionRuntime(
            [persona],
            WorldState(sim_minute=self.sim_minute),
            llm=self.llm,
            memory_store=store,
            adapter=lambda aid, action: captured.append(action),
        )
        self.runtimes[agent_id] = runtime
        self.fingerprints[agent_id] = fingerprint
        self.captured[agent_id] = captured
        return runtime

    def chat(self, agent_id: str, text: str, overrides: dict) -> dict:
        runtime = self._runtime_for(agent_id, overrides)
        captured = self.captured[agent_id]
        self.sim_minute += 1
        # build day/hour plans for the current minute, then isolate the
        # utterance's own actions from ambient minute steps
        runtime.tick(self.sim_minute, consume_events=False)
        captured.clear()
        runtime.handle_event_now(
            Event(
                t_min=self.sim_minute,
                kind=EventKind.USER_UTTERANCE,
                source="user",
                text=text,
                target_agent=agent_id,
            ),
            self.sim_minute,
        )
        dialogue = [a.dialogue for a in captured if a.dialogue]
        actions = [
            {
                "name": a.name,
                "correlation_id": a.correlation_id,
                "params": {
                    k: v
                    for k, v in (a.params or {}).items()
                    if isinstance(v, (str, int, float, bool))
                },
            }
            for a in captured
        ]
        decision = next(
            (t.detail for t in reversed(runtime.trace) if t.kind == "decision"), {}
        )
        persona = runtime.personas[agent_id]
        return {
            "reply": " ".join(dialogue) if dialogue else "（她安静地点了点头。）",
            "actions": actions,
            "decision": decision,
            "relationship_user": round(persona.relationships.get("user", 0.5), 3),
            "memory": runtime.memory_store.recall(agent_id, "episodic"),
            "llm": self.llm_kind,
        }


BRAIN = StudioBrain()
RUNTIME_URL = ""  # set by --runtime-url: Studio becomes a voice body


class RuntimeBodyClient:
    """Studio as a *voice body* of the central Runtime Server (8765).

    One brain only: in this mode the studio никогда decides — it forwards the
    utterance and renders whatever dialogue the Character Runtime replies with.
    Persona editing is owned by the server's configs/characters.json."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.body_id = "studio-voice"
        self._socket = None
        self._lock = asyncio.Lock()

    async def _connect(self):
        if self._socket is not None:
            try:
                await self._socket.ping()
                return self._socket
            except Exception:
                self._socket = None
        import websockets

        agents = [c["id"] for c in load_characters()["characters"]]
        socket = await websockets.connect(f"{self.url}/body")
        await socket.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol": "0.2",
                    "body_id": self.body_id,
                    "backend": "voice",
                    "agent_ids": agents,
                    "manifest": {
                        "supported_steps": ["speak_line", "look_at_user"],
                        "supported_templates": [],
                        "features": {"speech": True, "gaze": False, "nav": False},
                    },
                },
                ensure_ascii=False,
            )
        )
        welcome = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
        if welcome.get("type") != "welcome":
            raise ConnectionError(f"runtime refused hello: {welcome}")
        self._socket = socket
        return socket

    async def chat(self, agent_id: str, text: str) -> dict:
        async with self._lock:
            socket = await self._connect()
            await socket.send(
                json.dumps(
                    {
                        "type": "event",
                        "kind": "user_utterance",
                        "source": "user",
                        "text": text,
                        "target_agent": agent_id,
                        "payload": {},
                    },
                    ensure_ascii=False,
                )
            )
            dialogue, correlation, decision, actions = [], None, {}, []
            loop = asyncio.get_event_loop()
            deadline = loop.time() + 10.0
            quiet_after = None
            while loop.time() < (quiet_after or deadline):
                try:
                    raw = await asyncio.wait_for(
                        socket.recv(),
                        timeout=max(0.05, (quiet_after or deadline) - loop.time()),
                    )
                except asyncio.TimeoutError:
                    break
                data = json.loads(raw)
                if (
                    data.get("type") == "plan_state"
                    and data.get("agent_id") == agent_id
                ):
                    decision = data.get("last_decision") or decision
                if data.get("type") != "action" or data.get("agent_id") != agent_id:
                    continue
                await socket.send(
                    json.dumps(
                        {
                            "type": "observation",
                            "command_id": data.get("command_id", ""),
                            "agent_id": agent_id,
                            "status": "accepted",
                            "body_id": self.body_id,
                        },
                        ensure_ascii=False,
                    )
                )
                actions.append(
                    {
                        "name": data.get("name"),
                        "correlation_id": data.get("correlation_id"),
                        "params": {
                            k: v
                            for k, v in (data.get("params") or {}).items()
                            if isinstance(v, (str, int, float, bool))
                        },
                    }
                )
                if data.get("dialogue"):
                    if correlation is None:
                        correlation = data.get("correlation_id")
                    if data.get("correlation_id") == correlation or correlation is None:
                        dialogue.append(data["dialogue"])
                        quiet_after = loop.time() + 0.8
            return {
                "reply": " ".join(dialogue) or "（她想了想，没有说话。）",
                "actions": actions,
                "decision": decision,
                "relationship_user": None,
                "memory": {},
                "llm": "RuntimeServer",
                "linked": True,
                "correlation_id": correlation,
            }


RUNTIME_CLIENT: RuntimeBodyClient | None = None


# --------------------------------------------------------------------- APIs
async def api_status(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "llm": "RuntimeServer" if RUNTIME_CLIENT else BRAIN.llm_kind,
            "llm_is_mock": BRAIN.llm_kind == "MockBehaviorLLM" and not RUNTIME_CLIENT,
            "fish_tts": bool(FISH_KEY),
            "edge_tts": True,
            "linked_runtime": RUNTIME_URL or None,
        }
    )


_api_status_inner = api_status


async def api_status(request: web.Request) -> web.Response:  # noqa: F811
    resp = await _api_status_inner(request)
    data = json.loads(resp.body)
    data.update(
        {
            "gateway_ws_url": GATEWAY_WS_URL,
            "runtime_ws_url": RUNTIME_WS_URL,
            "ai_core_url": AI_CORE_URL,
        }
    )
    return web.json_response(data)


async def api_characters(_request: web.Request) -> web.Response:
    return web.json_response(load_characters())


_MODEL_KINDS = {
    ".vrm": "vrm",
    ".glb": "glb",
    ".gltf": "glb",
    ".fbx": "fbx",
    ".pmx": "mmd",
}


def _model_license(path: Path) -> str | None:
    """LICENSE*.txt or asset_manifest.json beside the model, if any."""
    for cand in sorted(path.parent.glob("LICENSE*")):
        try:
            return cand.read_text("utf-8").strip().splitlines()[0][:120]
        except OSError:
            pass
    manifest = path.parent / "asset_manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text("utf-8"))
            entries = data.get("assets", data) if isinstance(data, dict) else data
            if isinstance(entries, dict):
                entry = entries.get(path.name) or entries.get(path.stem) or {}
            else:
                entry = next(
                    (
                        e
                        for e in entries
                        if e.get("file") == path.name or e.get("name") == path.stem
                    ),
                    {},
                )
            lic = (entry or {}).get("license") or (
                data.get("license") if isinstance(data, dict) else None
            )
            if lic:
                return str(lic)[:120]
        except (OSError, ValueError):
            pass
    return None


async def api_models(_request: web.Request) -> web.Response:
    """Every humanoid model under assets/vtubers: VRM, glTF/GLB, FBX (Mixamo/Unity), PMX.

    Non-VRM rigs are synthesized into a VRM at load time by
    studio/web/lib/humanoid_adapter.js; the RobotExpressive GLB stays kind
    "robot" (workbench-only procedural body).
    """
    models = []
    for path in sorted((ROOT / "assets" / "vtubers").rglob("*")):
        suffix = path.suffix.lower()
        if suffix not in _MODEL_KINDS or path.name.startswith("."):
            continue
        kind = _MODEL_KINDS[suffix]
        if suffix == ".glb" and "robotexpressive" in path.stem.lower():
            kind = "robot"
        models.append(
            {
                "name": path.stem,
                "url": "/assets/" + str(path.relative_to(ROOT / "assets")),
                "kind": kind,
                "size_mb": round(path.stat().st_size / 1e6, 1),
                "license": _model_license(path),
            }
        )
    return web.json_response(models)


async def api_soul_export(request: web.Request) -> web.Response:
    """Pack one persona of configs/characters.json (+ its model file) into a `.soul`."""
    from studio import soul_io

    body = await request.json() if request.can_read_body else {}
    cid = body.get("character_id") or request.query.get("character")
    if not cid:
        return web.json_response({"error": "character_id required"}, status=400)
    try:
        data, filename = soul_io.export_persona(
            cid,
            passphrase=body.get("passphrase") or None,
            include_model=body.get("include_model", True),
        )
    except KeyError:
        return web.json_response({"error": f"unknown character {cid}"}, status=404)
    from urllib.parse import quote

    return web.Response(
        body=data,
        content_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


async def api_soul_peek(request: web.Request) -> web.Response:
    from studio.soul_io import SoulPackBuilder

    body = await request.json()
    try:
        return web.json_response(
            SoulPackBuilder.peek(base64.b64decode(body["soul_b64"]))
        )
    except Exception as e:
        return web.json_response({"error": f"not a soul file: {e}"}, status=400)


async def api_soul_import(request: web.Request) -> web.Response:
    """Unpack a `.soul`: install model, write persona, mirror to ai-core when a brand is set."""
    from studio import soul_io

    body = await request.json()
    try:
        blob = base64.b64decode(body["soul_b64"])
        result = soul_io.import_persona(blob, passphrase=body.get("passphrase") or None)
    except (KeyError, ValueError) as e:
        return web.json_response({"error": str(e)}, status=400)
    soul_b64 = result.pop("soul_b64")
    result["ai_core"] = None
    brand = load_dotenv_key("SOUL_BRAND_ID")
    if brand and AI_CORE_TOKEN:  # ai-core needs a brand context; optional mirror
        import aiohttp

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    f"{AI_CORE_URL}/soul-packs/import",
                    json={
                        "soul_b64": soul_b64,
                        "passphrase": body.get("passphrase") or None,
                        "upsert_by_name": True,
                        "publish": True,
                        "archetype": "HUMAN",
                    },
                    headers={"X-Service-Token": AI_CORE_TOKEN, "X-Brand-Id": brand},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    j = await resp.json()
                    result["ai_core"] = (
                        j.get("character_id") if resp.status < 300 else None
                    )
                    if resp.status >= 300:
                        result["ai_core_error"] = j.get("detail") or j
        except Exception as e:
            result["ai_core_error"] = str(e)
    return web.json_response(result)


async def api_soul_sync(request: web.Request) -> web.Response:
    """configs/characters.json → ai-core characters (upsert by name); first persona → web body."""
    from studio import soul_io

    body = await request.json() if request.can_read_body else {}
    try:
        if body.get("character_id"):
            out = soul_io.sync_persona(
                body["character_id"], bind_device=body.get("bind_device")
            )
        else:
            out = soul_io.sync_all(web_device=body.get("bind_device", "web_vrm-live"))
    except Exception as e:  # missing env / ai-core down: say so
        return web.json_response({"error": str(e)}, status=502)
    return web.json_response({"synced": out})


async def api_animations(_request: web.Request) -> web.Response:
    """VRMA motion assets under assets/animations/ (drop .vrma files there)."""
    out = []
    directory = ROOT / "assets" / "animations"
    if directory.exists():
        for path in sorted(directory.glob("*.vrma")):
            out.append(
                {
                    "name": path.stem.replace("vrma_", "").replace("_", " "),
                    "url": "/assets/animations/" + path.name,
                }
            )
    return web.json_response(out)


async def api_voices(_request: web.Request) -> web.Response:
    fish_voices = []
    for character in load_characters()["characters"]:
        fish = character.get("voice", {}).get("fish", {})
        if fish.get("reference_id"):
            fish_voices.append(
                {
                    "id": fish["reference_id"],
                    "label": f"{character['name']} · {fish.get('label', 'fish 音色')}",
                    "speed": fish.get("speed", 1.0),
                }
            )
    return web.json_response(
        {
            "fish": fish_voices if FISH_KEY else [],
            "fish_available": bool(FISH_KEY),
            "edge": EDGE_VOICE_CATALOG,
        }
    )


async def api_chat(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    text = str(data.get("text", "")).strip()
    agent_id = str(data.get("agent_id", "luna"))
    if not text or len(text) > 500:
        return web.json_response({"error": "text must be 1-500 chars"}, status=400)
    overrides = data.get("persona") or {}
    if RUNTIME_CLIENT is not None:
        try:
            result = await RUNTIME_CLIENT.chat(agent_id, text)
        except Exception as exc:
            return web.json_response(
                {"error": f"runtime link failed: {exc}"}, status=502
            )
    else:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, BRAIN.chat, agent_id, text, overrides)
    return web.json_response(result)


async def api_tts(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    text = str(data.get("text", "")).strip()
    if not text or len(text) > 600:
        return web.json_response({"error": "text must be 1-600 chars"}, status=400)
    voice = data.get("voice") or {}
    provider = voice.get("provider", "edge")
    fallback_note = ""
    try:
        if provider == "fish":
            try:
                audio = await tts_fish(text, voice)
            except Exception as exc:
                # never go mute: degrade to edge with a comparable voice
                fallback_note = f"fish 不可达（{str(exc)[:80]}），已降级 Edge"
                audio = await tts_edge(
                    text, {"id": "zh-CN-XiaoxiaoNeural", "rate": 0, "pitch": 0}
                )
        else:
            audio = await tts_edge(text, voice)
    except Exception as exc:
        return web.json_response({"error": f"tts failed: {exc}"}, status=502)
    from urllib.parse import quote

    headers = {"X-TTS-Fallback": quote(fallback_note)} if fallback_note else {}
    return web.Response(body=audio, content_type="audio/mpeg", headers=headers)


# NOTE: aiohttp's TLS handshake fails against these hosts on this Python 3.14
# setup (ConnectionReset), while stdlib urllib and the ai-core edge-tts CLI are
# proven working — so outbound TTS deliberately avoids aiohttp clients.


async def tts_edge(text: str, voice: dict) -> bytes:
    import tempfile

    rate = int(voice.get("rate", 0))
    pitch = int(voice.get("pitch", 0))
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        process = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "--package",
            "ai-core",
            "edge-tts",
            "--voice",
            voice.get("id", "zh-CN-XiaoxiaoNeural"),
            "--rate",
            f"{'+' if rate >= 0 else ''}{rate}%",
            "--pitch",
            f"{'+' if pitch >= 0 else ''}{pitch}Hz",
            "--write-media",
            str(out_path),
            "--text",
            text,
            cwd=str(ROOT),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        audio = out_path.read_bytes() if out_path.exists() else b""
        if process.returncode != 0 or len(audio) < 100:
            raise RuntimeError(
                (stderr or b"edge-tts produced no audio")[-160:].decode(
                    "utf-8", "replace"
                )
            )
        return audio
    finally:
        out_path.unlink(missing_ok=True)


def _fish_request(text: str, voice: dict) -> bytes:
    """Cross-border TLS to fish.audio is flaky (mid-handshake EOF resets):
    retry with backoff before giving up."""
    import time as _time
    import urllib.error
    import urllib.request

    payload = json.dumps(
        {
            "text": text,
            "reference_id": voice.get("id"),
            "format": "mp3",
            "mp3_bitrate": 128,
            "normalize": True,
            "temperature": 0.7,
            "top_p": 0.8,
            "latency": "normal",
            "prosody": {"speed": float(voice.get("speed", 1.0)), "volume": 0},
        }
    ).encode("utf-8")
    last_error: Exception = RuntimeError("no attempt")
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                "https://api.fish.audio/v1/tts",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Connection": "close",
                    "Authorization": f"Bearer {FISH_KEY}",
                    "model": FISH_MODEL,
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                audio = response.read()
            if len(audio) < 100:
                raise RuntimeError("fish returned empty audio")
            return audio
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            last_error = exc
            _time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"fish unreachable after 3 attempts: {last_error}")


async def _fish_via_curl(text: str, voice: dict) -> bytes:
    """Primary fish transport: the network path resets Python-OpenSSL TLS
    handshakes while curl's stack passes — so ship the request through curl."""
    import tempfile

    payload = json.dumps(
        {
            "text": text,
            "reference_id": voice.get("id"),
            "format": "mp3",
            "mp3_bitrate": 128,
            "normalize": True,
            "temperature": 0.7,
            "top_p": 0.8,
            "latency": "normal",
            "prosody": {"speed": float(voice.get("speed", 1.0)), "volume": 0},
        },
        ensure_ascii=False,
    )
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        process = await asyncio.create_subprocess_exec(
            "curl",
            "-s",
            "-m",
            "30",
            "--retry",
            "2",
            "--retry-delay",
            "1",
            "-X",
            "POST",
            "https://api.fish.audio/v1/tts",
            "-H",
            "Content-Type: application/json",
            "-H",
            f"Authorization: Bearer {FISH_KEY}",
            "-H",
            f"model: {FISH_MODEL}",
            "-d",
            payload,
            "-o",
            str(out_path),
            "-w",
            "%{http_code}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=40)
        code = (stdout or b"").decode().strip()
        audio = out_path.read_bytes() if out_path.exists() else b""
        if process.returncode != 0 or code != "200" or len(audio) < 100:
            raise RuntimeError(f"curl transport http={code or '?'} bytes={len(audio)}")
        return audio
    finally:
        out_path.unlink(missing_ok=True)


async def tts_fish(text: str, voice: dict) -> bytes:
    if not FISH_KEY:
        raise RuntimeError("FISH_AUDIO_API_KEY not configured")
    try:
        return await _fish_via_curl(text, voice)  # proven TLS path
    except Exception:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fish_request, text, voice)


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STUDIO_WEB / "index.html")


async def api_core_proxy(request: web.Request) -> web.Response:
    """Forward /api/core/<path> to ai-core (memory graph, relationship, export …).

    The browser never talks to ai-core directly (auth + CORS); studio relays with
    the service token. Same-host aiohttp client is fine (the TLS issue noted for
    fish/bing only bites remote hosts on Py3.14).
    """
    import aiohttp

    path = request.match_info["path"]
    url = f"{AI_CORE_URL}/{path}"
    headers = {"X-Service-Token": AI_CORE_TOKEN} if AI_CORE_TOKEN else {}
    body = await request.read() if request.can_read_body else None
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.request(
                request.method,
                url,
                params=request.query,
                data=body,
                headers={
                    **headers,
                    "Content-Type": request.content_type or "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                payload = await resp.read()
                return web.Response(
                    body=payload,
                    status=resp.status,
                    content_type=resp.content_type or "application/json",
                )
    except Exception as e:  # ai-core down → JSON error the page can render
        return web.json_response({"error": f"ai-core unreachable: {e}"}, status=502)


async def live(_request: web.Request) -> web.FileResponse:
    """VRM 作为 gateway 身体的实时页面（语音/记忆/PAD 全走 gateway 管道）。"""
    return web.FileResponse(STUDIO_WEB / "live.html")


@web.middleware
async def no_cache(request: web.Request, handler):
    """Page/lib assets change constantly; WKWebView (Tauri) caches them hard."""
    resp = await handler(request)
    if request.path.startswith(("/studio/", "/live", "/api/")) or request.path == "/":
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


def build_app() -> web.Application:
    app = web.Application(client_max_size=256 * 1024 * 1024, middlewares=[no_cache])
    app.router.add_get("/", index)
    app.router.add_get("/live", live)
    app.router.add_route("*", "/api/core/{path:.*}", api_core_proxy)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/characters", api_characters)
    app.router.add_get("/api/models", api_models)
    app.router.add_get("/api/voices", api_voices)
    app.router.add_get("/api/animations", api_animations)
    app.router.add_post("/api/soul/export", api_soul_export)
    app.router.add_post("/api/soul/peek", api_soul_peek)
    app.router.add_post("/api/soul/import", api_soul_import)
    app.router.add_post("/api/soul/sync", api_soul_sync)
    app.router.add_post("/api/chat", api_chat)
    app.router.add_post("/api/tts", api_tts)
    app.router.add_static("/studio/", STUDIO_WEB)
    app.router.add_static("/assets/", ROOT / "assets")
    app.router.add_static("/node_modules/", ROOT / "node_modules")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="SoulForge Studio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument(
        "--runtime-url",
        default="",
        help="e.g. ws://127.0.0.1:8765 — Studio becomes a voice "
        "body of the central Runtime Server (one brain)",
    )
    args = parser.parse_args()
    global RUNTIME_URL, RUNTIME_CLIENT
    if args.runtime_url:
        RUNTIME_URL = args.runtime_url
        RUNTIME_CLIENT = RuntimeBodyClient(args.runtime_url)
    print(
        f"SoulForge Studio → http://{args.host}:{args.port}  "
        f"(brain={'RuntimeServer@' + RUNTIME_URL if RUNTIME_URL else BRAIN.llm_kind}, "
        f"fish_tts={'on' if FISH_KEY else 'off'})"
    )
    web.run_app(build_app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
