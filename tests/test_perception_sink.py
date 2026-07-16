"""RuntimePerceptionSink transport regression tests."""

import asyncio

import pytest
import websockets

from engine.perception import PerceptionEvent, RuntimePerceptionSink
from engine.server.protocol import Event as WireEvent
from engine.server.protocol import decode


@pytest.mark.asyncio
async def test_runtime_perception_sink_sends_structured_wire_event():
    received = []

    async def handler(socket):
        received.append(decode(await socket.recv()))

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        sink = RuntimePerceptionSink(f"ws://127.0.0.1:{port}")
        await sink.start()
        try:
            sink.emit(PerceptionEvent(
                kind="object_detected",
                modality="vision",
                timestamp=1.0,
                captured_at=1.0,
                source_body="camera",
                target_agent="kai",
                text="cup detected",
                confidence=0.8,
                media_ref="camera://frame/1",
            ))
            await asyncio.wait_for(sink.drain(), timeout=1)
        finally:
            await sink.close()

    assert len(received) == 1
    assert isinstance(received[0], WireEvent)
    assert received[0].kind == "object_detected"
    assert received[0].payload["confidence"] == 0.8
    assert sink.health()["sent"] == 1


@pytest.mark.asyncio
async def test_runtime_perception_sink_fails_start_when_runtime_is_unreachable():
    # Port 1 is intentionally unreachable in the test environment.
    sink = RuntimePerceptionSink("ws://127.0.0.1:1")
    with pytest.raises(OSError):
        await sink.start()
    assert sink.health()["running"] is False
