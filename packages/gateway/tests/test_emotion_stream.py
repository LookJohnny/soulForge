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


def test_parse_relationship_event():
    payload = {
        "type": "relationship",
        "stage": "FRIEND",
        "app_mode": "dating_sim",
        "axes": {
            "affection": 312,
            "trust": 54,
            "intimacy": 12,
            "comfort": 40,
            "respect": 30,
            "energy": 88,
        },
        "deltas": {"affection": 4},
        "stage_changed": False,
        "from_stage": None,
    }
    chunk = PipelineOrchestrator._parse_stream_event(payload)
    assert chunk is not None
    assert chunk.kind == "relationship"
    assert chunk.is_done is False
    assert chunk.relationship == payload


async def test_relationship_chunk_forwarded_as_control():
    from gateway.server import WebSocketServer

    server = WebSocketServer.__new__(WebSocketServer)
    ws = AsyncMock()
    adapter = GenericWSAdapter()
    chunk = PipelineOrchestrator._parse_stream_event(
        {"type": "relationship", "stage": "DATING", "axes": {"affection": 640}}
    )
    await server._send_relationship(ws, adapter, chunk)
    ws.send_text.assert_awaited_once()
    sent = json.loads(ws.send_text.await_args.args[0])
    assert sent["type"] == MessageType.CONTROL.value
    assert sent["payload"]["type"] == "relationship"
    assert sent["payload"]["stage"] == "DATING"


def test_parse_emotion_event_with_causes_and_energy():
    chunk = PipelineOrchestrator._parse_stream_event(
        {
            "type": "emotion",
            "emotion": "happy",
            "pad": {"p": 0.5, "a": 0.3, "d": 0.6},
            "causes": ["你记得我的生日"],
            "energy": 77,
        }
    )
    assert chunk.causes == ["你记得我的生日"] and chunk.energy == 77


async def test_server_send_emotion_forwards_causes():
    from gateway.server import WebSocketServer

    server = WebSocketServer.__new__(WebSocketServer)
    ws = AsyncMock()
    chunk = PipelineOrchestrator._parse_stream_event(
        {"type": "emotion", "emotion": "happy", "causes": ["想你了"], "energy": 60}
    )
    await server._send_emotion(ws, GenericWSAdapter(), chunk)
    sent = json.loads(ws.send_text.await_args.args[0])
    assert sent["payload"]["causes"] == ["想你了"] and sent["payload"]["energy"] == 60


def test_parse_event_chunk_and_web_audio_choice_decode():
    import asyncio

    from gateway.protocols.web_audio import WebAudioAdapter

    chunk = PipelineOrchestrator._parse_stream_event(
        {"type": "event", "event_id": "confession_event", "scene": {"choices": [{"text": "a"}]}}
    )
    assert chunk.kind == "event" and chunk.event["event_id"] == "confession_event"
    msg = asyncio.run(
        WebAudioAdapter().decode(
            json.dumps({"type": "event_choice", "event_id": "x", "choice_index": "1"})
        )
    )
    assert msg.type == MessageType.CONTROL
    assert msg.payload == {"action": "event_choice", "event_id": "x", "choice_index": 1}
    mode = asyncio.run(
        WebAudioAdapter().decode(json.dumps({"type": "set_app_mode", "app_mode": "companion"}))
    )
    assert mode.payload == {"action": "set_app_mode", "app_mode": "companion"}
