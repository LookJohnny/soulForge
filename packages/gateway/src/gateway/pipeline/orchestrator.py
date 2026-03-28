"""Pipeline orchestrator - calls ai-core service for the full ASR->LLM->TTS chain.

Supports both blocking (/pipeline/chat) and streaming (/pipeline/chat/stream) modes.
Streaming mode yields per-sentence text+audio for low-latency playback.
"""

import base64
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from gateway.config import settings
from gateway.session import Session

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    """A single sentence chunk from the streaming pipeline."""
    text: str
    audio_data: bytes | None
    index: int
    is_done: bool = False
    # Only populated on the final 'done' chunk
    full_text: str = ""
    emotion: str = ""
    latency_ms: int = 0


class PipelineOrchestrator:
    def __init__(self):
        # Build headers for service-to-service auth
        headers = {}
        if settings.service_token:
            headers["X-Service-Token"] = settings.service_token

        # Use explicit transport to bypass system SOCKS proxy
        transport = httpx.AsyncHTTPTransport()
        self.client = httpx.AsyncClient(
            base_url=settings.ai_core_url,
            timeout=30.0,
            transport=transport,
            headers=headers,
        )
        # Separate client for streaming with longer timeout
        self.stream_client = httpx.AsyncClient(
            base_url=settings.ai_core_url,
            timeout=httpx.Timeout(60.0, connect=10.0),
            transport=httpx.AsyncHTTPTransport(),
            headers=headers,
        )

    async def process_audio(self, session: Session, audio_data: bytes) -> dict:
        """Send audio to ai-core pipeline, get text + audio response.

        Returns:
            {"text": str, "audio_data": bytes|None, "latency_ms": int}
        """
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "audio_data": base64.b64encode(audio_data).decode(),
        }

        # Include brand_id header for license checking
        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        resp = await self.client.post("/pipeline/chat", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        result = {
            "text": data["text"],
            "audio_data": None,
            "latency_ms": data.get("latency_ms", 0),
        }

        if data.get("audio_data"):
            result["audio_data"] = base64.b64decode(data["audio_data"])

        return result

    async def process_text(self, session: Session, text: str) -> dict:
        """Send text to ai-core pipeline (skip ASR)."""
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "text_input": text,
        }

        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        resp = await self.client.post("/pipeline/chat", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        result = {
            "text": data["text"],
            "audio_data": None,
            "latency_ms": data.get("latency_ms", 0),
        }

        if data.get("audio_data"):
            result["audio_data"] = base64.b64decode(data["audio_data"])

        return result

    async def process_touch(self, session: Session, touch_data: dict) -> dict | None:
        """Send touch event to ai-core, get optional text + audio response.

        Returns:
            {"text": str|None, "audio_data": bytes|None} or None
        """
        if not session.character_id:
            return None

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "gesture": touch_data.get("gesture", "none"),
            "zone": touch_data.get("zone"),
            "pressure": touch_data.get("pressure"),
            "duration_ms": touch_data.get("duration_ms"),
        }

        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        resp = await self.client.post("/pipeline/touch", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        result = {
            "text": data.get("text"),
            "audio_data": None,
        }

        if data.get("audio_data"):
            result["audio_data"] = base64.b64decode(data["audio_data"])

        return result

    async def process_audio_stream(
        self, session: Session, audio_data: bytes
    ) -> AsyncIterator[StreamChunk]:
        """Stream audio through AI pipeline, yielding per-sentence chunks."""
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "audio_data": base64.b64encode(audio_data).decode(),
        }

        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        async with self.stream_client.stream(
            "POST", "/pipeline/chat/stream", json=payload, headers=headers,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])

                if data["type"] == "sentence":
                    audio = None
                    if data.get("audio_data"):
                        audio = base64.b64decode(data["audio_data"])
                    yield StreamChunk(
                        text=data["text"],
                        audio_data=audio,
                        index=data["index"],
                    )
                elif data["type"] == "done":
                    yield StreamChunk(
                        text="",
                        audio_data=None,
                        index=-1,
                        is_done=True,
                        full_text=data.get("full_text", ""),
                        emotion=data.get("emotion", ""),
                        latency_ms=data.get("latency_ms", 0),
                    )

    async def process_text_stream(
        self, session: Session, text: str
    ) -> AsyncIterator[StreamChunk]:
        """Stream text through AI pipeline, yielding per-sentence chunks."""
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "text_input": text,
        }

        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        async with self.stream_client.stream(
            "POST", "/pipeline/chat/stream", json=payload, headers=headers,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])

                if data["type"] == "sentence":
                    audio = None
                    if data.get("audio_data"):
                        audio = base64.b64decode(data["audio_data"])
                    yield StreamChunk(
                        text=data["text"],
                        audio_data=audio,
                        index=data["index"],
                    )
                elif data["type"] == "done":
                    yield StreamChunk(
                        text="",
                        audio_data=None,
                        index=-1,
                        is_done=True,
                        full_text=data.get("full_text", ""),
                        emotion=data.get("emotion", ""),
                        latency_ms=data.get("latency_ms", 0),
                    )

    async def close(self):
        await self.client.aclose()
        await self.stream_client.aclose()
