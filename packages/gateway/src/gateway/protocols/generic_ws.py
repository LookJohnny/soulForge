"""Generic WebSocket JSON protocol adapter — universal fallback."""

import json

from fastapi import WebSocket

from gateway.protocols.base import (
    InboundMessage,
    MessageType,
    OutboundMessage,
    ProtocolAdapter,
)


class GenericWSAdapter(ProtocolAdapter):
    """Generic WebSocket JSON protocol for any client.

    Protocol (all JSON text frames):
    - {"action": "hello", "device_id": "..."} — handshake
    - {"action": "chat", "text": "..."} — text message
    - {"action": "listen", "state": "start|stop"} — audio control
    - {"action": "abort"} — cancel current operation
    - {"action": "ping"} — heartbeat

    Binary frames: raw PCM audio data.
    """

    name = "generic_ws"
    description = "Generic WebSocket JSON protocol"

    async def detect(self, ws: WebSocket, initial_data: str | bytes) -> bool:
        if isinstance(initial_data, str):
            try:
                msg = json.loads(initial_data)
                return msg.get("action") == "hello"
            except (json.JSONDecodeError, AttributeError):
                return False
        return False

    async def handshake(self, ws: WebSocket, initial_data: str | bytes) -> str:
        msg = json.loads(initial_data)
        device_id = msg.get("device_id", "generic_unknown")

        response = json.dumps({
            "action": "hello",
            "status": "ok",
            "device_id": device_id,
            "protocol": self.name,
        })
        await ws.send_text(response)

        return device_id

    async def decode(self, raw_data: str | bytes) -> InboundMessage:
        if isinstance(raw_data, bytes):
            return InboundMessage(type=MessageType.AUDIO, device_id="", payload=raw_data)

        msg = json.loads(raw_data)
        action = msg.get("action", "")

        if action == "chat":
            return InboundMessage(
                type=MessageType.TEXT,
                device_id="",
                payload=msg.get("text", ""),
            )
        elif action == "listen":
            return InboundMessage(
                type=MessageType.CONTROL,
                device_id="",
                payload={"action": "listen", "state": msg.get("state", "")},
            )
        elif action == "abort":
            return InboundMessage(
                type=MessageType.CONTROL,
                device_id="",
                payload={"action": "abort"},
            )
        elif action == "touch":
            return InboundMessage(
                type=MessageType.TOUCH,
                device_id="",
                payload={
                    "gesture": msg.get("gesture", "none"),
                    "zone": msg.get("zone"),
                    "pressure": msg.get("pressure"),
                    "duration_ms": msg.get("duration_ms"),
                },
            )
        elif action == "ping":
            return InboundMessage(type=MessageType.HEARTBEAT, device_id="", payload=None)
        else:
            return InboundMessage(type=MessageType.TEXT, device_id="", payload=str(raw_data))

    async def encode(self, message: OutboundMessage) -> str | bytes:
        if message.type == MessageType.AUDIO:
            if isinstance(message.payload, bytes):
                return message.payload
            return b""

        state = ""
        if message.metadata:
            state = message.metadata.get("state", "")

        if message.type == MessageType.TEXT:
            return json.dumps({
                "type": "response",
                "text": message.payload,
                "state": state,
            })
        elif message.type == MessageType.CONTROL:
            return json.dumps({
                "type": "control",
                "payload": message.payload,
            })

        return json.dumps({"type": "unknown"})
