"""Xiaozhi ESP32 protocol adapter.

Implements the WebSocket protocol used by xiaozhi-esp32 firmware.
Reference: github.com/78/xiaozhi-esp32
"""

import json
import logging

from fastapi import WebSocket

from gateway.protocols.base import (
    InboundMessage,
    MessageType,
    OutboundMessage,
    ProtocolAdapter,
)

logger = logging.getLogger(__name__)


class XiaozhiAdapter(ProtocolAdapter):
    """Protocol adapter for xiaozhi-esp32 devices.

    Xiaozhi protocol overview:
    - Text frames: JSON messages for control/auth
    - Binary frames: Raw audio data (16kHz 16bit PCM)
    - Auth: device sends {"type":"hello","device_id":"...",...} on connect
    """

    @property
    def name(self) -> str:
        return "xiaozhi"

    async def detect(self, ws: WebSocket, initial_data: bytes | str) -> bool:
        """Detect xiaozhi protocol by looking for 'hello' message."""
        if isinstance(initial_data, str):
            try:
                msg = json.loads(initial_data)
                return msg.get("type") == "hello"
            except (json.JSONDecodeError, AttributeError):
                return False
        return False

    async def handshake(self, ws: WebSocket, initial_data: bytes | str) -> str:
        """Handle xiaozhi handshake, return device_id."""
        msg = json.loads(initial_data)
        device_id = msg.get("device_id", "")

        if not device_id:
            raise ValueError("Missing device_id in hello message")

        # Send hello response
        response = {
            "type": "hello",
            "session_id": "",  # will be set by session manager
            "transport": "websocket",
        }
        await ws.send_text(json.dumps(response))

        logger.info(f"Xiaozhi device connected: {device_id}")
        return device_id

    async def decode(self, raw_data: bytes | str) -> InboundMessage:
        """Decode xiaozhi frame."""
        if isinstance(raw_data, bytes):
            # Binary frame = audio data
            return InboundMessage(
                type=MessageType.AUDIO,
                device_id="",  # set by session context
                payload=raw_data,
            )

        # Text frame = JSON control message
        msg = json.loads(raw_data)
        msg_type = msg.get("type", "")

        if msg_type == "listen":
            # Device is sending audio (start/stop listening)
            state = msg.get("state", "")
            return InboundMessage(
                type=MessageType.CONTROL,
                device_id="",
                payload={"action": "listen", "state": state},
                metadata=msg,
            )
        elif msg_type == "abort":
            return InboundMessage(
                type=MessageType.CONTROL,
                device_id="",
                payload={"action": "abort"},
            )
        elif msg_type == "iot":
            return InboundMessage(
                type=MessageType.CONTROL,
                device_id="",
                payload={"action": "iot", "data": msg.get("descriptors", {})},
            )
        else:
            return InboundMessage(
                type=MessageType.TEXT,
                device_id="",
                payload=msg,
            )

    async def encode(self, message: OutboundMessage) -> bytes | str:
        """Encode message for xiaozhi device."""
        if message.type == MessageType.AUDIO:
            # Send raw audio bytes
            if isinstance(message.payload, bytes):
                return message.payload
            raise ValueError("Audio payload must be bytes")

        # Control/text messages as JSON
        if message.type == MessageType.CONTROL:
            return json.dumps(message.payload)

        if message.type == MessageType.TEXT:
            # TTS text response format
            return json.dumps({
                "type": "tts",
                "state": message.metadata.get("state", "start"),
                "text": message.payload if isinstance(message.payload, str) else "",
            })

        return json.dumps({"type": "unknown"})
