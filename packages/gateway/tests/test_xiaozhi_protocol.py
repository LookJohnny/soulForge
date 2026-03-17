"""Tests for the Xiaozhi protocol adapter."""

import json
import pytest
from unittest.mock import AsyncMock

from gateway.protocols.xiaozhi import XiaozhiAdapter
from gateway.protocols.base import MessageType


@pytest.fixture
def adapter():
    return XiaozhiAdapter()


async def test_detect_hello_message(adapter):
    ws = AsyncMock()
    data = json.dumps({"type": "hello", "device_id": "AA:BB:CC:DD:EE:FF"})
    assert await adapter.detect(ws, data) is True


async def test_detect_non_hello_message(adapter):
    ws = AsyncMock()
    assert await adapter.detect(ws, '{"type": "other"}') is False
    assert await adapter.detect(ws, b"\x00\x01\x02") is False
    assert await adapter.detect(ws, "not json") is False


async def test_decode_audio_bytes(adapter):
    audio = b"\x00\x01\x02\x03" * 100
    msg = await adapter.decode(audio)
    assert msg.type == MessageType.AUDIO
    assert msg.payload == audio


async def test_decode_listen_start(adapter):
    data = json.dumps({"type": "listen", "state": "start"})
    msg = await adapter.decode(data)
    assert msg.type == MessageType.CONTROL
    assert msg.payload["action"] == "listen"
    assert msg.payload["state"] == "start"


async def test_decode_listen_stop(adapter):
    data = json.dumps({"type": "listen", "state": "stop"})
    msg = await adapter.decode(data)
    assert msg.type == MessageType.CONTROL
    assert msg.payload["state"] == "stop"


async def test_decode_abort(adapter):
    data = json.dumps({"type": "abort"})
    msg = await adapter.decode(data)
    assert msg.type == MessageType.CONTROL
    assert msg.payload["action"] == "abort"


async def test_encode_audio(adapter):
    from gateway.protocols.base import OutboundMessage

    audio = b"\x00\x01" * 50
    msg = OutboundMessage(type=MessageType.AUDIO, payload=audio)
    result = await adapter.encode(msg)
    assert result == audio


async def test_encode_text(adapter):
    from gateway.protocols.base import OutboundMessage

    msg = OutboundMessage(
        type=MessageType.TEXT,
        payload="Hello!",
        metadata={"state": "sentence"},
    )
    result = await adapter.encode(msg)
    parsed = json.loads(result)
    assert parsed["type"] == "tts"
    assert parsed["text"] == "Hello!"
    assert parsed["state"] == "sentence"
