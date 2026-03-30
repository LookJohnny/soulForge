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
from gateway.plugins import match_plugin

logger = structlog.get_logger()


class WebSocketServer:
    def __init__(self):
        self.session_manager = SessionManager()
        self.audio_handler = AudioHandler(
            dashscope_api_key=settings.dashscope_api_key,
        )
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
            session._last_activity = time.monotonic()
            logger.info(
                "gateway.device_connected",
                device_id=device_id,
                protocol=adapter.name,
                session_id=session.session_id,
            )

            # Start idle timeout checker
            async def _idle_checker():
                IDLE_TIMEOUT = 120  # seconds
                while True:
                    await asyncio.sleep(10)
                    idle = time.monotonic() - getattr(session, "_last_activity", time.monotonic())
                    if idle > IDLE_TIMEOUT:
                        logger.info("gateway.idle_timeout device=%s", device_id)
                        await ws.close(code=1000, reason="Idle timeout")
                        return

            idle_task = asyncio.create_task(_idle_checker())

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
            if "idle_task" in locals():
                idle_task.cancel()
            if "session" in locals():
                self.audio_handler.abort(session)
                await self.session_manager.remove_session(session.session_id)

    async def _handle_message(self, ws, adapter, session, msg):
        """Route message to appropriate handler."""
        if msg.type == MessageType.AUDIO:
            # During TTS playback: check for user interrupt (barge-in)
            if getattr(session, "_playing", False):
                self._check_interrupt(session, msg.payload)
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

    def _check_interrupt(self, session, opus_data: bytes):
        """Detect user barge-in during TTS playback.

        Decodes Opus frame and checks energy level. If sustained loud audio
        is detected (user speaking over TTS), sets the interrupt flag.
        TTS playback loop checks this flag and aborts.
        """
        import struct
        try:
            decoder = getattr(session, "_interrupt_decoder", None)
            if not decoder:
                import opuslib
                session._interrupt_decoder = opuslib.Decoder(16000, 1)
                decoder = session._interrupt_decoder
                session._interrupt_count = 0

            pcm = decoder.decode(opus_data, 960, decode_fec=False)
            samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
            rms = (sum(s * s for s in samples) / len(samples)) ** 0.5

            # High energy = user is trying to speak over TTS
            # Threshold must be well above speaker echo level (~3000-8000 RMS)
            if rms > 12000:
                session._interrupt_count += 1
                if session._interrupt_count >= 8:  # ~500ms sustained loud voice
                    session._interrupted = True
                    logger.info("gateway.barge_in detected rms=%d", int(rms))
            else:
                session._interrupt_count = max(0, getattr(session, "_interrupt_count", 0) - 1)
        except Exception:
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
                    # Try streaming ASR first (low latency)
                    asr_text = await self.audio_handler.get_streaming_asr_result(session)
                    audio = self.audio_handler.stop_listening(session)

                    # If streaming ASR failed or returned garbage, fall back to batch
                    if not asr_text or len(asr_text) < 2 or asr_text.startswith("sentence_id"):
                        if audio and asr_text:
                            logger.info("gateway.streaming_asr_fallback bad=%s", asr_text[:30])
                        if audio:
                            # Fall back to sending audio to AI Core for batch ASR
                            session._processing = True
                            try:
                                await self._process_and_respond(ws, adapter, session, audio)
                            finally:
                                session._processing = False
                            self.audio_handler.start_listening(session)
                            session._silence_task = asyncio.create_task(
                                self._vad_monitor(ws, adapter, session)
                            )
                            return
                        logger.info("gateway.vad_trigger empty asr")
                        self.audio_handler.start_listening(session)
                        session._silence_task = asyncio.create_task(
                            self._vad_monitor(ws, adapter, session)
                        )
                        return

                    if asr_text:
                        logger.info("gateway.vad_trigger asr=%s", asr_text[:50])
                        session._last_activity = time.monotonic()

                        # Check plugins first — skip LLM for simple queries
                        plugin_result = match_plugin(asr_text)
                        if plugin_result:
                            handler, name = plugin_result
                            try:
                                reply = handler(asr_text)
                                if reply:
                                    logger.info("gateway.plugin hit=%s reply=%s", name, reply[:30])
                                    await self._send_quick_reply(ws, adapter, session, reply)
                                    # Restart listening
                                    self.audio_handler.start_listening(session)
                                    session._silence_task = asyncio.create_task(
                                        self._vad_monitor(ws, adapter, session)
                                    )
                                    return
                            except Exception:
                                logger.exception("gateway.plugin_error name=%s", name)

                        # No plugin match — full LLM pipeline
                        session._processing = True
                        try:
                            await self._process_text_and_respond_streaming(
                                ws, adapter, session, asr_text
                            )
                        finally:
                            session._processing = False
                    else:
                        logger.info("gateway.vad_trigger empty asr")
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

    async def _send_quick_reply(self, ws, adapter, session, text: str):
        """Send a quick text+TTS reply without going through the full LLM pipeline.

        Used for plugin responses (time, date, math) that don't need AI.
        """
        try:
            # Send text
            start_msg = OutboundMessage(
                type=MessageType.TEXT, payload="",
                metadata={"state": "start"},
            )
            await ws.send_text(await adapter.encode(start_msg))

            text_msg = OutboundMessage(
                type=MessageType.TEXT, payload=text,
                metadata={"state": "sentence"},
            )
            await ws.send_text(await adapter.encode(text_msg))

            # TTS for the reply
            try:
                from gateway.handlers.audio_codec import mp3_to_pcm_24k, pcm_to_opus_frames
                tts = await self._get_quick_tts(text)
                if tts:
                    ss = OutboundMessage(
                        type=MessageType.TEXT, payload="",
                        metadata={"state": "sentence_start"},
                    )
                    await ws.send_text(await adapter.encode(ss))

                    pcm = await mp3_to_pcm_24k(tts)
                    if pcm:
                        frames = pcm_to_opus_frames(pcm, sample_rate=24000)
                        for i, frame in enumerate(frames[:5]):
                            await ws.send_bytes(frame)
                        for frame in frames[5:]:
                            await ws.send_bytes(frame)
                            await asyncio.sleep(0.06)
            except Exception:
                logger.exception("gateway.quick_reply_tts_error")

            await asyncio.sleep(0.42)
            done_msg = OutboundMessage(
                type=MessageType.TEXT, payload="",
                metadata={"state": "stop"},
            )
            await ws.send_text(await adapter.encode(done_msg))
            logger.info("gateway.quick_reply sent: %s", text[:30])

        except Exception:
            logger.exception("gateway.quick_reply_error")

    async def _get_quick_tts(self, text: str) -> bytes | None:
        """Get TTS audio via AI Core for a short text."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Use AI Core's TTS directly — simpler than full pipeline
                from gateway.config import settings
                resp = await client.post(
                    f"{settings.ai_core_url}/tts/synthesize",
                    json={"text": text},
                    headers={"X-Service-Token": settings.service_token} if settings.service_token else {},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("audio_data"):
                        import base64
                        return base64.b64decode(data["audio_data"])
        except Exception:
            pass
        return None

    async def _process_text_and_respond_streaming(self, ws, adapter, session, text: str):
        """Process text from streaming ASR through AI pipeline with TTS playback.

        Same as _process_and_respond but takes pre-recognized text instead of
        raw audio, skipping AI Core's ASR step. Includes playback state
        management and interrupt detection.
        """
        try:
            logger.info("gateway.responding start (streaming asr: %s)", text[:30])
            thinking = OutboundMessage(
                type=MessageType.TEXT, payload="",
                metadata={"state": "start"},
            )
            await ws.send_text(await adapter.encode(thinking))

            session._playing = True
            session._interrupted = False
            session._interrupt_count = 0
            total_opus_frames = 0
            full_text = ""
            interrupted = False

            async for chunk in self.orchestrator.process_text_stream(session, text):
                if chunk.is_done:
                    full_text = chunk.full_text or full_text
                    break

                if getattr(session, "_interrupted", False):
                    logger.info("gateway.interrupted by user")
                    interrupted = True
                    break

                logger.info("gateway.sending sentence=%s audio=%d",
                            chunk.text[:30], len(chunk.audio_data) if chunk.audio_data else 0)
                text_out = OutboundMessage(
                    type=MessageType.TEXT, payload=chunk.text,
                    metadata={"state": "sentence"},
                )
                await ws.send_text(await adapter.encode(text_out))
                full_text += chunk.text

                if chunk.audio_data:
                    ss = OutboundMessage(
                        type=MessageType.TEXT, payload="",
                        metadata={"state": "sentence_start"},
                    )
                    await ws.send_text(await adapter.encode(ss))

                    audio_out = AudioHandler.make_audio_response(chunk.audio_data)
                    raw = await adapter.encode(audio_out)
                    if isinstance(raw, list):
                        n = len(raw)
                        logger.info("gateway.sending %d opus frames @24kHz", n)
                        total_opus_frames += n
                        PRE_BUFFER = 5
                        for frame in raw[:PRE_BUFFER]:
                            await ws.send_bytes(frame)
                        for frame in raw[PRE_BUFFER:]:
                            if getattr(session, "_interrupted", False):
                                interrupted = True
                                break
                            await ws.send_bytes(frame)
                            await asyncio.sleep(0.06)
                    elif isinstance(raw, bytes):
                        await ws.send_bytes(raw)

                    if interrupted:
                        break

            if interrupted:
                stop = OutboundMessage(
                    type=MessageType.TEXT, payload="",
                    metadata={"state": "stop"},
                )
                await ws.send_text(await adapter.encode(stop))
                await asyncio.sleep(0.2)
            else:
                await asyncio.sleep(0.42)
                done = OutboundMessage(
                    type=MessageType.TEXT, payload="",
                    metadata={"state": "stop"},
                )
                await ws.send_text(await adapter.encode(done))
                playback_secs = max(total_opus_frames * 0.06 - 2.0, 0.5)
                await asyncio.sleep(playback_secs)

            session._playing = False
            session._interrupted = False
            session._interrupt_count = 0

            await self.session_manager.add_to_history(
                session.session_id, "user", text
            )
            await self.session_manager.add_to_history(
                session.session_id, "assistant", full_text
            )
            logger.info("gateway.responding done text=%s frames=%d",
                        full_text[:50], total_opus_frames)

        except Exception:
            session._playing = False
            logger.exception("gateway.pipeline_error")
            error_out = OutboundMessage(
                type=MessageType.CONTROL,
                payload={"type": "tts", "state": "stop"},
            )
            await ws.send_text(await adapter.encode(error_out))

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

            # Enter playing state with interrupt detection
            session._playing = True
            session._interrupted = False
            session._interrupt_count = 0
            total_opus_frames = 0
            full_text = ""
            user_text = ""
            interrupted = False

            async for chunk in self.orchestrator.process_audio_stream(session, audio_data):
                if chunk.is_done:
                    full_text = chunk.full_text or full_text
                    user_text = chunk.user_text
                    break

                # Check if user interrupted
                if getattr(session, "_interrupted", False):
                    logger.info("gateway.interrupted by user")
                    interrupted = True
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
                    # Send sentence_start before audio (xiaozhi protocol)
                    ss = OutboundMessage(
                        type=MessageType.TEXT, payload="",
                        metadata={"state": "sentence_start"},
                    )
                    await ws.send_text(await adapter.encode(ss))

                    audio_out = AudioHandler.make_audio_response(chunk.audio_data)
                    raw = await adapter.encode(audio_out)
                    if isinstance(raw, list):
                        n = len(raw)
                        logger.info("gateway.sending %d opus frames @24kHz", n)
                        total_opus_frames += n
                        PRE_BUFFER = 5
                        for frame in raw[:PRE_BUFFER]:
                            await ws.send_bytes(frame)
                        for frame in raw[PRE_BUFFER:]:
                            # Check interrupt between frames
                            if getattr(session, "_interrupted", False):
                                logger.info("gateway.interrupted mid-sentence")
                                interrupted = True
                                break
                            await ws.send_bytes(frame)
                            await asyncio.sleep(0.06)
                    elif isinstance(raw, bytes):
                        await ws.send_bytes(raw)

                    if interrupted:
                        break

            if interrupted:
                # User interrupted — send stop immediately, skip waiting
                stop = OutboundMessage(
                    type=MessageType.TEXT, payload="",
                    metadata={"state": "stop"},
                )
                await ws.send_text(await adapter.encode(stop))
                logger.info("gateway.interrupted_stop")
                await asyncio.sleep(0.2)
            else:
                # Normal completion — wait 420ms then send stop
                await asyncio.sleep(0.42)
                done = OutboundMessage(
                    type=MessageType.TEXT, payload="",
                    metadata={"state": "stop"},
                )
                await ws.send_text(await adapter.encode(done))
                logger.info("gateway.responding done text=%s frames=%d",
                            full_text[:50], total_opus_frames)
                # Wait for device to finish playing buffered audio
                playback_secs = max(total_opus_frames * 0.06 - 2.0, 0.5)
                await asyncio.sleep(playback_secs)

            # Resume listening
            session._playing = False
            session._interrupted = False
            session._interrupt_count = 0

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
