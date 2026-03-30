"""WebSocket server core - handles connections and dispatches to protocol adapters."""

import asyncio
import hashlib
import json
import time

import structlog

from fastapi import WebSocket, WebSocketDisconnect

from gateway.config import settings
from gateway.protocols.base import MessageType, OutboundMessage
from gateway.protocols.registry import registry
from gateway.session import SessionManager
from gateway.handlers.audio import AudioHandler
from gateway.pipeline.orchestrator import PipelineOrchestrator

logger = structlog.get_logger()


class WebSocketServer:
    def __init__(self):
        self.session_manager = SessionManager()
        self.audio_handler = AudioHandler()
        self.orchestrator = PipelineOrchestrator()

    async def startup(self):
        await self.session_manager.connect()

    async def shutdown(self):
        await self.orchestrator.close()

    async def _verify_device(self, device_id: str, device_secret: str | None) -> bool:
        """Verify device credentials against Redis/DB with fallback.

        If device_secret is not provided and we're in development, allow.
        In production, devices must provide valid credentials.
        """
        if settings.environment != "production" and not device_secret:
            return True

        if not device_secret:
            return False

        # Load device info (Redis → DB fallback)
        info = await self.session_manager.load_device_info(device_id)
        if not info:
            return settings.environment != "production"

        stored_secret = info.get("device_secret")
        if stored_secret:
            hashed = hashlib.sha256(device_secret.encode()).hexdigest()
            return hashed == stored_secret

        # No secret configured for this device — allow in non-production
        return settings.environment != "production"

    async def handle_connection(self, ws: WebSocket):
        """Handle a new WebSocket connection."""
        await ws.accept()

        try:
            # Wait for first message to detect protocol
            initial = await ws.receive()
            initial_data = initial.get("text") or initial.get("bytes", b"")

            # Auto-detect protocol
            adapter = await registry.detect(ws, initial_data)
            if not adapter:
                logger.warning("gateway.unknown_protocol")
                await ws.close(code=4000, reason="Unknown protocol")
                return

            # Handshake
            device_id = await adapter.handshake(ws, initial_data)

            # Device authentication
            device_secret = None
            if isinstance(initial_data, str):
                try:
                    msg = json.loads(initial_data)
                    device_secret = msg.get("device_secret")
                except (json.JSONDecodeError, AttributeError):
                    pass

            if not await self._verify_device(device_id, device_secret):
                logger.warning("gateway.device_auth_failed", device_id=device_id)
                await ws.close(code=4001, reason="Device authentication failed")
                return

            # Create session
            session = await self.session_manager.create_session(device_id, adapter.name)
            logger.info(
                "gateway.device_connected",
                device_id=device_id,
                protocol=adapter.name,
                session_id=session.session_id,
            )

            # Message loop
            while True:
                raw = await ws.receive()
                raw_data = raw.get("text") or raw.get("bytes", b"")

                if not raw_data:
                    if raw.get("type") == "websocket.disconnect":
                        break
                    continue

                # Debug: log frame type and size
                if isinstance(raw_data, bytes):
                    logger.debug("gateway.frame binary=%d bytes", len(raw_data))
                else:
                    logger.info("gateway.frame text=%s", raw_data[:200])

                msg = await adapter.decode(raw_data)
                msg.device_id = device_id

                await self._handle_message(ws, adapter, session, msg)

        except WebSocketDisconnect:
            logger.info("gateway.device_disconnected")
        except Exception:
            logger.exception("gateway.connection_error")
        finally:
            # Cleanup
            if "session" in locals():
                self.audio_handler.abort(session)
                await self.session_manager.remove_session(session.session_id)

    async def _handle_message(self, ws, adapter, session, msg):
        """Route message to appropriate handler."""
        if msg.type == MessageType.AUDIO:
            # Skip audio while we're playing TTS (avoid echo feedback loop)
            if getattr(session, "_playing", False):
                return

            self.audio_handler.add_audio(session, msg.payload)
            session._last_audio_time = time.monotonic()

            # Start VAD monitor if not running
            if not getattr(session, "_silence_task", None):
                session._silence_task = asyncio.create_task(
                    self._vad_monitor(ws, adapter, session)
                )

        elif msg.type == MessageType.CONTROL:
            action = msg.payload.get("action", "") if isinstance(msg.payload, dict) else ""

            if action == "listen":
                state = msg.payload.get("state", "")
                if state == "start":
                    self.audio_handler.start_listening(session)
                    session._last_audio_time = time.monotonic()
                    logger.info("gateway.listen_start")
                elif state == "stop":
                    # Cancel silence detector
                    if getattr(session, "_silence_task", None):
                        session._silence_task.cancel()
                        session._silence_task = None
                    audio = self.audio_handler.stop_listening(session)
                    if audio:
                        await self._process_and_respond(ws, adapter, session, audio)

            elif action == "abort":
                if getattr(session, "_silence_task", None):
                    session._silence_task.cancel()
                    session._silence_task = None
                self.audio_handler.abort(session)
                out = OutboundMessage(
                    type=MessageType.CONTROL,
                    payload={"type": "tts", "state": "stop"},
                )
                await ws.send_text(await adapter.encode(out))

        elif msg.type == MessageType.TEXT:
            text = msg.payload if isinstance(msg.payload, str) else str(msg.payload)
            if text:
                await self._process_text_and_respond(ws, adapter, session, text)

        elif msg.type == MessageType.TOUCH:
            await self._handle_touch(ws, adapter, session, msg)

        elif msg.type == MessageType.HEARTBEAT:
            pass

    async def _vad_monitor(self, ws, adapter, session):
        """Monitor VAD state and trigger processing when speech ends.

        Instead of a fixed timeout, this checks the AudioHandler's VAD state
        every 100ms. Processing is triggered only when:
        1. Speech was detected (not just noise)
        2. Followed by sufficient silence (VAD says speech_complete)
        """
        MAX_WAIT = 30.0  # absolute max wait time
        try:
            start = time.monotonic()
            while time.monotonic() - start < MAX_WAIT:
                await asyncio.sleep(0.1)

                if self.audio_handler.is_speech_complete(session):
                    audio = self.audio_handler.stop_listening(session)
                    if audio:
                        logger.info("gateway.vad_trigger bytes=%d", len(audio))
                        session._processing = True
                        try:
                            await self._process_and_respond(ws, adapter, session, audio)
                        finally:
                            session._processing = False
                        # Restart listening for next utterance
                        self.audio_handler.start_listening(session)
                        session._silence_task = asyncio.create_task(
                            self._vad_monitor(ws, adapter, session)
                        )
                    return

            # Max wait reached without speech — restart listening
            logger.info("gateway.vad_timeout no speech detected")
            self.audio_handler.stop_listening(session)
            self.audio_handler.start_listening(session)
            session._silence_task = asyncio.create_task(
                self._vad_monitor(ws, adapter, session)
            )
        except asyncio.CancelledError:
            pass

    async def _process_text_and_respond(self, ws, adapter, session, text: str):
        """Process text input through AI pipeline with streaming response."""
        try:
            # Send thinking indicator
            thinking = OutboundMessage(
                type=MessageType.TEXT,
                payload="",
                metadata={"state": "start"},
            )
            await ws.send_text(await adapter.encode(thinking))

            full_text = ""
            async for chunk in self.orchestrator.process_text_stream(session, text):
                if chunk.is_done:
                    full_text = chunk.full_text or full_text
                    break

                # Send each sentence immediately
                text_out = OutboundMessage(
                    type=MessageType.TEXT,
                    payload=chunk.text,
                    metadata={"state": "sentence"},
                )
                await ws.send_text(await adapter.encode(text_out))
                full_text += chunk.text

                # Send audio for this sentence
                if chunk.audio_data:
                    audio_out = AudioHandler.make_audio_response(chunk.audio_data)
                    raw = await adapter.encode(audio_out)
                    if isinstance(raw, list):
                        for frame in raw:
                            await ws.send_bytes(frame)
                    elif isinstance(raw, bytes):
                        await ws.send_bytes(raw)

            # Send stop signal
            done = OutboundMessage(
                type=MessageType.TEXT,
                payload="",
                metadata={"state": "stop"},
            )
            await ws.send_text(await adapter.encode(done))

            await self.session_manager.add_to_history(
                session.session_id, "user", text
            )
            await self.session_manager.add_to_history(
                session.session_id, "assistant", full_text
            )

        except Exception:
            logger.exception("gateway.text_pipeline_error")
            error_out = OutboundMessage(
                type=MessageType.CONTROL,
                payload={"type": "tts", "state": "stop"},
            )
            await ws.send_text(await adapter.encode(error_out))

    async def _handle_touch(self, ws, adapter, session, msg):
        """Forward touch event to ai-core and optionally trigger a response."""
        payload = msg.payload if isinstance(msg.payload, dict) else {}
        try:
            result = await self.orchestrator.process_touch(session, payload)
            if result and result.get("text"):
                # Touch triggered a verbal response
                text_out = OutboundMessage(
                    type=MessageType.TEXT,
                    payload=result["text"],
                    metadata={"state": "sentence"},
                )
                await ws.send_text(await adapter.encode(text_out))

                if result.get("audio_data"):
                    audio_out = AudioHandler.make_audio_response(result["audio_data"])
                    raw = await adapter.encode(audio_out)
                    if isinstance(raw, list):
                        for frame in raw:
                            await ws.send_bytes(frame)
                    elif isinstance(raw, bytes):
                        await ws.send_bytes(raw)

                done = OutboundMessage(
                    type=MessageType.TEXT,
                    payload="",
                    metadata={"state": "stop"},
                )
                await ws.send_text(await adapter.encode(done))
        except Exception:
            logger.exception("gateway.touch_error")

    async def _process_and_respond(self, ws, adapter, session, audio_data: bytes):
        """Process audio through AI pipeline with streaming response.

        Sets session._playing = True during TTS playback to suppress echo
        from the device's microphone picking up the speaker output.
        After all audio is sent, waits for estimated playback duration
        before resuming listening.
        """
        try:
            logger.info("gateway.responding start")
            thinking = OutboundMessage(
                type=MessageType.TEXT,
                payload="",
                metadata={"state": "start"},
            )
            await ws.send_text(await adapter.encode(thinking))

            # Enter playing state — suppress incoming audio during TTS
            session._playing = True
            total_opus_frames = 0
            full_text = ""
            user_text = ""

            async for chunk in self.orchestrator.process_audio_stream(session, audio_data):
                if chunk.is_done:
                    full_text = chunk.full_text or full_text
                    user_text = chunk.user_text
                    break

                logger.info("gateway.sending sentence=%s audio=%d",
                            chunk.text[:30], len(chunk.audio_data) if chunk.audio_data else 0)
                text_out = OutboundMessage(
                    type=MessageType.TEXT,
                    payload=chunk.text,
                    metadata={"state": "sentence"},
                )
                await ws.send_text(await adapter.encode(text_out))
                full_text += chunk.text

                if chunk.audio_data:
                    audio_out = AudioHandler.make_audio_response(chunk.audio_data)
                    raw = await adapter.encode(audio_out)
                    if isinstance(raw, list):
                        logger.info("gateway.sending %d opus frames", len(raw))
                        total_opus_frames += len(raw)
                        # Send frames in small batches — fast enough to keep
                        # device buffer full, with tiny yields to stay async
                        for i, frame in enumerate(raw):
                            await ws.send_bytes(frame)
                            if i % 10 == 9:  # yield every 10 frames
                                await asyncio.sleep(0)
                    elif isinstance(raw, bytes):
                        await ws.send_bytes(raw)

            # Send stop signal
            done = OutboundMessage(
                type=MessageType.TEXT,
                payload="",
                metadata={"state": "stop"},
            )
            await ws.send_text(await adapter.encode(done))

            # Wait for device to finish playing all buffered audio
            playback_secs = total_opus_frames * 0.06 + 0.5
            logger.info("gateway.responding done text=%s frames=%d wait=%.1fs",
                        full_text[:50], total_opus_frames, playback_secs)
            await asyncio.sleep(playback_secs)

            # Resume listening
            session._playing = False

            if user_text:
                await self.session_manager.add_to_history(
                    session.session_id, "user", user_text
                )
            await self.session_manager.add_to_history(
                session.session_id, "assistant", full_text
            )

        except Exception:
            session._playing = False
            logger.exception("gateway.pipeline_error")
            error_out = OutboundMessage(
                type=MessageType.CONTROL,
                payload={"type": "tts", "state": "stop"},
            )
            await ws.send_text(await adapter.encode(error_out))
