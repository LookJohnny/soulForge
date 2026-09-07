import asyncio
import base64
from contextlib import asynccontextmanager
import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
import httpx
import numpy as np
from PIL import Image
import pytest

from avatar_worker.app import Worker, create_app
from avatar_worker.backend import BackendUnavailable, FlashHeadBackend, Geometry, Settings


def settings(model_type="pro"):
    return Settings(token="synthetic-worker-token", source_image="/synthetic/person.png",
        repo="/synthetic/source", model_dir="/synthetic/model", wav2vec_dir="/synthetic/wav2vec",
        model_type=model_type)


class FakeBackend:
    def __init__(self, model_type="pro"):
        self.geometry = Geometry.for_model(model_type)
        self.cuda_available = False  # Deliberate injection; never used by real startup.
        self.blocks = []
        self.resets = 0
        self.entered = threading.Event()
        self.release = None
        self.fail = False
        self.wrong_count = False

    def setup(self):
        pass

    def reset(self):
        self.resets += 1

    def render_block(self, pcm):
        self.blocks.append(pcm)
        self.entered.set()
        if self.release:
            assert self.release.wait(3), "Synthetic GPU operation did not get released"
        if self.fail:
            raise RuntimeError("private internal path or credential must not be disclosed")
        count = self.geometry.frames_per_chunk - int(self.wrong_count)
        return ["synthetic-base64-jpeg"] * count


@asynccontextmanager
async def service(model_type="pro", backend=None):
    backend = backend or FakeBackend(model_type)
    app = create_app(settings(model_type), backend)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker") as client:
            yield client, app.state.worker, backend


def request_body(geometry, blocks=1):
    # Different signed PCM values per block prove exact input slicing and ordering.
    pcm = b"".join(np.full(geometry.block_samples, i * 100 - 100, dtype="<i2").tobytes()
                   for i in range(blocks))
    return {"request_id": "synthetic-turn-1", "sample_rate": 16000,
            "audio_base64": base64.b64encode(pcm).decode()}, pcm


HEADERS = {"Authorization": "Bearer synthetic-worker-token"}


@pytest.mark.asyncio
@pytest.mark.parametrize("model_type,block_samples,frames_per_chunk", [("pro", 17920, 28), ("lite", 15360, 24)])
async def test_actual_routes_preserve_pcm_sample_clock_and_chunk_order(model_type, block_samples, frames_per_chunk):
    async with service(model_type) as (client, worker, backend):
        health = (await client.get("/health")).json()
        assert health["block_samples"] == block_samples
        assert health["frames_per_chunk"] == frames_per_chunk
        assert health["capabilities"]["gaze_control"] is False
        assert health["capabilities"]["emotion_control"] is False
        body, pcm = request_body(backend.geometry, 3)
        response = await client.post("/render", headers=HEADERS, json=body)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [event["type"] for event in events] == ["chunk", "chunk", "chunk", "done"]
        for i, event in enumerate(events[:-1]):
            assert event["chunk_seq"] == i
            assert event["start_sample"] == i * block_samples
            assert event["sample_count"] == block_samples
            assert event["frame_count"] == len(event["frames"]) == frames_per_chunk
            assert event["sample_count"] * event["fps"] == event["frame_count"] * event["sample_rate"]
        assert events[-1]["total_samples"] == len(pcm) // 2
        assert events[-1]["total_frames"] == frames_per_chunk * 3
        assert b"".join(backend.blocks) == pcm
        assert backend.resets == 1
        assert worker.completed_requests == 1 and worker.cancelled_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token", "Basic synthetic-worker-token"])
async def test_authentication_rejects_before_inference(authorization):
    async with service() as (client, _, backend):
        body, _ = request_body(backend.geometry)
        headers = {"Authorization": authorization} if authorization else {}
        response = await client.post("/render", headers=headers, json=body)
        assert response.status_code == 401 and backend.blocks == [] and backend.resets == 0
        assert "synthetic-worker-token" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"sample_rate": 24000}, {"sample_rate": True}, {"audio_base64": "not base64!"},
    {"audio_base64": ""}, {"audio_base64": "AAAA"}, {"request_id": "../../path"},
    {"gaze": "user"},
])
async def test_invalid_format_and_partial_blocks_never_enter_model(change):
    async with service() as (client, _, backend):
        body, _ = request_body(backend.geometry)
        body.update(change)
        response = await client.post("/render", headers=HEADERS, json=body)
        assert response.status_code == 422 and backend.blocks == []


@pytest.mark.asyncio
async def test_request_body_size_is_bounded():
    async with service() as (client, worker, backend):
        response = await client.post("/render", headers=HEADERS,
                                     content=b"x" * (worker.max_samples * 3))
        assert response.status_code == 413 and backend.blocks == []


@pytest.mark.asyncio
async def test_second_request_rejected_while_single_gpu_is_in_flight():
    backend = FakeBackend()
    backend.release = threading.Event()
    async with service(backend=backend) as (client, worker, _):
        body, _ = request_body(backend.geometry)
        first = asyncio.create_task(client.post("/render", headers=HEADERS, json=body))
        try:
            assert await asyncio.to_thread(backend.entered.wait, 2)
            second = await client.post("/render", headers=HEADERS, json=body)
            assert second.status_code == 429
            assert worker.busy is True and len(backend.blocks) == 1
        finally:
            backend.release.set()
        assert (await first).status_code == 200


@pytest.mark.asyncio
async def test_disconnect_discards_inflight_frames_and_holds_gpu_until_finished():
    backend = FakeBackend()
    backend.release = threading.Event()
    worker = Worker(settings(), backend)
    await worker.start()
    disconnected = [False]

    async def is_disconnected():
        return disconnected[0]

    _, pcm = request_body(backend.geometry, 3)
    response = await worker.stream(SimpleNamespace(is_disconnected=is_disconnected), pcm, "old-turn")
    first_item = asyncio.create_task(response.body_iterator.__anext__())
    try:
        assert await asyncio.to_thread(backend.entered.wait, 2)
        disconnected[0] = True
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(first_item, 1)
        assert worker.busy is True  # CUDA work cannot be killed by cancelling asyncio.
        with pytest.raises(HTTPException) as error:
            worker.begin(pcm, "too-soon")
        assert error.value.status_code == 429
    finally:
        backend.release.set()
        await asyncio.wait_for(worker._task, 2)
    assert len(backend.blocks) == 1
    assert worker.busy is False and worker.cancelled_requests == 1
    assert worker.ready is True


@pytest.mark.asyncio
async def test_disconnect_before_response_generator_starts_cancels_producer(monkeypatch):
    backend = FakeBackend()
    worker = Worker(settings(), backend)
    await worker.start()
    _, pcm = request_body(backend.geometry, 2)
    response = await worker.stream(SimpleNamespace(), pcm, "never-started")

    async def not_started(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr("avatar_worker.app.StreamingResponse.__call__", not_started)
    with pytest.raises(asyncio.CancelledError):
        await response({}, None, None)
    await asyncio.wait_for(worker._task, 1)
    assert backend.blocks == [] and worker.busy is False
    assert worker.cancelled_requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_count", [False, True])
async def test_inference_failure_is_explicit_not_fake_video_or_done(wrong_count):
    backend = FakeBackend()
    backend.wrong_count = wrong_count
    backend.fail = not wrong_count
    async with service(backend=backend) as (client, worker, _):
        body, _ = request_body(backend.geometry)
        response = await client.post("/render", headers=HEADERS, json=body)
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [event["type"] for event in events] == ["error"]
        assert "private" not in response.text
        assert worker.ready is False and worker.reason == "inference_failed"
        again = await client.post("/render", headers=HEADERS, json=body)
        assert again.status_code == 503


@pytest.mark.asyncio
async def test_cpu_backend_health_is_not_ready_without_loading_or_mocking(monkeypatch):
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    monkeypatch.setattr("avatar_worker.backend.importlib.import_module", lambda name: torch)
    backend = FlashHeadBackend(settings())
    app = create_app(settings(), backend)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker") as client:
            health = (await client.get("/health")).json()
            assert health["configured"] is True and health["ready"] is False
            assert health["cuda_available"] is False and health["reason"] == "cuda_unavailable"
            body, _ = request_body(backend.geometry)
            assert (await client.post("/render", headers=HEADERS, json=body)).status_code == 503
    assert backend.pipeline is None


def test_multi_gpu_environment_is_not_falsely_advertised(monkeypatch):
    monkeypatch.setenv("WORLD_SIZE", "2")
    with pytest.raises(BackendUnavailable, match="multi_gpu_worker_not_supported"):
        FlashHeadBackend(settings()).setup()


@pytest.mark.parametrize("model_type,overlap", [("pro", 5), ("lite", 9)])
def test_real_adapter_uses_official_audio_window_drops_overlap_and_encodes_jpeg(model_type, overlap):
    backend = FlashHeadBackend(settings(model_type))
    pipeline = SimpleNamespace(reset_person_name=Mock(), generator=SimpleNamespace(manual_seed=Mock()))
    backend.pipeline = pipeline
    # Synthetic frame index encoded as luminance identifies the exact dropped
    # overlap, including the first block, after real JPEG encode/decode.
    values = np.broadcast_to(np.arange(33, dtype=np.uint8)[:, None, None, None], (33, 512, 512, 3)).copy()

    class Tensor:
        shape = values.shape
        def __getitem__(self, key):
            return SimpleNamespace(cpu=lambda: SimpleNamespace(numpy=lambda: values[key]))

    backend.api = SimpleNamespace(get_audio_embedding=Mock(return_value="embedding"),
                                  run_pipeline=Mock(return_value=Tensor()))
    backend.reset()
    pcm = np.full(backend.geometry.block_samples, -16384, dtype="<i2").tobytes()
    frames = backend.render_block(pcm)
    args = backend.api.get_audio_embedding.call_args.args
    assert args[0] is pipeline and args[2:] == (167, 200)
    audio = args[1]
    assert len(audio) == 128000 and audio.dtype == np.float32
    assert np.all(audio[:-backend.geometry.block_samples] == 0)
    assert np.all(audio[-backend.geometry.block_samples:] == -0.5)
    assert len(frames) == 33 - overlap
    for encoded, expected in [(frames[0], overlap), (frames[-1], 32)]:
        image = Image.open(io.BytesIO(base64.b64decode(encoded)))
        assert image.size == (512, 512) and image.format == "JPEG"
        assert abs(int(np.asarray(image)[0, 0, 0]) - expected) <= 1
    backend.reset()
    assert np.all(np.asarray(backend.audio) == 0)
    assert pipeline.reset_person_name.call_count == 2
