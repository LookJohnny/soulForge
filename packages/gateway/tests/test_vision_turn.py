"""Tests for the per-turn camera vision flow (trigger -> capture -> pipeline)."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gateway.protocols.generic_ws import GenericWSAdapter
from gateway.server import WebSocketServer


def _server():
    return WebSocketServer.__new__(WebSocketServer)


def test_vision_trigger_positive():
    s = _server()
    assert s._is_vision_trigger("你看看这是什么东西")
    assert s._is_vision_trigger("帮我看看 我手里拿的")
    assert s._is_vision_trigger("猜猜这是什么")


def test_vision_trigger_negative():
    s = _server()
    assert not s._is_vision_trigger("今天天气怎么样")
    assert not s._is_vision_trigger("")
    assert not s._is_vision_trigger(None)


async def test_request_frame_roundtrip():
    s = _server()
    ws = AsyncMock()
    adapter = GenericWSAdapter()
    session = SimpleNamespace(device_id="pi-test")

    async def device_replies():
        await asyncio.sleep(0.05)
        session._pending_frame.set_result("ZmFrZWpwZWc=")

    reply_task = asyncio.create_task(device_replies())
    frame = await s._request_frame(ws, adapter, session, timeout_s=2.0)
    await reply_task

    assert frame == "ZmFrZWpwZWc="
    sent = json.loads(ws.send_text.await_args.args[0])
    assert sent["payload"]["type"] == "capture"
    assert session._pending_frame is None  # cleaned up


async def test_request_frame_timeout_returns_none():
    s = _server()
    ws = AsyncMock()
    adapter = GenericWSAdapter()
    session = SimpleNamespace(device_id="pi-test")
    frame = await s._request_frame(ws, adapter, session, timeout_s=0.05)
    assert frame is None
    assert session._pending_frame is None


async def test_vision_frame_text_message_resolves_future():
    from gateway.protocols.base import InboundMessage, MessageType

    s = _server()
    session = SimpleNamespace(device_id="pi-test")
    session._pending_frame = asyncio.get_running_loop().create_future()
    msg = InboundMessage(
        type=MessageType.TEXT,
        device_id="pi-test",
        payload={"type": "vision_frame", "data": "QUJD"},
    )
    await s._handle_message(AsyncMock(), GenericWSAdapter(), session, msg)
    assert session._pending_frame.result() == "QUJD"


async def test_generic_ws_decodes_vision_frame_as_dict():
    from gateway.protocols.base import MessageType

    adapter = GenericWSAdapter()
    msg = await adapter.decode(json.dumps({"type": "vision_frame", "data": "QUJD"}))
    assert msg.type == MessageType.TEXT
    assert msg.payload == {"type": "vision_frame", "data": "QUJD"}
