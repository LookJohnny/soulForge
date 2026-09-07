"""Pipeline orchestrator - calls ai-core service for the full ASR->LLM->TTS chain.

Supports both blocking (/pipeline/chat) and streaming (/pipeline/chat/stream) modes.
Streaming mode yields per-sentence text+audio for low-latency playback.
"""

import base64
import json
import logging
import re
import time
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
    causes: list[str] | None = None  # mood causality ring (newest last)
    energy: int | None = None
    # Only populated on 'relationship' chunks (five-axis state + turn deltas)
    relationship: dict | None = None
    # Only populated on 'event' chunks (visual-novel scene card)
    event: dict | None = None
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

    def _runtime_bridge(self, session: Session):
        """A session owns its voice queue and playback receipts."""
        from gateway.pipeline.character_bridge import CharacterBridge

        if getattr(self, "_resetting_runtime", False):
            raise RuntimeError("Runtime character is switching")
        if not settings.soulforge_brand_id:
            return self._character_bridge_instance()  # explicit legacy/mock mode
        bridges = getattr(self, "_voice_bridges", None)
        if bridges is None:
            bridges = self._voice_bridges = {}
        key = session.session_id
        bridge = bridges.get(key)
        if bridge is None or bridge.agent_id != settings.character_runtime_agent:
            bridge = CharacterBridge(
                body_id=f"gateway-{uuid.uuid4().hex}",
                timeout_s=settings.character_runtime_timeout_s,
                autonomous_speech=(
                    not settings.character_runtime_voice_device_id
                    or session.device_id == settings.character_runtime_voice_device_id
                ),
            )
            bridges[key] = bridge
        return bridge

    async def _resolve_runtime_identity(
        self, body_id: str, session_id: str, agent_id: str | None = None
    ) -> dict:
        from soulforge_harness.runtime.identity import runtime_user_id

        brand = settings.soulforge_brand_id
        if not brand or not settings.service_token:
            raise RuntimeError("Unified Runtime requires brand and service authentication")
        user = settings.soulforge_user_id or runtime_user_id(brand)
        agent = agent_id or settings.character_runtime_agent
        response = await self.client.post(
            "/runtime/resolve",
            json={
                "user_id": user,
                "agent_id": agent,
                "body_id": body_id,
                "session_id": session_id,
            },
            headers={"X-Brand-Id": brand},
        )
        response.raise_for_status()
        identity = response.json()["identity"]
        expected = {
            "user_id": user,
            "agent_id": agent,
            "body_id": body_id,
            "session_id": session_id,
        }
        if not isinstance(identity, dict) or any(identity.get(k) != v for k, v in expected.items()):
            raise PermissionError(
                "Resolved identity does not match the requested body and character"
            )
        return identity

    async def bind_runtime_session(self, session: Session, *, bridge=None) -> dict | None:
        if not settings.soulforge_brand_id:
            return None
        from soulforge_harness.runtime.identity import runtime_user_id

        bridge = bridge or self._runtime_bridge(session)
        brand = settings.soulforge_brand_id
        user = settings.soulforge_user_id or runtime_user_id(brand)
        if session.brand_id and session.brand_id != brand:
            raise PermissionError("Session belongs to a different runtime brand")
        if session.end_user_id and session.end_user_id != user:
            raise PermissionError("Session belongs to a different runtime user")
        cached = getattr(session, "_runtime_identity", None)
        if (
            cached
            and cached["agent_id"] == bridge.agent_id
            and cached["body_id"] == bridge.body_id
            and cached["user_id"] == user
            and cached["session_id"] == session.session_id
        ):
            return cached
        identity = await self._resolve_runtime_identity(
            bridge.body_id, session.session_id, agent_id=bridge.agent_id
        )
        # A late resolve from the retired character must not overwrite a newer
        # session binding. The initiating turn still keeps its original bridge.
        if getattr(self, "_voice_bridges", {}).get(session.session_id) is bridge:
            session.brand_id = brand
            session.end_user_id = identity["user_id"]
            session.character_id = identity["character_id"]
            session._runtime_identity = identity
        return identity

    async def _runtime_decision(self, session: Session, text: str) -> tuple:
        bridge = self._runtime_bridge(session)
        identity = await self.bind_runtime_session(session, bridge=bridge)
        if identity:
            decision = await bridge.process_utterance(text, payload={"identity": identity})
        else:
            decision = await bridge.process_utterance(text)
        return bridge, decision

    async def process_external_utterance(self, text: str, *, body_id: str, session_id: str) -> dict:
        """External video is a voice body of the same runtime and durable user."""
        from gateway.pipeline.character_bridge import CharacterBridge

        bridge = CharacterBridge(
            body_id=f"{body_id[:70]}-{uuid.uuid4().hex}",
            timeout_s=settings.character_runtime_timeout_s,
            autonomous_speech=False,
        )
        try:
            identity = await self._resolve_runtime_identity(
                bridge.body_id, session_id, agent_id=bridge.agent_id
            )
            result = await bridge.process_utterance(text, payload={"identity": identity})
            for command in result.get("commands", []):
                await bridge.confirm_spoken(
                    command["command_id"],
                    played=False,
                    detail="external text delivered; playback unverified",
                )
            return result
        finally:
            await bridge.close()

    async def close_session_runtime(self, session: Session) -> None:
        bridge = getattr(self, "_voice_bridges", {}).pop(session.session_id, None)
        if bridge is not None:
            for receipt, owner in list(getattr(self, "_playback_bridges", {}).items()):
                if owner is bridge:
                    await self.confirm_playback(
                        receipt, played=False, detail="voice body disconnected"
                    )
            await bridge.close()

    async def reset_runtime_bridges(self) -> None:
        self._resetting_runtime = True
        try:
            for receipt in list(getattr(self, "_pending_playback", {})):
                await self.confirm_playback(
                    receipt, played=False, detail="runtime character switched"
                )
            bridges = list(getattr(self, "_voice_bridges", {}).values())
            self._voice_bridges = {}
            for bridge in bridges:
                await bridge.close()
            bridge = getattr(self, "_character_bridge", None)
            if bridge is not None:
                await bridge.close()
                del self._character_bridge
        finally:
            self._resetting_runtime = False

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

    def _register_playback(self, commands: list[dict], bridge=None) -> str | None:
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
        if bridge is not None:
            if not hasattr(self, "_playback_bridges"):
                self._playback_bridges = {}
            self._playback_bridges[receipt] = bridge
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
        owners = getattr(self, "_playback_bridges", {})
        bridge = owners.get(receipt) or getattr(self, "_character_bridge", None)
        if not command_ids or bridge is None:
            return False
        for command_id in command_ids:
            await bridge.confirm_spoken(command_id, played=played, detail=detail)
        pending.pop(receipt, None)
        owners.pop(receipt, None)
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
        # session.character_id is only the DB voice hint; Lane B overrides the
        # voice from characters.json, so an unbound (web) session still speaks
        bridge = self._runtime_bridge(session)
        await self.bind_runtime_session(session, bridge=bridge)
        command = await bridge.next_unsolicited(timeout_s=timeout_s)
        text = str(command.get("dialogue") or "")
        receipt = self._register_playback([command], bridge)
        try:
            audio = (
                await self.synthesize_tts(
                    text,
                    session.character_id,
                    session.brand_id,
                    emotion=self._beat_emotion([command]),
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
        if not session.character_id and not settings.character_runtime_url:
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
            bridge, decision = await self._runtime_decision(session, user_text)
            reply = decision["text"]
            receipt = self._register_playback(decision.get("commands", []), bridge)
            try:
                audio = (
                    await self.synthesize_tts(
                        reply,
                        session.character_id,
                        session.brand_id,
                        emotion=self._beat_emotion(decision.get("commands")),
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
        if not session.character_id and not settings.character_runtime_url:
            raise ValueError(f"No character assigned to device {session.device_id}")

        # Phase 6 single-decision path: when the Character Runtime is configured,
        # IT alone decides what the character says/does — the legacy ai-core chat
        # LLM is bypassed so one utterance is never processed by two brains.
        if settings.character_runtime_url:
            bridge, decision = await self._runtime_decision(session, text)
            receipt = self._register_playback(decision.get("commands", []), bridge)
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
        if settings.character_runtime_url:
            # Runtime's schedule/proactivity owns idle cognition. This local
            # device timer must never invoke a competing conversation brain.
            return {"text": None, "audio_data": None}

        if not session.character_id and not settings.character_runtime_url:
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

    _runtime_voice_cache: tuple[str | None, float] | None = None

    @classmethod
    def _runtime_voice(cls) -> tuple[str | None, float]:
        """Fish reference for the Character-Runtime agent, from characters.json.

        In Lane B the ai-core DB character may not exist, so the config file's
        voice binding is what actually keeps the character's voice hers."""
        if cls._runtime_voice_cache is not None:
            return cls._runtime_voice_cache
        voice: str | None = None
        speed = 1.0
        try:
            import json as _json
            from pathlib import Path

            for parent in (Path.cwd(), *Path.cwd().parents):
                config = parent / "configs" / "characters.json"
                if config.exists():
                    data = _json.loads(config.read_text("utf-8"))
                    for entry in data.get("characters", []):
                        if entry.get("id") == settings.character_runtime_agent:
                            fish = entry.get("voice", {}).get("fish", {})
                            voice = fish.get("reference_id") or None
                            speed = float(fish.get("speed", 1.0))
                            break
                    break
        except Exception:
            logger.warning("orchestrator.runtime_voice_load_failed", exc_info=True)
        cls._runtime_voice_cache = (voice, speed)
        return cls._runtime_voice_cache

    @staticmethod
    def _beat_emotion(commands: list | None) -> str | None:
        """First speak_line emotion of a decision beat, if any."""
        for command in commands or ():
            if isinstance(command, dict) and command.get("dialogue"):
                emotion = (command.get("params") or {}).get("emotion")
                if isinstance(emotion, str) and emotion:
                    return emotion
        return None

    async def synthesize_tts(
        self,
        text: str,
        character_id: str | None = None,
        brand_id: str | None = None,
        emotion: str | None = None,
    ) -> bytes | None:
        """Synthesize a short clip in the character's voice via ai-core."""
        payload = {"text": text, "character_id": character_id, "brand_id": brand_id}
        if settings.character_runtime_url and not settings.soulforge_brand_id:
            voice, speed = self._runtime_voice()
            if voice:
                payload["voice"] = voice
                payload["speed"] = speed
        if emotion:
            payload["emotion"] = emotion
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
        if settings.character_runtime_url:
            bridge = self._runtime_bridge(session)
            identity = await self.bind_runtime_session(session, bridge=bridge)
            # Keep sensor data as data. In particular, never turn a hug into a
            # USER_UTTERANCE that would earn relationship points or user facts.
            touch = {
                key: touch_data[key]
                for key in ("gesture", "zone", "pressure", "duration_ms")
                if key in touch_data
            }
            event_payload = {"touch": touch}
            if identity:
                event_payload["identity"] = identity
            decision = await bridge.process_event(
                "environment",
                source="touch_sensor",
                text="Touch sensor interaction",
                payload=event_payload,
            )
            commands = decision.get("commands", [])
            reply = decision.get("text") or ""
            receipt = self._register_playback(commands, bridge)
            character_id = (identity or {}).get("character_id") or session.character_id
            brand_id = session.brand_id or settings.soulforge_brand_id
            try:
                audio = (
                    await self.synthesize_tts(
                        reply, character_id, brand_id, emotion=self._beat_emotion(commands)
                    )
                    if reply
                    else None
                )
            except BaseException:
                if receipt:
                    await self.confirm_playback(
                        receipt, played=False, detail="touch TTS interrupted"
                    )
                raise
            if reply and audio is None and receipt:
                await self.confirm_playback(
                    receipt, played=False, detail="touch TTS synthesis failed"
                )
                receipt = None
            state = next(
                (
                    c.get("params", {}).get("cognitive_state")
                    for c in commands
                    if c.get("params", {}).get("cognitive_state")
                ),
                {},
            )
            return {
                "text": reply,
                "audio_data": audio,
                "playback_receipt": receipt,
                "cognitive_state": state,
                "correlation_id": decision.get("correlation_id"),
            }

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

        normalized = (event_type or "").strip().lower()
        safety_events = {
            "battery_low",
            "low_battery",
            "hardware_failure",
            "device_error",
            "motor_error",
            "user_interrupt",
            "barge_in",
            "interrupt",
        }
        unified = bool(settings.character_runtime_url)
        if unified and normalized not in safety_events:
            return {
                "reaction": {
                    "should_react": False,
                    "reaction_type": "ignore",
                    "reason": "runtime_owns_reaction",
                    "speech": None,
                    "actions": [],
                    "plan_patch": {},
                    "safety_flags": [],
                },
                "action_preview": None,
            }
        if unified:
            await self.bind_runtime_session(session)

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

        if unified:
            # Preserve only the existing deterministic safety restrictions.
            # General speech, motion and autonomous resume belong to Runtime.
            reaction["speech"] = None
            reaction["actions"] = [
                a
                for a in reaction.get("actions", [])
                if isinstance(a, dict)
                and (
                    (a.get("channel") == "audio" and a.get("command") == "stop")
                    or (a.get("channel") == "led" and a.get("pattern") in {"breathe", "soft_hold"})
                )
            ]
            if normalized in {"battery_low", "low_battery"}:
                reaction["plan_patch"] = {
                    "mode": "power_saving",
                    "suspend_high_power_actions": True,
                }
            elif normalized in {"hardware_failure", "device_error", "motor_error"}:
                channel = event.get("channel", "motion")
                if not isinstance(channel, str) or channel not in {
                    "motion",
                    "servo",
                    "motor",
                    "audio",
                    "led",
                    "gaze",
                    "nav",
                }:
                    channel = "motion"
                reaction["plan_patch"] = {"disabled_channel": channel}
            else:
                reaction["plan_patch"] = {"pause_current_intent": True}

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
        if not session.character_id and not settings.character_runtime_url:
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
        if not session.character_id and not settings.character_runtime_url:
            raise ValueError(f"No character assigned to device {session.device_id}")

        # Phase 6 single-decision path: dialogue is decided by the Character
        # Runtime; only TTS synthesis still rides ai-core. The legacy chat LLM
        # is bypassed — one utterance is never processed by two brains.
        if settings.character_runtime_url:
            started = time.monotonic()
            bridge, decision = await self._runtime_decision(session, text)
            decided_ms = round((time.monotonic() - started) * 1000)
            reply = decision["text"]
            commands = decision.get("commands", [])
            turn_identity = next(
                (
                    c.get("params", {}).get("identity")
                    for c in commands
                    if c.get("params", {}).get("identity")
                ),
                {},
            )
            turn_character = turn_identity.get("character_id") or session.character_id
            turn_brand = session.brand_id
            receipt = self._register_playback(commands, bridge)
            state = next(
                (
                    c.get("params", {}).get("cognitive_state")
                    for c in commands
                    if c.get("params", {}).get("cognitive_state")
                ),
                {},
            )
            handed_off = False
            first_audio_ms = None
            index = 0
            try:
                # Same-turn mood reaches the body before its first audio clip.
                if state:
                    yield StreamChunk(
                        text="",
                        audio_data=None,
                        index=-1,
                        kind="emotion",
                        emotion=state.get("emotion", ""),
                        pad=state.get("pad"),
                    )
                    if state.get("relationship"):
                        yield StreamChunk(
                            text="",
                            audio_data=None,
                            index=-1,
                            kind="relationship",
                            relationship=state["relationship"],
                        )
                # The decision is already validated as a whole. Synthesize each
                # sentence with its own beat emotion instead of buffering all TTS.
                # This is sentence TTS pipelining, not token-streamed cognition.
                lines = commands or [{"dialogue": reply}]
                for command in lines:
                    line = command.get("dialogue") or ""
                    for sentence in re.findall(r"[^。！？!?]+[。！？!?]*", line):
                        if not sentence.strip():
                            continue
                        audio = await self.synthesize_tts(
                            sentence,
                            turn_character,
                            turn_brand,
                            emotion=self._beat_emotion([command]),
                        )
                        if audio is None and receipt:
                            await self.confirm_playback(
                                receipt, played=False, detail="TTS synthesis failed"
                            )
                            receipt = None
                        if audio is not None and first_audio_ms is None:
                            first_audio_ms = round((time.monotonic() - started) * 1000)
                        yield StreamChunk(
                            text=sentence,
                            audio_data=audio,
                            index=index,
                            kind="sentence",
                            playback_receipt=receipt,
                        )
                        index += 1
                handed_off = True
                yield StreamChunk(
                    text="",
                    audio_data=None,
                    index=index,
                    kind="done",
                    is_done=True,
                    full_text=reply,
                    user_text=text,
                    playback_receipt=receipt,
                    latency_ms=round((time.monotonic() - started) * 1000),
                    stages={"decision_ms": decided_ms, "first_audio_ms": first_audio_ms},
                )
            except Exception:
                if receipt:
                    await self.confirm_playback(
                        receipt, played=False, detail="TTS synthesis raised an error"
                    )
                    receipt = None
                raise
            finally:
                if not handed_off and receipt:
                    await self.confirm_playback(
                        receipt, played=False, detail="speech stream interrupted before handoff"
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
                causes=data.get("causes"),
                energy=data.get("energy"),
            )
        if etype == "relationship":
            return StreamChunk(
                text="", audio_data=None, index=-1, kind="relationship", relationship=data
            )
        if etype == "event":
            return StreamChunk(text="", audio_data=None, index=-1, kind="event", event=data)
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
        await self.reset_runtime_bridges()
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
