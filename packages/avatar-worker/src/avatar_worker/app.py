"""Authenticated NDJSON service, with one stateful GPU operation at a time."""

import asyncio
import base64
import binascii
from contextlib import asynccontextmanager
import hmac
import json
import math
import re
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from avatar_worker import FLASHHEAD_REVISION
from avatar_worker.backend import BackendUnavailable, FlashHeadBackend, Settings

MAX_AUDIO_SECONDS = 120
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class RenderResponse(StreamingResponse):
    def __init__(self, body, cancel):
        super().__init__(body, media_type="application/x-ndjson", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        self.cancel = cancel

    async def __call__(self, scope, receive, send):
        # Cover disconnect/cancellation before the async generator even starts;
        # its own finally is insufficient in that case.
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.cancel.set()


class Worker:
    def __init__(self, settings, backend):
        self.settings = settings
        self.backend = backend
        self.ready = False
        self.reason = "not_started"
        self.error_type = None
        self.busy = False
        self.inference_calls = 0
        self.completed_requests = 0
        self.cancelled_requests = 0
        self.failed_requests = 0
        self._task = None
        self._cancel = None

    @property
    def geometry(self):
        return self.backend.geometry

    @property
    def max_samples(self):
        # Allow padding of a 120 s utterance to the next whole model block.
        return math.ceil(MAX_AUDIO_SECONDS * self.geometry.sample_rate / self.geometry.block_samples) * self.geometry.block_samples

    async def start(self):
        if not self.settings.configured():
            self.reason = "missing_configuration"
            return
        try:
            await asyncio.to_thread(self.backend.setup)
            self.ready, self.reason = True, None
        except Exception as error:
            self.reason = str(error) if isinstance(error, BackendUnavailable) else "model_load_failed"
            self.error_type = type(error).__name__

    def health(self):
        geometry = self.geometry
        return {"configured": self.settings.configured(), "ready": self.ready,
                "status": "ready" if self.ready else "not_ready", "busy": self.busy,
                "model": f"SoulX-FlashHead/{self.settings.model_type}",
                "revision": FLASHHEAD_REVISION, "reason": self.reason,
                "error_type": self.error_type,
                "cuda_available": self.backend.cuda_available,
                "sample_rate": geometry.sample_rate, "fps": geometry.fps,
                "block_samples": geometry.block_samples,
                "frames_per_chunk": geometry.frames_per_chunk,
                "max_audio_samples": self.max_samples,
                "capabilities": {"audio_driven": True, "streamed_output": True,
                    "incremental_audio_input": False, "gaze_control": False,
                    "emotion_control": False, "body_control": False,
                    "cross_request_motion_continuity": False,
                    "multi_gpu": False, "max_concurrent_requests": 1,
                    "cancellation": "between_blocks_and_discard_inflight"},
                "inference_calls": self.inference_calls,
                "completed_requests": self.completed_requests,
                "cancelled_requests": self.cancelled_requests,
                "failed_requests": self.failed_requests}

    async def _put(self, queue, item, cancel):
        # Backpressure is bounded; a disconnected reader must not strand the GPU
        # producer on a full queue after the in-flight CUDA call finishes.
        while not cancel.is_set():
            try:
                await asyncio.wait_for(queue.put(item), timeout=0.1)
                return
            except asyncio.TimeoutError:
                continue

    async def _produce(self, pcm, request_id, queue, cancel):
        geometry = self.geometry
        samples_per_block = geometry.block_samples
        chunks = 0
        completed = False
        try:
            if cancel.is_set():
                return
            await asyncio.to_thread(self.backend.reset)
            for offset in range(0, len(pcm), samples_per_block * 2):
                if cancel.is_set():
                    return
                # Never cancel the to_thread future. CUDA cannot be safely killed
                # mid-kernel; keep busy until it returns, then discard old output.
                frames = await asyncio.to_thread(self.backend.render_block,
                                                pcm[offset:offset + samples_per_block * 2])
                self.inference_calls += 1
                if cancel.is_set():
                    return
                if len(frames) != geometry.frames_per_chunk:
                    raise RuntimeError("Generated frames do not match the sample clock")
                await self._put(queue, {"type": "chunk", "request_id": request_id,
                    "chunk_seq": chunks, "start_sample": offset // 2,
                    "sample_count": samples_per_block, "sample_rate": geometry.sample_rate,
                    "fps": geometry.fps, "frames": frames, "frame_count": len(frames)}, cancel)
                chunks += 1
            if not cancel.is_set():
                completed = True
                self.completed_requests += 1
                await self._put(queue, {"type": "done", "request_id": request_id,
                    "chunk_count": chunks, "total_samples": len(pcm) // 2,
                    "total_frames": chunks * geometry.frames_per_chunk,
                    "sample_rate": geometry.sample_rate, "fps": geometry.fps}, cancel)
        except Exception as error:
            self.ready = False
            self.reason = "inference_failed"
            self.error_type = type(error).__name__
            self.failed_requests += 1
            await self._put(queue, {"type": "error", "request_id": request_id,
                "code": "inference_failed", "error_type": self.error_type}, cancel)
        finally:
            if cancel.is_set() and not completed:
                self.cancelled_requests += 1
            self.busy = False

    def begin(self, pcm, request_id):
        # Called on the event loop without an intervening await: no race between
        # simultaneous HTTP requests. A second request is rejected, never queued.
        if not self.ready:
            raise HTTPException(503, detail={"code": "worker_not_ready", "reason": self.reason})
        if self.busy:
            raise HTTPException(429, detail={"code": "worker_busy"}, headers={"Retry-After": "1"})
        self.busy = True
        queue = asyncio.Queue(maxsize=1)
        cancel = threading.Event()
        self._cancel = cancel
        task = asyncio.create_task(self._produce(pcm, request_id, queue, cancel))
        self._task = task
        return queue, cancel, task

    async def stream(self, request, pcm, request_id):
        queue, cancel, producer = self.begin(pcm, request_id)

        async def body():
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        if producer.done():
                            return
                        continue
                    if await request.is_disconnected():
                        return
                    yield json.dumps(item, separators=(",", ":")) + "\n"
                    if item["type"] in {"done", "error"}:
                        return
            finally:
                cancel.set()

        return RenderResponse(body(), cancel)

    async def close(self):
        if self._cancel:
            self._cancel.set()
        if self._task:
            await asyncio.shield(self._task)


def create_app(settings=None, backend=None):
    settings = settings or Settings.from_env()
    worker = Worker(settings, backend or FlashHeadBackend(settings))

    @asynccontextmanager
    async def lifespan(_app):
        await worker.start()
        yield
        await worker.close()

    app = FastAPI(title="SoulForge Avatar Worker", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.worker = worker

    @app.get("/health")
    async def health():
        return worker.health()

    @app.post("/render")
    async def render(request: Request):
        if not settings.token:
            raise HTTPException(503, detail={"code": "worker_not_configured"})
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {settings.token}".encode()):
            raise HTTPException(401, detail={"code": "unauthorized"}, headers={"WWW-Authenticate": "Bearer"})
        # Bound the decoded and encoded body before parsing. No client-controlled
        # model paths, images, gaze, prompts or arbitrary options are accepted.
        limit = 4 * math.ceil(worker.max_samples * 2 / 3) + 1024
        received = bytearray()
        async for part in request.stream():
            received.extend(part)
            if len(received) > limit:
                raise HTTPException(413, detail={"code": "audio_too_large"})
        try:
            data = json.loads(received)
            if (not isinstance(data, dict) or set(data) != {"request_id", "audio_base64", "sample_rate"}
                    or not isinstance(data["request_id"], str)
                    or REQUEST_ID.fullmatch(data["request_id"]) is None
                    or type(data["sample_rate"]) is not int or data["sample_rate"] != 16000
                    or not isinstance(data["audio_base64"], str)):
                raise ValueError("Invalid request")
            pcm = base64.b64decode(data["audio_base64"], validate=True)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise HTTPException(422, detail={"code": "invalid_render_request"}) from None
        if (not pcm or len(pcm) % (worker.geometry.block_samples * 2)
                or len(pcm) // 2 > worker.max_samples):
            raise HTTPException(422, detail={"code": "audio_requires_whole_blocks",
                "sample_rate": 16000, "block_samples": worker.geometry.block_samples,
                "max_audio_samples": worker.max_samples})
        return await worker.stream(request, pcm, data["request_id"])

    return app
