"""Pipeline orchestrator - calls ai-core service for the full ASR->LLM->TTS chain.

Supports both blocking (/pipeline/chat) and streaming (/pipeline/chat/stream) modes.
Streaming mode yields per-sentence text+audio for low-latency playback.
"""

import base64
import json
import logging
import uuid
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
    # Only populated on 'emotion' chunks (PAD snapshot + mapped hardware command)
    pad: dict | None = None
    hardware: dict | None = None
    # Only populated on 'relationship' chunks (five-axis state + turn deltas)
    relationship: dict | None = None
    latency_ms: int = 0
    stages: dict | None = None  # ai-core per-stage latency breakdown (ms)
    # Opaque receipt for the downstream playback sink.  The sink calls
    # ``PipelineOrchestrator.confirm_playback`` only after real playback (or
    # cancellation); producing/yielding audio is not completion.
    playback_receipt: str | None = None


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
        self._pending_playback: dict[str, tuple[str, ...]] = {}

    def _character_bridge_instance(self):
        from gateway.pipeline.character_bridge import CharacterBridge

        if not hasattr(self, "_character_bridge"):
            self._character_bridge = CharacterBridge()
        return self._character_bridge

    async def _transcribe_audio(self, audio_data: bytes, audio_format: str = "pcm") -> str:
        """ASR-only fallback used when the Character Runtime owns decisions.

        The old ``/pipeline/chat/stream`` endpoint combines ASR with a second
        LLM and is therefore forbidden in single-brain mode. Gateway audio is
        already 16 kHz mono PCM; feed it to the existing DashScope streaming
        recognizer without invoking any chat endpoint.
        """
        if not audio_data:
            return ""
        if audio_format != "pcm":
            logger.error("orchestrator.asr_only_unsupported_format format=%s", audio_format)
            return ""
        if not settings.dashscope_api_key:
            logger.error("orchestrator.asr_only_unavailable missing DashScope API key")
            return ""

        from gateway.handlers.streaming_asr import StreamingASR

        recognizer = StreamingASR(api_key=settings.dashscope_api_key)
        try:
            recognizer.start()
            # Small chunks preserve the provider's streaming contract while
            # processing an already-buffered utterance.
            for offset in range(0, len(audio_data), 3200):
                recognizer.feed(audio_data[offset : offset + 3200])
            return (await recognizer.finish()).strip()
        except Exception:
            recognizer.abort()
            logger.exception("orchestrator.asr_only_failed")
            return ""

    def _register_playback(self, commands: list[dict]) -> str | None:
        command_ids = tuple(
            str(command.get("command_id"))
            for command in commands
            if command.get("dialogue") and command.get("command_id")
        )
        if not command_ids:
            return None
        receipt = uuid.uuid4().hex
        pending = getattr(self, "_pending_playback", None)
        if pending is None:
            pending = self._pending_playback = {}
        pending[receipt] = command_ids
        return receipt

    async def confirm_playback(
        self,
        receipt: str | None,
        *,
        played: bool = True,
        detail: str = "",
    ) -> bool:
        """Commit an explicit downstream playback result.

        Existing stream consumers remain source-compatible because the receipt
        is optional metadata on ``StreamChunk``. Playback-aware consumers must
        call this after the device drains its audio buffer (or with
        ``played=False`` on disconnect/barge-in). Returns ``False`` for unknown
        or already-consumed receipts, making duplicate callbacks idempotent.
        """
        pending = getattr(self, "_pending_playback", {})
        command_ids = pending.get(receipt or "")
        bridge = getattr(self, "_character_bridge", None)
        if not command_ids or bridge is None:
            return False
        for command_id in command_ids:
            await bridge.confirm_spoken(command_id, played=played, detail=detail)
        pending.pop(receipt, None)
        return True

    async def process_next_runtime_dialogue(
        self,
        session: Session,
        *,
        timeout_s: float | None = None,
    ) -> StreamChunk:
        """Render dialogue caused by perception/system events into TTS.

        Unlike ``process_text_stream`` this does not submit a second event. The
        persistent voice body receives an unsolicited ``speak_line`` already
        decided by Character Runtime, synthesizes it, and returns an explicit
        playback receipt for the device loop.
        """
        if not settings.character_runtime_url:
            raise RuntimeError("Character Runtime bridge is not configured")
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")
        bridge = self._character_bridge_instance()
        command = await bridge.next_unsolicited(timeout_s=timeout_s)
        text = str(command.get("dialogue") or "")
        receipt = self._register_playback([command])
        try:
            audio = (
                await self.synthesize_tts(
                    text,
                    session.character_id,
                    session.brand_id,
                )
                if text
                else None
            )
        except Exception:
            if receipt:
                await self.confirm_playback(
                    receipt,
                    played=False,
                    detail="TTS synthesis raised an error",
                )
            raise
        if text and audio is None and receipt:
            await self.confirm_playback(
                receipt,
                played=False,
                detail="TTS synthesis failed",
            )
            receipt = None
        return StreamChunk(
            text=text,
            audio_data=audio,
            index=0,
            kind="sentence",
            playback_receipt=receipt,
        )

    async def process_audio(self, session: Session, audio_data: bytes) -> dict:
        """Send audio to ai-core pipeline, get text + audio response.

        Returns:
            {"text": str, "audio_data": bytes|None, "latency_ms": int}
        """
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        if settings.character_runtime_url:
            user_text = await self._transcribe_audio(audio_data)
            if not user_text:
                return {
                    "text": "",
                    "audio_data": None,
                    "latency_ms": 0,
                    "user_text": "",
                    "playback_receipt": None,
                }
            bridge = self._character_bridge_instance()
            decision = await bridge.process_utterance(user_text)
            reply = decision["text"]
            receipt = self._register_playback(decision.get("commands", []))
            try:
                audio = (
                    await self.synthesize_tts(
                        reply,
                        session.character_id,
                        session.brand_id,
                    )
                    if reply
                    else None
                )
            except Exception:
                if receipt:
                    await self.confirm_playback(
                        receipt,
                        played=False,
                        detail="TTS synthesis raised an error",
                    )
                raise
            if reply and audio is None and receipt:
                await self.confirm_playback(receipt, played=False, detail="TTS synthesis failed")
                receipt = None
            return {
                "text": reply,
                "audio_data": audio,
                "latency_ms": 0,
                "user_text": user_text,
                "playback_receipt": receipt,
                "correlation_id": decision.get("correlation_id"),
            }

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

        # Phase 6 single-decision path: when the Character Runtime is configured,
        # IT alone decides what the character says/does — the legacy ai-core chat
        # LLM is bypassed so one utterance is never processed by two brains.
        if settings.character_runtime_url:
            decision = await self._character_bridge_instance().process_utterance(text)
            receipt = self._register_playback(decision.get("commands", []))
            return {
                "text": decision["text"],
                "audio_data": None,
                "latency_ms": 0,
                "correlation_id": decision.get("correlation_id"),
                "commands": decision.get("commands", []),
                "playback_receipt": receipt,
            }

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

        if settings.character_runtime_url:
            user_text = await self._transcribe_audio(audio_data, audio_format)
            if not user_text:
                # Fail closed: no transcript means no decision. In particular,
                # never fall through to the legacy chat LLM for convenience.
                yield StreamChunk(
                    text="",
                    audio_data=None,
                    index=0,
                    kind="done",
                    is_done=True,
                    user_text="",
                    stages={"asr_only": "no_transcript"},
                )
                return
            async for chunk in self.process_text_stream(session, user_text):
                if chunk.is_done:
                    chunk.user_text = user_text
                yield chunk
            return

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
            # 400 here means the utterance produced nothing usable (batch ASR
            # heard only noise/cough and returned empty text). That's a normal
            # quiet-room event, not a pipeline failure — swallow and resume
            # listening instead of erroring the device.
            if resp.status_code == 400:
                logger.info("orchestrator.empty_utterance_rejected device=%s", session.device_id)
                return
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                chunk = self._parse_stream_event(data)
                if chunk is not None:
                    yield chunk

    async def process_text_stream(
        self,
        session: Session,
        text: str,
        stream_audio: bool = False,
        image_data: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream text through AI pipeline, yielding per-sentence chunks.

        When ``stream_audio`` is set, ai-core sends audio progressively as
        ``audio_chunk``/``audio_end`` events instead of one clip per sentence.
        """
        if not session.character_id:
            raise ValueError(f"No character assigned to device {session.device_id}")

        # Phase 6 single-decision path: dialogue is decided by the Character
        # Runtime; only TTS synthesis still rides ai-core. The legacy chat LLM
        # is bypassed — one utterance is never processed by two brains.
        if settings.character_runtime_url:
            bridge = self._character_bridge_instance()
            decision = await bridge.process_utterance(text)
            reply = decision["text"]
            receipt = self._register_playback(decision.get("commands", []))
            try:
                audio = (
                    await self.synthesize_tts(
                        reply,
                        session.character_id,
                        session.brand_id,
                    )
                    if reply
                    else None
                )
            except Exception:
                if receipt:
                    await self.confirm_playback(
                        receipt,
                        played=False,
                        detail="TTS synthesis raised an error",
                    )
                raise
            if reply and audio is None and receipt:
                await self.confirm_playback(receipt, played=False, detail="TTS synthesis failed")
                receipt = None
            yield StreamChunk(
                text=reply, audio_data=audio, index=0, kind="sentence", playback_receipt=receipt
            )
            yield StreamChunk(
                text="",
                audio_data=None,
                index=1,
                kind="done",
                is_done=True,
                full_text=reply,
                user_text=text,
                playback_receipt=receipt,
            )
            return

        payload = {
            "character_id": session.character_id,
            "end_user_id": session.end_user_id,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "text_input": text,
            "audio_streaming": stream_audio,
        }
        if image_data is not None:
            payload["image_data"] = image_data

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
            return StreamChunk(text="", audio_data=audio, index=data["index"], kind="audio_chunk")
        if etype == "audio_end":
            return StreamChunk(text="", audio_data=None, index=data["index"], kind="audio_end")
        if etype == "need_vision":
            # ai-core spotted a vision request in an audio turn it transcribed;
            # the server must capture a frame and re-issue the turn as text.
            return StreamChunk(
                text=data.get("user_text", ""),
                audio_data=None,
                index=-1,
                kind="need_vision",
            )
        if etype == "emotion":
            return StreamChunk(
                text="",
                audio_data=None,
                index=-1,
                kind="emotion",
                emotion=data.get("emotion", ""),
                pad=data.get("pad"),
                hardware=data.get("hardware"),
            )
        if etype == "relationship":
            return StreamChunk(
                text="", audio_data=None, index=-1, kind="relationship", relationship=data
            )
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
        # Outstanding receipts were never confirmed by a playback sink. Mark
        # them interrupted before disconnecting so Runtime does not infer speech.
        for receipt in list(getattr(self, "_pending_playback", {})):
            await self.confirm_playback(
                receipt, played=False, detail="gateway shutdown before playback confirmation"
            )
        bridge = getattr(self, "_character_bridge", None)
        if bridge is not None:
            await bridge.close()
        await self.client.aclose()
        await self.stream_client.aclose()
