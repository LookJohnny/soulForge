"""Loopback WebRTC gateway. Public access is through the Studio's same-origin proxy."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import hmac
import json
import logging
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from aiohttp import ClientSession, web
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
import av
from dotenv import dotenv_values

from .media import Playout, VoiceActivity, decode_audio
from .upstream import Gateway, Worker

LOG = logging.getLogger("media_body")


@dataclass
class Settings:
    token: str = ""
    gateway_url: str = "http://127.0.0.1:8081"
    gateway_token: str = ""
    worker_url: str = "http://127.0.0.1:8092"
    worker_token: str = ""
    port: int = 8902
    session_seconds: int = 900

    @classmethod
    def load(cls):
        root = Path(__file__).resolve().parents[4]
        env = dict(os.environ)
        env.update({k: v for k, v in dotenv_values(root / ".env", interpolate=False).items() if v is not None})
        return cls(token=env.get("SELFHOST_MEDIA_TOKEN", ""),
                   gateway_url=env.get("GATEWAY_API_URL") or f"http://127.0.0.1:{env.get('GATEWAY_PORT', '8081')}",
                   gateway_token=env.get("GATEWAY_API_TOKEN", ""),
                   worker_url=env.get("AVATAR_WORKER_URL", "http://127.0.0.1:8092"),
                   worker_token=env.get("AVATAR_WORKER_TOKEN", ""),
                   port=int(env.get("SELFHOST_MEDIA_PORT", "8902")))

    def validate(self):
        if len(self.token) < 24:
            raise ValueError("Set SELFHOST_MEDIA_TOKEN to a random secret of at least 24 characters")
        for value in (self.gateway_url, self.worker_url):
            url = urlsplit(value)
            if (url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}
                    or url.scheme not in {"http", "https"} or not url.hostname):
                raise ValueError("Upstream URLs must be plain HTTP(S) base URLs")
            if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Use HTTPS or a loopback SSH forward for remote GPU access")


class BodySession:
    def __init__(self, service: Service, owner: str, sid: str, brain_id: str, pc):
        self.service, self.owner, self.id = service, owner, sid
        self.brain_id, self.pc = brain_id, pc
        self.epoch = 0
        self.turn_id = None
        self.task = None
        self.asr_task = None
        self.retire_task = None
        self.brain_usable = True
        self.mic_tasks = set()
        self.receipt_id = None
        self.channel = None
        self.closed = False
        self.created = time.monotonic()
        self.disconnected_at = None
        self.offer_sdp = None
        self.answer = None
        self.phase = "listening"
        self.lock = asyncio.Lock()
        self.playout = Playout(lambda: self.emit("state", phase="speaking"))
        pc.addTrack(self.playout.audio)
        pc.addTrack(self.playout.video)

        @pc.on("datachannel")
        def on_channel(channel):
            if channel.label != "events" or self.channel is not None:
                channel.close()
                return
            self.channel = channel

            @channel.on("open")
            def ready():
                self.emit("state", phase=self.phase)

            # With negotiated SCTP it may already be open when delivered.
            if channel.readyState == "open":
                ready()

        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                task = asyncio.create_task(self.consume_mic(track))
                self.mic_tasks.add(task)
                task.add_done_callback(self.mic_tasks.discard)

        @pc.on("connectionstatechange")
        async def on_connection():
            if pc.connectionState == "disconnected":
                self.disconnected_at = time.monotonic()
            elif pc.connectionState == "connected":
                self.disconnected_at = None
            if pc.connectionState in {"failed", "closed"} and not self.closed:
                await self.close()

    def emit(self, kind: str, **fields):
        if kind == "state":
            self.phase = fields["phase"]
        data = {"type": kind, "session_id": self.id, "epoch": self.epoch, **fields}
        if self.channel and self.channel.readyState == "open":
            self.channel.send(json.dumps(data, ensure_ascii=False))

    async def _cancel(self):
        old_turn = self.turn_id
        old_task, self.task = self.task, None
        self.epoch += 1
        await self.playout.reset(self.epoch)
        if self.asr_task and self.asr_task is not asyncio.current_task():
            self.asr_task.cancel()
        self.asr_task = None
        if old_task and old_task is not asyncio.current_task():
            old_task.cancel()
        self.turn_id = None
        self.receipt_id = None
        self.emit("cancelled", turn_id=old_turn)
        self.emit("state", phase="listening")
        if old_turn:
            previous = self.retire_task

            async def retire():
                try:
                    if previous:
                        await previous
                    if old_task:
                        # Late results are epoch-filtered even if a library ignores
                        # cancellation. Keep microphone collection independent.
                        await asyncio.wait({old_task}, timeout=1)
                    async with asyncio.timeout(5):
                        await self.service.gateway.interrupt(self.brain_id, old_turn)
                except Exception:
                    self.brain_usable = False

            self.retire_task = asyncio.create_task(retire())

    async def interrupt(self):
        async with self.lock:
            await self._cancel()

    async def start_turn(self, text: str):
        async with self.lock:
            if self.closed:
                raise web.HTTPGone()
            await self._cancel()
            self.turn_id = str(uuid4())
            self.emit("caption", role="user", text=text, turn_id=self.turn_id)
            self.emit("state", phase="thinking")
            self.task = asyncio.create_task(self.run_turn(self.epoch, self.turn_id, text))
            return {"turn_id": self.turn_id, "epoch": self.epoch}

    async def run_turn(self, epoch: int, turn_id: str, text: str):
        started = time.monotonic()
        first_audio = first_video = None
        receipt = None
        try:
            if self.retire_task:
                await asyncio.shield(self.retire_task)
            if not self.brain_usable:
                raise ValueError("previous brain turn cleanup not confirmed; reconnect")
            health = await self.service.worker.health()
            deadline = time.monotonic() + 30
            while health.get("busy"):
                if time.monotonic() >= deadline:
                    raise TimeoutError("GPU still completing cancelled work")
                await asyncio.sleep(.2)
                health = await self.service.worker.health()
            block = health.get("block_samples", 0)
            if (not health.get("ready") or health.get("sample_rate") != 16000
                    or health.get("fps") != 25 or not isinstance(block, int) or not 640 <= block <= 64000
                    or block % 640):
                raise ValueError("GPU contract not ready")
            done = False
            async for event in self.service.gateway.turn(self.brain_id, turn_id, text):
                if epoch != self.epoch:
                    raise asyncio.CancelledError
                kind = event.get("type")
                if kind == "error":
                    raise ValueError("brain turn failed")
                if kind == "decision":
                    self.emit("decision", turn_id=turn_id, emotion=event.get("emotion"),
                              actions_supported=False)
                elif kind == "audio":
                    receipt = event.get("receipt_id") or receipt
                    self.receipt_id = receipt
                    pcm = await asyncio.to_thread(decode_audio, event["audio_base64"], event["format"])
                    first_audio = first_audio or time.monotonic()
                    self.emit("caption", role="assistant", text=event.get("text", ""), turn_id=turn_id)
                    if self.phase != "speaking":
                        self.emit("state", phase="generating")
                    padded = pcm.ljust(((len(pcm) + block * 2 - 1) // (block * 2)) * block * 2, b"\0")
                    request_id = str(uuid4())
                    expected_start = 0
                    render_done = False
                    async for chunk in self.service.worker.render(request_id, padded):
                        if epoch != self.epoch:
                            raise asyncio.CancelledError
                        if chunk.get("type") == "error":
                            raise ValueError("GPU render failed")
                        if chunk.get("type") == "done":
                            render_done = True
                            continue
                        if chunk.get("type") != "chunk" or render_done:
                            raise ValueError("invalid GPU stream")
                        frames = chunk.get("frames", [])
                        count = chunk.get("sample_count", 0)
                        if (chunk.get("start_sample") != expected_start or chunk.get("sample_rate") != 16000
                                or chunk.get("fps") != 25 or count != block
                                or chunk.get("frame_count") != len(frames) or len(frames) * 640 != count):
                            raise ValueError("GPU audio/video alignment mismatch")
                        first_video = first_video or time.monotonic()
                        await self.playout.enqueue(epoch, pcm[expected_start * 2:(expected_start + count) * 2], frames)
                        expected_start += count
                    if not render_done or expected_start * 2 != len(padded):
                        raise ValueError("incomplete GPU render")
                elif kind == "done":
                    done = True
            if not done:
                raise ValueError("incomplete brain turn")
            await self.playout.drain(epoch)
            # Sender drain is NOT an actual-playback receipt. Conservatively reject
            # execution until the browser can acknowledge exact turn/sample bounds.
            if receipt:
                await self.service.gateway.receipt(self.brain_id, receipt, played=False)
                self.receipt_id = None
            self.emit("metrics", turn_id=turn_id,
                      first_audio_ready_ms=round((first_audio - started) * 1000) if first_audio else None,
                      first_video_ready_ms=round((first_video - started) * 1000) if first_video else None,
                      sender_drained_ms=round((time.monotonic() - started) * 1000),
                      browser_playback_verified=False, dropped_packets=self.playout.dropped_packets)
            self.emit("state", phase="listening")
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.warning("media turn failed session=%s turn=%s", self.id, turn_id)
            if epoch == self.epoch:
                self.epoch += 1
                await self.playout.reset(self.epoch)
                self.emit("error", message="视频轮次未完成，请检查大脑与 GPU 服务状态。", turn_id=turn_id)
                self.emit("state", phase="listening")
            with contextlib.suppress(Exception):
                await self.service.gateway.interrupt(self.brain_id, turn_id)

    async def consume_mic(self, track):
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        vad = VoiceActivity()
        pending = bytearray()
        try:
            while not self.closed:
                frame = await track.recv()
                for part in resampler.resample(frame):
                    pending.extend(part.to_ndarray().tobytes())
                while len(pending) >= 640:
                    piece = bytes(pending[:640])
                    del pending[:640]
                    onset, utterance = vad.feed(piece)
                    if onset:
                        await self.interrupt()
                    if utterance:
                        async def transcribe(pcm=utterance, epoch=self.epoch):
                            try:
                                if epoch != self.epoch or self.closed:
                                    return
                                self.emit("state", phase="transcribing")
                                text = await self.service.gateway.transcribe(self.brain_id, pcm)
                                if text.strip() and epoch == self.epoch and not self.closed:
                                    await self.start_turn(text.strip())
                                elif epoch == self.epoch:
                                    self.emit("state", phase="listening")
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                if epoch == self.epoch and not self.closed:
                                    self.emit("error", message="语音识别失败，可以输入文字继续。")
                                    self.emit("state", phase="listening")
                        self.asr_task = asyncio.create_task(transcribe())
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                self.emit("error", message="麦克风连接已结束，可以输入文字继续。")
        finally:
            if self.asr_task:
                self.asr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self.asr_task

    async def close(self):
        if self.closed:
            return
        self.closed = True
        async with self.lock:
            await self._cancel()
        for task in list(self.mic_tasks):
            task.cancel()
        if self.mic_tasks:
            await asyncio.gather(*self.mic_tasks, return_exceptions=True)
        if self.retire_task:
            await asyncio.wait({self.retire_task}, timeout=6)
            if not self.retire_task.done():
                self.retire_task.cancel()
        await self.playout.close()
        await self.pc.close()
        with contextlib.suppress(Exception):
            async with asyncio.timeout(5):
                await self.service.gateway.close(self.brain_id)
        self.service.sessions.pop(self.id, None)


class Service:
    def __init__(self, settings, gateway, worker):
        self.settings, self.gateway, self.worker = settings, gateway, worker
        self.sessions: dict[str, BodySession] = {}
        self.open_lock = asyncio.Lock()

    async def health(self):
        worker, gateway = {}, {}
        errors = []
        try:
            worker = await self.worker.health()
        except Exception:
            errors.append("GPU worker unreachable")
        try:
            gateway = await self.gateway.health("/media/health")
        except Exception:
            errors.append("media brain API unreachable")
        configured = bool(self.settings.worker_token and self.settings.gateway_token)
        ready = configured and worker.get("ready") is True and gateway.get("ready") is True
        return {"ready": ready, "status": "ready" if ready else "unconfigured" if not configured else "degraded",
                "worker": {k: worker.get(k) for k in ("ready", "status", "model", "revision", "block_samples", "fps", "reason")},
                "readiness_scope": "worker_loaded_and_brain_route_configured",
                "end_to_end_verified": False,
                "brain": {k: gateway.get(k) for k in ("ready", "readiness_scope", "end_to_end_verified", "dependencies")}, "issues": errors,
                "limitations": ["single session", "audio-driven face; no semantic gaze or gesture control",
                                "sentence audio buffering", "face state resets between render requests",
                                "energy VAD baseline", "idle holds last frame", "browser playback not verified"]}

    async def reap(self):
        while True:
            await asyncio.sleep(5)
            for session in list(self.sessions.values()):
                age = time.monotonic() - session.created
                if (age > self.settings.session_seconds
                        or (session.pc.connectionState in {"new", "connecting"} and age > 30)
                        or (session.disconnected_at and time.monotonic() - session.disconnected_at > 10)):
                    await session.close()


def client_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text="client_id must be a UUID") from None


async def payload(request):
    try:
        data = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text="JSON object required") from None
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="JSON object required")
    return data


async def make_app(settings=None, gateway=None, worker=None):
    settings = settings or Settings.load()
    settings.validate()
    http = ClientSession(trust_env=False)
    service = Service(settings, gateway or Gateway(http, settings.gateway_url, settings.gateway_token),
                      worker or Worker(http, settings.worker_url, settings.worker_token))

    @web.middleware
    async def auth(request, handler):
        if request.path == "/livez" and request.method == "GET":
            return web.json_response({"status": "ok", "service": "media-body", "scope": "process_only"})
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {settings.token}"):
            raise web.HTTPUnauthorized()
        return await handler(request)

    app = web.Application(middlewares=[auth], client_max_size=1_000_000)
    app["service"] = service

    async def health(request):
        return web.json_response(await service.health())

    async def create(request):
        data = await payload(request)
        owner = client_id(data.get("client_id"))
        if data.get("type") != "offer" or not isinstance(data.get("sdp"), str) or len(data["sdp"]) > 100_000:
            raise web.HTTPBadRequest(text="valid RTC offer required")
        async with service.open_lock:
            if service.sessions:
                for existing in service.sessions.values():
                    if existing.owner == owner and existing.offer_sdp == data["sdp"] and existing.answer:
                        return web.json_response(existing.answer)
                raise web.HTTPConflict(text="one video session at a time")
            if not (await service.health())["ready"]:
                raise web.HTTPServiceUnavailable(text="GPU and media brain must be ready")
            sid = str(uuid4())
            brain_id = await service.gateway.open(f"selfhost-{sid}")
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            session = BodySession(service, owner, sid, brain_id, pc)
            session.offer_sdp = data["sdp"]
            service.sessions[sid] = session
            try:
                async with asyncio.timeout(20):
                    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type="offer"))
                    await pc.setLocalDescription(await pc.createAnswer())
                session.answer = {"session_id": sid, "sdp": pc.localDescription.sdp, "type": "answer"}
                return web.json_response(session.answer)
            except Exception:
                await session.close()
                raise web.HTTPBadRequest(text="RTC negotiation failed") from None

    async def action(request):
        data = await payload(request)
        owner = client_id(data.get("client_id"))
        session = service.sessions.get(request.match_info["sid"])
        if not session or session.owner != owner:
            raise web.HTTPNotFound()
        action = request.match_info["action"]
        if action == "turn":
            text = data.get("text", "")
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
                raise web.HTTPBadRequest(text="text must contain 1-4000 characters")
            return web.json_response(await session.start_turn(text.strip()))
        if action == "interrupt":
            await session.interrupt()
            return web.json_response({"ok": True, "epoch": session.epoch})
        if action == "close":
            await session.close()
            return web.json_response({"ok": True})
        raise web.HTTPNotFound()

    async def close_owned(request):
        owner = client_id((await payload(request)).get("client_id"))
        async with service.open_lock:
            owned = [session for session in service.sessions.values() if session.owner == owner]
            for session in owned:
                await session.close()
        return web.json_response({"ok": True, "closed": len(owned)})

    app.router.add_get("/health", health)
    app.router.add_get("/livez", health)  # middleware returns process-only liveness
    app.router.add_post("/sessions", create)
    app.router.add_post("/sessions/close-owned", close_owned)
    app.router.add_post("/sessions/{sid}/{action}", action)
    reaper = asyncio.create_task(service.reap())

    async def cleanup(app):
        reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper
        await asyncio.gather(*(session.close() for session in list(service.sessions.values())))
        await http.close()

    app.on_cleanup.append(cleanup)
    return app


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.load()
    web.run_app(make_app(settings), host="127.0.0.1", port=settings.port, access_log=None)


if __name__ == "__main__":
    main()
