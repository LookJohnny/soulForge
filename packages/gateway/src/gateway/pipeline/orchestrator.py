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
    """A single chunk from the streaming pipeline.

    ``kind`` distinguishes:
      - "sentence"   : a sentence of text; ``audio_data`` holds the whole clip
                       (legacy) or is None when audio streams as audio_chunks.
      - "audio_chunk": a progressive audio fragment for ``index`` (audio_data).
      - "audio_end"  : end-of-audio marker for ``index``.
      - "done"       : terminal chunk (is_done=True) with turn metadata.
    """

    text: str
    audio_data: bytes | None
    index: int
    kind: str = "sentence"
    is_done: bool = False
    # Only populated on the final 'done' chunk
    full_text: str = ""
    user_text: str = ""
    emotion: str = ""
    latency_ms: int = 0
    stages: dict | None = None  # ai-core per-stage latency breakdown (ms)


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

    async def process_idle(self, session: Session, idle_state: str = "bored") -> dict:
        """Ask ai-core for a spontaneous idle musing (text + audio).

        Runs the normal pipeline in idle_mode: memory-aware, but writes
        no memories and earns no relationship points.
        """
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "idle_mode": True,
            "idle_state": idle_state,
        }
        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        resp = await self.client.post("/pipeline/chat", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        result = {"text": data.get("text"), "audio_data": None}
        if data.get("audio_data"):
            result["audio_data"] = base64.b64decode(data["audio_data"])
        return result

    async def synthesize_tts(
        self, text: str, character_id: str | None = None, brand_id: str | None = None
    ) -> bytes | None:
        """Synthesize a short clip in the character's voice via ai-core."""
        payload = {"text": text, "character_id": character_id, "brand_id": brand_id}
        headers = {}
        if brand_id:
            headers["X-Brand-Id"] = brand_id
        resp = await self.client.post("/tts/synthesize", json=payload, headers=headers)
        if resp.status_code != 200:
            logger.warning("orchestrator.tts_synthesize_failed status=%d", resp.status_code)
            return None
        data = resp.json()
        if data.get("audio_data"):
            return base64.b64decode(data["audio_data"])
        return None

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

    async def process_reaction_event(
        self,
        session: Session,
        event_type: str,
        event: dict | None = None,
        context: dict | None = None,
        device_manifest: dict | None = None,
        device_state: dict | None = None,
    ) -> dict:
        """Send a device/user event to ai-core reaction planner and safety preview."""

        event = event or {}
        context = {
            "device_id": session.device_id,
            "protocol": session.protocol,
            **(context or {}),
        }
        device_manifest = (
            device_manifest or event.get("device_manifest") or event.get("manifest") or {}
        )
        device_state = device_state or event.get("device_state") or {}
        for key in ("battery_percent", "temperature_c", "quiet_mode", "local_hour"):
            if key in event and key not in device_state:
                device_state[key] = event[key]

        payload = {
            "user_id": session.end_user_id,
            "character_id": session.character_id,
            "event_type": event_type,
            "event": event,
            "context": context,
        }

        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        reaction_resp = await self.client.post("/memory/reaction", json=payload, headers=headers)
        reaction_resp.raise_for_status()
        reaction = reaction_resp.json()

        action_preview = None
        if reaction.get("speech") or reaction.get("actions"):
            preview_resp = await self.client.post(
                "/actions/preview",
                json={
                    "action_plan": {
                        "intent": reaction.get("reaction_type") or event_type,
                        "speech": reaction.get("speech"),
                        "actions": reaction.get("actions") or [],
                    },
                    "device_manifest": device_manifest,
                    "device_state": device_state,
                    "context": context,
                },
                headers=headers,
            )
            preview_resp.raise_for_status()
            action_preview = preview_resp.json()

        return {"reaction": reaction, "action_preview": action_preview}

    async def process_audio_stream(
        self, session: Session, audio_data: bytes, audio_format: str = "pcm"
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
            "audio_format": audio_format,
            "history": session.history[-10:] if session.history else [],  # last 10 turns
        }

        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        async with self.stream_client.stream(
            "POST",
            "/pipeline/chat/stream",
            json=payload,
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                chunk = self._parse_stream_event(data)
                if chunk is not None:
                    yield chunk

    async def process_text_stream(
        self, session: Session, text: str, stream_audio: bool = False
    ) -> AsyncIterator[StreamChunk]:
        """Stream text through AI pipeline, yielding per-sentence chunks.

        When ``stream_audio`` is set, ai-core sends audio progressively as
        ``audio_chunk``/``audio_end`` events instead of one clip per sentence.
        """
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "text_input": text,
            "audio_streaming": stream_audio,
        }

        headers = {}
        if session.brand_id:
            headers["X-Brand-Id"] = session.brand_id

        async with self.stream_client.stream(
            "POST",
            "/pipeline/chat/stream",
            json=payload,
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                chunk = self._parse_stream_event(data)
                if chunk is not None:
                    yield chunk

    @staticmethod
    def _parse_stream_event(data: dict) -> "StreamChunk | None":
        """Translate one ai-core SSE event into a StreamChunk (or None)."""
        etype = data.get("type")
        if etype == "sentence":
            audio = base64.b64decode(data["audio_data"]) if data.get("audio_data") else None
            return StreamChunk(
                text=data["text"], audio_data=audio, index=data["index"], kind="sentence"
            )
        if etype == "audio_chunk":
            audio = base64.b64decode(data["audio_data"]) if data.get("audio_data") else None
            return StreamChunk(
                text="", audio_data=audio, index=data["index"], kind="audio_chunk"
            )
        if etype == "audio_end":
            return StreamChunk(text="", audio_data=None, index=data["index"], kind="audio_end")
        if etype == "done":
            return StreamChunk(
                text="",
                audio_data=None,
                index=-1,
                kind="done",
                is_done=True,
                full_text=data.get("full_text", ""),
                user_text=data.get("user_text", ""),
                emotion=data.get("emotion", ""),
                latency_ms=data.get("latency_ms", 0),
                stages=data.get("stages"),
            )
        return None

    async def close(self):
        await self.client.aclose()
        await self.stream_client.aclose()
