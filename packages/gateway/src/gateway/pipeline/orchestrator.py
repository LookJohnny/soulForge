"""Pipeline orchestrator - calls ai-core service for the full ASR->LLM->TTS chain."""

import base64
import logging

import httpx

from gateway.config import settings
from gateway.session import Session

logger = logging.getLogger(__name__)


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

    async def close(self):
        await self.client.aclose()
