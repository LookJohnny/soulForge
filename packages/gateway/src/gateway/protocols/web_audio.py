"""Web Audio protocol adapter — browser WebAudio API for development/testing."""

import json

from fastapi import WebSocket

from gateway.protocols.base import (
    InboundMessage,
    MessageType,
    OutboundMessage,
    ProtocolAdapter,
)


class WebAudioAdapter(ProtocolAdapter):
    """Browser-based WebSocket protocol for development and testing.

    Protocol:
    - Text frames: JSON messages
    - Binary frames: Raw PCM audio chunks (16kHz 16bit mono)

    Handshake:
    Client sends: {"type": "web_hello", "session_name": "browser-test"}
    Server responds: {"type": "web_hello", "session_id": "..."}

    Messages:
    - {"type": "text", "content": "..."} — text input
    - {"type": "listen", "state": "start|stop"} — audio recording control
    - Binary frames — raw PCM audio data
    """

    name = "web_audio"
    description = "Browser WebAudio API adapter for development"

    async def detect(self, ws: WebSocket, initial_data: str | bytes) -> bool:
        if isinstance(initial_data, str):
            try:
                msg = json.loads(initial_data)
                return msg.get("type") == "web_hello"
            except (json.JSONDecodeError, AttributeError):
                return False
        return False

    async def handshake(self, ws: WebSocket, initial_data: str | bytes) -> str:
        msg = json.loads(initial_data)
        session_name = msg.get("session_name", "browser")
        device_id = f"web_{session_name}"

        response = json.dumps({
            "type": "web_hello",
            "device_id": device_id,
            "protocol": self.name,
        })
        await ws.send_text(response)

        return device_id

    async def decode(self, raw_data: str | bytes) -> InboundMessage:
        if isinstance(raw_data, bytes):
            return InboundMessage(type=MessageType.AUDIO, payload=raw_data)

        msg = json.loads(raw_data)
        msg_type = msg.get("type", "")

        if msg_type == "text":
            return InboundMessage(
                type=MessageType.TEXT,
                payload=msg.get("content", ""),
            )
        elif msg_type == "listen":
            return InboundMessage(
                type=MessageType.CONTROL,
                payload={"action": "listen", "state": msg.get("state", "")},
            )
        elif msg_type == "abort":
            return InboundMessage(
                type=MessageType.CONTROL,
                payload={"action": "abort"},
            )
        elif msg_type == "heartbeat":
            return InboundMessage(type=MessageType.HEARTBEAT, payload=None)
        else:
            return InboundMessage(type=MessageType.TEXT, payload=str(raw_data))

    async def encode(self, message: OutboundMessage) -> str | bytes:
        if message.type == MessageType.AUDIO:
            # Send raw PCM/WAV bytes directly
            if isinstance(message.payload, bytes):
                return message.payload
            return b""

        state = ""
        if message.metadata:
            state = message.metadata.get("state", "")

        if message.type == MessageType.TEXT:
            return json.dumps({
                "type": "text",
                "content": message.payload,
                "state": state,
            })
        elif message.type == MessageType.CONTROL:
            return json.dumps({
                "type": "control",
                "payload": message.payload,
            })

        return json.dumps({"type": "unknown"})
