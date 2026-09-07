"""Fake upstreams are test fixtures only; RTC itself uses real local peers/codecs."""
import asyncio
import base64
from contextlib import asynccontextmanager
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
import numpy as np
import pytest

from media_body.server import Settings, make_app
from test_media import jpeg

TOKEN = "test-only-media-token-000000000000"
OWNER = str(uuid4())


class Gateway:
    def __init__(self):
        self.turns, self.receipts, self.interrupts, self.closed = [], [], [], []
        self.second_waiting = asyncio.Event()

    async def health(self, path):
        return {"ready": True, "readiness_scope": "configuration_only"}

    async def open(self, body_id):
        return str(uuid4())

    async def turn(self, sid, turn_id, text):
        self.turns.append((sid, turn_id, text))
        yield {"type": "decision", "turn_id": turn_id, "emotion": "calm"}
        pcm = (np.sin(np.arange(16000) * 2 * np.pi * 440 / 16000) * 6000).astype(np.int16).tobytes()
        yield {"type": "audio", "turn_id": turn_id, "text": text, "audio_base64": base64.b64encode(pcm).decode(),
               "format": "pcm16", "receipt_id": "receipt-" + turn_id}
        if text == "wait":
            self.second_waiting.set()
            await asyncio.sleep(60)
        yield {"type": "done", "turn_id": turn_id}

    async def receipt(self, sid, receipt_id, played=False):
        self.receipts.append(played)

    async def interrupt(self, sid, turn_id):
        self.interrupts.append(turn_id)

    async def close(self, sid):
        self.closed.append(sid)


class Worker:
    ready = True
    corrupt = False

    async def health(self):
        return {"ready": self.ready, "sample_rate": 16000, "fps": 25, "block_samples": 16000,
                "model": "TEST FIXTURE ONLY"}

    async def render(self, request_id, pcm):
        yield {"type": "chunk", "request_id": request_id, "start_sample": 1 if self.corrupt else 0,
               "sample_count": 16000, "sample_rate": 16000, "fps": 25,
               "frames": [jpeg()] * 25, "frame_count": 25}
        yield {"type": "done", "request_id": request_id}


@asynccontextmanager
async def server(worker=None):
    gateway = Gateway()
    app = await make_app(Settings(token=TOKEN, gateway_token="gateway", worker_token="worker"), gateway, worker or Worker())
    async with TestClient(TestServer(app)) as client:
        yield client, gateway, app["service"]


def auth():
    return {"Authorization": "Bearer " + TOKEN}


async def connect(client):
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    channel = pc.createDataChannel("events", ordered=True)
    pc.addTransceiver("audio", direction="recvonly")
    pc.addTransceiver("video", direction="recvonly")
    tracks, events = {}, []

    @pc.on("track")
    def track(value):
        tracks[value.kind] = value

    @channel.on("message")
    def message(value):
        import json
        events.append(json.loads(value))

    await pc.setLocalDescription(await pc.createOffer())
    result = await client.post("/sessions", headers=auth(), json={"client_id": OWNER,
                              "type": "offer", "sdp": pc.localDescription.sdp})
    assert result.status == 200, await result.text()
    data = await result.json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type="answer"))
    for _ in range(100):
        if pc.connectionState == "connected" and channel.readyState == "open":
            break
        await asyncio.sleep(.02)
    assert pc.connectionState == "connected"
    return pc, data["session_id"], tracks, events


async def test_no_gpu_blocks_session_and_auth_is_required():
    worker = Worker()
    worker.ready = False
    async with server(worker) as (client, gateway, service):
        assert (await client.get("/health")).status == 401
        health = await (await client.get("/health", headers=auth())).json()
        assert not health["ready"]
        result = await client.post("/sessions", headers=auth(), json={"client_id": OWNER, "type": "offer", "sdp": "fake"})
        assert result.status == 503
        assert not gateway.turns and not service.sessions


async def test_real_webrtc_video_audio_and_cancel_epoch():
    async with server() as (client, gateway, service):
        pc, sid, tracks, events = await connect(client)
        try:
            result = await client.post(f"/sessions/{sid}/turn", headers=auth(), json={"client_id": str(uuid4()), "text": "foreign"})
            assert result.status == 404
            result = await client.post(f"/sessions/{sid}/turn", headers=auth(), json={"client_id": OWNER, "text": "hello"})
            assert result.status == 200
            first_epoch = (await result.json())["epoch"]
            video = await asyncio.wait_for(tracks["video"].recv(), 5)
            assert video.width == video.height == 64
            color = video.to_ndarray(format="rgb24")[20, 20]
            assert color[2] > color[0] + 50
            async def speech():
                while True:
                    frame = await tracks["audio"].recv()
                    if np.max(np.abs(frame.to_ndarray().astype(np.float32))) > 100:
                        return frame
            assert (await asyncio.wait_for(speech(), 5)).samples > 0
            await asyncio.wait_for(service.sessions[sid].task, 5)
            assert gateway.receipts == [False]  # sending is not hearing
            assert len(gateway.turns) == 1
            result = await client.post(f"/sessions/{sid}/turn", headers=auth(), json={"client_id": OWNER, "text": "wait"})
            await asyncio.wait_for(gateway.second_waiting.wait(), 5)
            result = await client.post(f"/sessions/{sid}/interrupt", headers=auth(), json={"client_id": OWNER})
            assert result.status == 200
            cancelled_epoch = (await result.json())["epoch"]
            assert cancelled_epoch > first_epoch
            await asyncio.sleep(.1)
            assert service.sessions[sid].task is None
            assert not service.sessions[sid].playout.cells
            assert any(event["type"] == "cancelled" and event["epoch"] == cancelled_epoch for event in events)
            assert all(event["session_id"] == sid for event in events)
            result = await client.post(f"/sessions/{sid}/close", headers=auth(), json={"client_id": OWNER})
            assert result.status == 200 and not service.sessions
            assert gateway.closed
        finally:
            await pc.close()


async def test_misaligned_gpu_never_plays_audio():
    worker = Worker()
    worker.corrupt = True
    async with server(worker) as (client, gateway, service):
        pc, sid, tracks, events = await connect(client)
        try:
            result = await client.post(f"/sessions/{sid}/turn", headers=auth(), json={"client_id": OWNER, "text": "broken"})
            assert result.status == 200
            await asyncio.wait_for(service.sessions[sid].task, 5)
            await asyncio.sleep(.1)
            assert not service.sessions[sid].playout.cells
            assert service.sessions[sid].playout.video.queue.empty()
            assert not gateway.receipts
            assert any(event["type"] == "error" for event in events)
        finally:
            await pc.close()


@pytest.mark.parametrize("url", ["http://gpu.example", "https://key@gpu.example", "https://gpu.example/path"])
def test_reject_unsafe_worker_urls(url):
    with pytest.raises(ValueError):
        Settings(token=TOKEN, worker_url=url).validate()


async def test_interrupt_ack_does_not_wait_for_remote_cleanup():
    async with server() as (client, gateway, service):
        pc, sid, tracks, events = await connect(client)
        released = asyncio.Event()
        original = gateway.interrupt

        async def delayed(*args):
            await released.wait()
            return await original(*args)

        gateway.interrupt = delayed
        try:
            await client.post(f"/sessions/{sid}/turn", headers=auth(), json={"client_id": OWNER, "text": "wait"})
            await asyncio.wait_for(gateway.second_waiting.wait(), 5)
            response = await asyncio.wait_for(client.post(f"/sessions/{sid}/interrupt", headers=auth(), json={"client_id": OWNER}), .3)
            assert response.status == 200
            assert not service.sessions[sid].playout.cells
            # A new turn can be submitted while cleanup finishes, but cognition
            # must not be called until the old runtime turn is retired.
            await client.post(f"/sessions/{sid}/turn", headers=auth(), json={"client_id": OWNER, "text": "next"})
            await asyncio.sleep(.05)
            assert len(gateway.turns) == 1
            released.set()
            await asyncio.wait_for(service.sessions[sid].task, 5)
            assert len(gateway.turns) == 2
        finally:
            released.set()
            await pc.close()


async def test_create_retry_returns_same_session_without_second_brain():
    async with server() as (client, gateway, service):
        pc, sid, tracks, events = await connect(client)
        try:
            response = await client.post("/sessions", headers=auth(), json={"client_id": OWNER,
                "type": "offer", "sdp": pc.localDescription.sdp})
            assert response.status == 200
            assert (await response.json())["session_id"] == sid
            assert len(service.sessions) == 1
        finally:
            await pc.close()


async def test_worker_busy_waits_before_spending_a_brain_turn():
    class BusyWorker(Worker):
        busy = True
        async def health(self):
            return {**await super().health(), "busy": self.busy}

    worker = BusyWorker()
    async with server(worker) as (client, gateway, service):
        pc, sid, tracks, events = await connect(client)
        try:
            await client.post(f"/sessions/{sid}/turn", headers=auth(), json={"client_id": OWNER, "text": "hello"})
            await asyncio.sleep(.1)
            assert gateway.turns == []
            worker.busy = False
            await asyncio.wait_for(service.sessions[sid].task, 5)
            assert len(gateway.turns) == 1
        finally:
            await pc.close()


async def test_close_owned_recovers_lost_create_without_touching_other_owner():
    async with server() as (client, gateway, service):
        pc, sid, tracks, events = await connect(client)
        try:
            response = await client.post("/sessions/close-owned", headers=auth(), json={"client_id": str(uuid4())})
            assert (await response.json())["closed"] == 0
            assert sid in service.sessions
            response = await client.post("/sessions/close-owned", headers=auth(), json={"client_id": OWNER})
            assert (await response.json())["closed"] == 1
            assert not service.sessions
        finally:
            await pc.close()


async def test_invalid_json_object_is_client_error():
    async with server() as (client, gateway, service):
        for body in ([], None, "text"):
            response = await client.post("/sessions", headers=auth(), json=body)
            assert response.status == 400
        assert not service.sessions
