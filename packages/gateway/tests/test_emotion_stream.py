"""Tests for emotion event flow: ai-core SSE -> StreamChunk -> device control."""

import json
from unittest.mock import AsyncMock

from gateway.pipeline.orchestrator import PipelineOrchestrator
from gateway.protocols.base import MessageType
from gateway.protocols.generic_ws import GenericWSAdapter


def test_parse_emotion_event():
    chunk = PipelineOrchestrator._parse_stream_event(
        {
            "type": "emotion",
            "emotion": "happy",
            "pad": {"p": 0.5, "a": 0.3, "d": 0.6},
            "hardware": {"led": {"expression": "happy"}},
        }
    )
    assert chunk is not None
    assert chunk.kind == "emotion"
    assert chunk.is_done is False
    assert chunk.emotion == "happy"
    assert chunk.pad == {"p": 0.5, "a": 0.3, "d": 0.6}
    assert chunk.hardware == {"led": {"expression": "happy"}}


def test_parse_emotion_event_minimal():
    chunk = PipelineOrchestrator._parse_stream_event({"type": "emotion"})
    assert chunk is not None
    assert chunk.kind == "emotion"
    assert chunk.emotion == ""
    assert chunk.pad is None
    assert chunk.hardware is None


def test_parse_unknown_event_still_dropped():
    assert PipelineOrchestrator._parse_stream_event({"type": "mystery"}) is None


async def test_server_send_emotion_encodes_control():
    from gateway.server import WebSocketServer

    server = WebSocketServer.__new__(WebSocketServer)  # no full init needed
    ws = AsyncMock()
    adapter = GenericWSAdapter()
    chunk = PipelineOrchestrator._parse_stream_event(
        {"type": "emotion", "emotion": "curious", "pad": {"p": 0.1, "a": 0.4, "d": 0.2}}
    )
    await server._send_emotion(ws, adapter, chunk)

    ws.send_text.assert_awaited_once()
    sent = json.loads(ws.send_text.await_args.args[0])
    assert sent["type"] == "control"
    assert sent["payload"]["type"] == "emotion"
    assert sent["payload"]["emotion"] == "curious"
    assert sent["payload"]["pad"] == {"p": 0.1, "a": 0.4, "d": 0.2}


async def test_server_send_emotion_swallows_ws_errors():
    from gateway.server import WebSocketServer

    server = WebSocketServer.__new__(WebSocketServer)
    ws = AsyncMock()
    ws.send_text.side_effect = RuntimeError("socket closed")
    adapter = GenericWSAdapter()
    chunk = PipelineOrchestrator._parse_stream_event({"type": "emotion", "emotion": "happy"})
    await server._send_emotion(ws, adapter, chunk)  # must not raise
    assert MessageType.CONTROL is not None
