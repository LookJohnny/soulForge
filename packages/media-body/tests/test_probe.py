"""Probe acceptance tests: synthetic upstreams, real loopback WebRTC/MP4.

No paid brain, TTS, worker or hardware is contacted by these tests.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
import io
import json
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestServer
import av
import numpy as np
from PIL import Image
import pytest

from media_body import probe
from media_body.server import Settings, make_app

TOKEN = "synthetic-probe-token-000000000000"


class SyntheticBrain:
    def __init__(self, *, blocked=False, silence=False, fail=False):
        self.blocked, self.silence, self.fail = blocked, silence, fail
        self.turns, self.closed = [], []
        self.started = asyncio.Event()

    async def health(self, path):
        return {"ready": True, "readiness_scope": "test_fixture"}

    async def open(self, body_id):
        return str(uuid4())

    async def turn(self, sid, turn_id, text):
        self.turns.append(text)
        self.started.set()
        if self.blocked:
            await asyncio.Event().wait()
        if self.fail:
            yield {"type": "error", "message": TOKEN}
            return
        yield {"type": "decision", "turn_id": turn_id}
        values = np.zeros(16000) if self.silence else np.sin(np.arange(16000) * 2 * np.pi * 440 / 16000) * 6000
        audio = base64.b64encode(values.astype(np.int16).tobytes()).decode()
        yield {"type": "audio", "turn_id": turn_id, "text": "虚构测试声音",
               "audio_base64": audio, "format": "pcm16"}
        yield {"type": "done", "turn_id": turn_id}

    async def interrupt(self, *args):
        pass

    async def receipt(self, *args, **kwargs):
        pass

    async def close(self, sid):
        self.closed.append(sid)


class SyntheticWorker:
    ready = True

    def __init__(self, delay=0):
        self.delay = delay

    async def health(self):
        return {"ready": self.ready, "block_samples": 16000, "fps": 25,
                "sample_rate": 16000, "model": "synthetic fixture only"}

    async def render(self, request_id, pcm):
        await asyncio.sleep(self.delay)
        picture = io.BytesIO()
        Image.new("RGB", (64, 64), (80, 120, 200)).save(picture, format="JPEG")
        yield {"type": "chunk", "request_id": request_id, "start_sample": 0,
               "sample_count": 16000, "sample_rate": 16000, "fps": 25,
               "frame_count": 25, "frames": [base64.b64encode(picture.getvalue()).decode()] * 25}
        yield {"type": "done", "request_id": request_id}


@asynccontextmanager
async def local_service(brain=None, worker=None):
    brain, worker = brain or SyntheticBrain(), worker or SyntheticWorker()
    settings = Settings(token=TOKEN, gateway_token="synthetic-gateway-token", worker_token="synthetic-worker-token")
    app = await make_app(settings, brain, worker)
    async with TestServer(app) as server:
        settings.port = server.port
        yield settings, brain, app["service"]


@pytest.mark.parametrize("ready, expected", [(True, True), (False, False), (None, False), ("true", False), (0, False)])
async def test_health_is_strict_and_never_prints_provider_secrets(ready, expected):
    async def health(request):
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        return web.json_response({"ready": ready, "token": TOKEN, "worker": {
            "model": TOKEN, "reason": "worker-token", "api_key": "do-not-print"},
            "brain": {"dependencies": {"credentials": TOKEN}}})
    app = web.Application()
    app.router.add_get("/health", health)
    async with TestServer(app) as server:
        result = await probe.check_health(Settings(token=TOKEN, port=server.port, worker_token="worker-token"))
    assert result["ready"] is expected
    serialized = json.dumps(result)
    assert TOKEN not in serialized and "worker-token" not in serialized
    assert "api_key" not in serialized and "credentials" not in serialized
    assert "[redacted]" in serialized


async def test_health_unconfigured_never_creates_http():
    def forbidden(settings):
        raise AssertionError("unconfigured health must not connect")
    result = await probe.check_health(Settings(), http_factory=forbidden)
    assert result == {"ready": False, "error": "media_token_unconfigured"}


async def test_health_rejects_redirect_without_leaking_authorization():
    destination_hit = False

    async def destination(request):
        nonlocal destination_hit
        destination_hit = True
        return web.json_response({"ready": True})

    target = web.Application()
    target.router.add_get("/", destination)
    async with TestServer(target) as remote:
        async def redirect(request):
            raise web.HTTPFound(str(remote.make_url("/")))
        source = web.Application()
        source.router.add_get("/health", redirect)
        async with TestServer(source) as server:
            result = await probe.check_health(Settings(token=TOKEN, port=server.port))
    assert result["error"] == "http_302"
    assert not destination_hit


def test_health_cli_exit_requires_boolean_true(monkeypatch, capsys):
    monkeypatch.setattr(probe.Settings, "load", lambda: Settings(token=TOKEN))

    async def ready(settings):
        return {"ready": True}
    monkeypatch.setattr(probe, "check_health", ready)
    assert probe.main(["--health"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ready": True}

    async def missing(settings):
        return {"status": "ready"}
    monkeypatch.setattr(probe, "check_health", missing)
    assert probe.main(["--health"]) == 1


async def test_real_received_mp4_has_audio_video_and_scoped_timings(tmp_path):
    async with local_service() as (settings, brain, service):
        result = await probe.run_probe(settings, "你好，这是离线合成测试。", tmp_path, timeout=12, tail_seconds=.3)
        assert result["ok"], result
        assert not service.sessions and len(brain.closed) == 1
        assert brain.turns == ["你好，这是离线合成测试。"]
    assert result["cleanup"] == {"remote_closed": True, "peer_closed": True, "http_closed": True}
    assert result["human_playback_verified"] is False and result["interruption_verified"] is False
    assert result["client"]["audio"]["first_non_silent_frame_ms"] > 0
    assert result["client"]["video"]["first_frame_ms"] > 0
    assert result["sender"]["first_video_ready_ms"] >= 0
    assert result["sender"]["scope"] != result["client"]["measurement"]
    with av.open(result["recording"]["path"]) as container:
        assert len(container.streams.video) == len(container.streams.audio) == 1
        frame = next(container.decode(video=0))
        assert frame.width == frame.height == 64
        assert frame.to_ndarray(format="rgb24").mean() > 50
    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved == result
    assert TOKEN not in json.dumps(saved)


async def test_delayed_first_video_preserves_valid_recording(tmp_path):
    # Silence is already flowing while the GPU is still preparing its first frame.
    async with local_service(worker=SyntheticWorker(delay=.5)) as (settings, _, _):
        result = await probe.run_probe(settings, "视频延迟", tmp_path, timeout=10, tail_seconds=.2)
    assert result["ok"], result
    assert result["client"]["video"]["first_frame_ms"] >= 500
    with av.open(result["recording"]["path"]) as container:
        frame = next(container.decode(video=0))
        assert frame.width == frame.height == 64
        assert float(frame.pts * frame.time_base) >= .5


async def test_turn_error_remains_visible_and_secrets_are_not_echoed(tmp_path):
    async with local_service(SyntheticBrain(fail=True)) as (settings, _, service):
        result = await probe.run_probe(settings, "故障测试", tmp_path, timeout=10)
        assert result["ok"] is False and result["error"] == "turn_failed"
        assert result["sender"] is None
        assert not service.sessions and all(result["cleanup"].values())
    assert TOKEN not in json.dumps(result)


async def test_health_handles_fragmented_json():
    async def health(request):
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        await response.write(b'{"rea')
        await asyncio.sleep(.01)
        await response.write(b'dy":true}')
        await response.write_eof()
        return response
    app = web.Application()
    app.router.add_get("/health", health)
    async with TestServer(app) as server:
        result = await probe.check_health(Settings(token=TOKEN, port=server.port))
        assert result["ready"] is True


async def test_not_ready_does_not_create_session_or_turn(tmp_path):
    worker = SyntheticWorker()
    worker.ready = False
    async with local_service(worker=worker) as (settings, brain, service):
        result = await probe.run_probe(settings, "不会调用", tmp_path)
        assert result["error"] == "media_not_ready"
        assert not service.sessions and not brain.turns and not brain.closed
    assert not list(tmp_path.glob("*.mp4"))


async def test_deadline_cleans_remote_peer_http_without_false_zero_timings(tmp_path):
    async with local_service(SyntheticBrain(blocked=True)) as (settings, brain, service):
        result = await probe.run_probe(settings, "等待", tmp_path, timeout=1.5)
        assert not result["ok"]
        assert result["status"] == "timeout" and result["error"] == "receive_deadline_exceeded"
        assert result["sender"] is None
        assert result["client"]["audio"]["first_non_silent_frame_ms"] is None
        assert result["client"]["video"]["first_frame_ms"] is None
        assert not service.sessions and brain.closed
        assert all(result["cleanup"].values())


async def test_cancel_closes_owned_remote_and_peer(tmp_path):
    async with local_service(SyntheticBrain(blocked=True)) as (settings, brain, service):
        peers = []

        def new_peer(config):
            pc = probe.RTCPeerConnection(config)
            peers.append(pc)
            return pc
        task = asyncio.create_task(probe.run_probe(settings, "取消", tmp_path, pc_factory=new_peer))
        await asyncio.wait_for(brain.started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 6)
        assert not service.sessions and brain.closed
        assert peers[0].connectionState == "closed"
        saved = json.loads(next(tmp_path.glob("*.json")).read_text())
        assert not saved["ok"] and all(saved["cleanup"].values())


async def test_silent_audio_is_not_successful_speech_acceptance(tmp_path):
    async with local_service(SyntheticBrain(silence=True)) as (settings, _, service):
        result = await probe.run_probe(settings, "静音测试", tmp_path, timeout=10, tail_seconds=.2)
        assert result["ok"] is False
        assert result["error"] == "missing_received_speech_or_video"
        assert result["client"]["audio"]["first_non_silent_frame_ms"] is None
        assert result["client"]["video"]["decoded_frames"] > 0
        assert not service.sessions


async def test_lost_create_response_still_closes_owner(tmp_path, monkeypatch):
    request = probe._request

    async def lost_response(http, base, path, data=None):
        result = await request(http, base, path, data)
        if path == "/sessions":
            raise TimeoutError("synthetic lost response")
        return result
    monkeypatch.setattr(probe, "_request", lost_response)
    async with local_service() as (settings, brain, service):
        result = await probe.run_probe(settings, "不会发送", tmp_path, timeout=10)
        assert result["error"] == "receive_deadline_exceeded"
        assert result["cleanup"]["remote_closed"] is True
        assert not service.sessions and brain.closed and not brain.turns


@pytest.mark.parametrize("seconds", [0, -1, 61, 1000])
async def test_duration_is_bounded(seconds, tmp_path):
    with pytest.raises(ValueError):
        await probe.run_probe(Settings(token=TOKEN), "测试", tmp_path, timeout=seconds)
