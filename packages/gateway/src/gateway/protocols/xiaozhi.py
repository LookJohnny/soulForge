"""Xiaozhi ESP32 protocol adapter.

Implements the WebSocket protocol used by xiaozhi-esp32 firmware.
Reference: github.com/78/xiaozhi-esp32

Audio format: Xiaozhi sends/receives Opus audio (OGG container, 16kHz mono).
This adapter transparently converts:
  - Incoming: Opus → PCM 16kHz 16-bit mono (for ASR)
  - Outgoing: MP3 (from TTS) → Opus (for device playback)
"""

import json
import logging
import uuid

from fastapi import WebSocket

from gateway.handlers.audio_codec import is_opus, is_mp3, mp3_to_pcm, pcm_to_opus_frames
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
    - Binary frames: Opus audio data (16kHz mono, OGG container)
    - Auth: device sends {"type":"hello","device_id":"...",...} on connect
    """

    def __init__(self):
        self._device_audio_format: str = "opus"  # xiaozhi default

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
        """Handle xiaozhi handshake, return device_id.

        Xiaozhi v2 firmware sends device_id via WebSocket HTTP headers
        (Device-Id / Client-Id), not in the hello JSON body.
        """
        msg = json.loads(initial_data)
        logger.info("xiaozhi.hello: %s", json.dumps(msg, ensure_ascii=False)[:500])

        # Device ID from hello body (older firmware) or WebSocket headers (v2+)
        device_id = msg.get("device_id", "")
        if not device_id:
            # v2 firmware: device_id in WebSocket upgrade headers
            headers = dict(ws.headers) if hasattr(ws, "headers") else {}
            device_id = (
                headers.get("device-id")
                or headers.get("client-id")
                or headers.get("mac-address")
                or ""
            )
            logger.info("xiaozhi.headers: %s", {k: v for k, v in headers.items() if k in (
                "device-id", "client-id", "authorization", "protocol-version", "user-agent"
            )})

        if not device_id:
            raise ValueError(f"Missing device_id in hello/headers: keys={list(msg.keys())}")

        # Read device's audio format preference from hello message
        audio_params = msg.get("audio_params", {})
        self._device_audio_format = audio_params.get("format", "opus")

        # Send hello response with a valid session_id
        self._session_id = str(uuid.uuid4())
        response = {
            "type": "hello",
            "session_id": self._session_id,
            "transport": "websocket",
        }
        await ws.send_text(json.dumps(response))

        logger.info(
            "Xiaozhi device connected: %s (audio: %s)",
            device_id, self._device_audio_format,
        )
        return device_id

    async def decode(self, raw_data: bytes | str) -> InboundMessage:
        """Decode xiaozhi frame. Audio is passed as-is (Opus frames)."""
        if isinstance(raw_data, bytes):
            # Pass raw Opus frames directly — ASR supports Opus natively
            return InboundMessage(
                type=MessageType.AUDIO,
                device_id="",  # set by session context
                payload=raw_data,
            )

        # Text frame = JSON control message
        msg = json.loads(raw_data)
        msg_type = msg.get("type", "")

        if msg_type == "listen":
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
        elif msg_type == "touch":
            return InboundMessage(
                type=MessageType.TOUCH,
                device_id="",
                payload={
                    "gesture": msg.get("gesture", "none"),
                    "zone": msg.get("zone"),
                    "pressure": msg.get("pressure"),
                    "duration_ms": msg.get("duration_ms"),
                },
                metadata=msg,
            )
        else:
            return InboundMessage(
                type=MessageType.TEXT,
                device_id="",
                payload=msg,
            )

    async def encode(self, message: OutboundMessage) -> bytes | str:
        """Encode message for xiaozhi device. MP3 audio is re-encoded to Opus."""
        if message.type == MessageType.AUDIO:
            if isinstance(message.payload, bytes):
                audio = message.payload
                # Convert MP3 (from TTS) to raw Opus frames for xiaozhi playback.
                # The device expects individual Opus packets, NOT MP3/OGG containers.
                if is_mp3(audio):
                    pcm = await mp3_to_pcm(audio)
                    if pcm:
                        frames = pcm_to_opus_frames(pcm, frame_duration_ms=60)
                        # Return list of frames — server.py will send each as a binary msg
                        return frames
                    return []
                return audio
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
