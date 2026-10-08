"""WebSocket server core - handles connections and dispatches to protocol adapters."""

import asyncio
import contextlib
import hashlib
import json
import time

import structlog

from fastapi import WebSocket, WebSocketDisconnect

from gateway.config import settings
from gateway.protocols.base import MessageType, OutboundMessage
from gateway.protocols.registry import registry
from gateway.session import DeviceRegistryUnavailable, SessionManager
from gateway.handlers.audio import AudioHandler
from gateway.latency import latency_tracker
from gateway.life import LifeLoop
from gateway.pipeline.orchestrator import PipelineOrchestrator
from gateway.playback import PlaybackChannel
from gateway.plugins import match_plugin
from gateway.reply import TurnStyle, render_turn, speech_lock

logger = structlog.get_logger()


def _log_turn_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("gateway.turn_task_failed", error=type(task.exception()).__name__)


class WebSocketServer:
    def __init__(self):
        self.session_manager = SessionManager()
        self.audio_handler = AudioHandler(
            dashscope_api_key=settings.dashscope_api_key,
        )
        self.orchestrator = PipelineOrchestrator()
        # Gateway-side servo face: PAD-driven autonomous expressions. Enabled
        # when FACE_HOST is set and the gateway (not the device body) can
        # reach the ESP8266 on the current network topology.
        self.face_engine = None
        if settings.face_host:
            try:
                from gateway import playback as _playback
                from gateway.face_engine import PadFaceEngine

                self.face_engine = PadFaceEngine(settings.face_host)
                self.face_engine.start()
                _playback.speaking_hook = self.face_engine.on_speaking
                _playback.audio_hook = self.face_engine.feed_audio
                logger.info("gateway.face_engine_started", host=settings.face_host)
            except Exception:
                self.face_engine = None
                logger.exception("gateway.face_engine_init_failed")

    async def startup(self):
        await self.session_manager.connect()

    async def shutdown(self):
        await self.orchestrator.close()

    async def _confirm_playback_receipts(
        self,
        receipts: set[str],
        *,
        played: bool,
        detail: str = "",
    ) -> None:
        """Commit speech command terminal state after the device playback boundary."""
        for receipt in list(receipts):
            try:
                await self.orchestrator.confirm_playback(
                    receipt,
                    played=played,
                    detail=detail,
                )
            except Exception:
                logger.exception("gateway.playback_receipt_failed", receipt=receipt)
        receipts.clear()

    async def _runtime_dialogue_loop(self, ws, adapter, session) -> None:
        """Continuously render speech triggered by perception/system events."""
        while True:
            receipt: str | None = None
            try:
                chunk = await self.orchestrator.process_next_runtime_dialogue(session)
                receipt = chunk.playback_receipt
                interrupted = False
                # waits for any reply playing now (voice, text or touch)
                async with speech_lock(session), PlaybackChannel(ws, adapter, session) as pb:
                    await self._send_expression(ws, adapter, chunk)
                    await pb.send_sentence(chunk.text)
                    if chunk.audio_data:
                        await pb.send_clip(chunk.audio_data)
                    await pb.finish(settle=False)
                    interrupted = pb.interrupted
                if receipt:
                    await self.orchestrator.confirm_playback(
                        receipt,
                        played=not interrupted,
                        detail="user barge-in interrupted playback" if interrupted else "",
                    )
                    receipt = None
            except asyncio.CancelledError:
                if receipt:
                    await self.orchestrator.confirm_playback(
                        receipt,
                        played=False,
                        detail="device connection closed",
                    )
                raise
            except Exception:
                if receipt:
                    await self.orchestrator.confirm_playback(
                        receipt,
                        played=False,
                        detail="unsolicited playback error",
                    )
                logger.exception("gateway.runtime_dialogue_error")
                await asyncio.sleep(0.2)
            # No session-flag reset here: PlaybackChannel restores the flags it
            # claimed, and clearing them blindly broke a turn playing meanwhile.

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
            if settings.character_runtime_url:
                await self.orchestrator.bind_runtime_session(session)
            session._last_activity = time.monotonic()
            logger.info(
                "gateway.device_connected",
                device_id=device_id,
                protocol=adapter.name,
                session_id=session.session_id,
            )

            # Start the life loop — idle hums/yawns/snores + thinking fillers
            session._life = LifeLoop(self, ws, adapter, session)
            session._life.start()
            await self._send_control(
                ws,
                adapter,
                {
                    "type": "session",
                    "session_id": session.session_id,
                    "end_user_id": session.end_user_id,
                    "character_id": session.character_id,
                    "character_name": getattr(session, "character_name", None),
                },
            )
            await self._push_relationship_snapshot(ws, adapter, session)

            # Keep one configured character voice online even when a visual or
            # system event (rather than microphone speech) caused the line.
            runtime_dialogue_task = None
            voice_device = settings.character_runtime_voice_device_id
            # Lane B without an explicit voice device: every session is the
            # agent's voice body. Web sessions auto-bind to whatever DB
            # character exists — never the runtime agent id — so the old
            # equality check silently muted the character in every browser.
            owns_runtime_voice = device_id == voice_device if voice_device else True
            if settings.character_runtime_url and owns_runtime_voice:
                runtime_dialogue_task = asyncio.create_task(
                    self._runtime_dialogue_loop(ws, adapter, session),
                    name=f"runtime-dialogue-{session.session_id}",
                )

            # Start idle timeout checker
            async def _idle_checker():
                while True:
                    await asyncio.sleep(10)
                    idle = time.monotonic() - getattr(session, "_last_activity", time.monotonic())
                    if idle > settings.idle_timeout_s:
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
        except PermissionError:
            logger.warning("gateway.device_ownership_rejected")
            with contextlib.suppress(Exception):
                await ws.close(code=4003, reason="Device belongs to a different runtime identity")
        except DeviceRegistryUnavailable:
            logger.warning("gateway.device_registry_unavailable")
            with contextlib.suppress(Exception):
                await ws.close(code=1013, reason="Device registry temporarily unavailable")
        except Exception:
            logger.exception("gateway.connection_error")
        finally:
            if "idle_task" in locals():
                idle_task.cancel()
            if "runtime_dialogue_task" in locals() and runtime_dialogue_task is not None:
                runtime_dialogue_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runtime_dialogue_task
            if "session" in locals():
                self._cancel_turns(session)
                life = getattr(session, "_life", None)
                if life:
                    life.cancel()
                # The VAD monitor coroutine outlives the socket otherwise and
                # keeps writing to a closed connection.
                silence_task = getattr(session, "_silence_task", None)
                if silence_task:
                    silence_task.cancel()
                    session._silence_task = None
                self.audio_handler.release(session)
                await self.orchestrator.close_session_runtime(session)
                await self.session_manager.remove_session(session.session_id)

    def _spawn_turn(self, session, coro) -> asyncio.Task:
        """Run a reply turn off the receive loop, in arrival order per session.

        Awaiting a turn inline froze the socket for the whole decision (seconds
        on a local model): abort, barge-in audio and camera frames went unread."""
        lock = getattr(session, "_turn_lock", None)
        if lock is None:
            lock = session._turn_lock = asyncio.Lock()
        tasks = getattr(session, "_turn_tasks", None)
        if tasks is None:
            tasks = session._turn_tasks = set()

        async def run():
            try:
                async with lock:
                    await coro
            finally:
                coro.close()  # a turn cancelled while still queued never started

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        task.add_done_callback(_log_turn_failure)
        return task

    @staticmethod
    def _cancel_turns(session) -> None:
        for task in list(getattr(session, "_turn_tasks", ()) or ()):
            task.cancel()

    async def _handle_message(self, ws, adapter, session, msg):
        """Route message to appropriate handler."""
        if msg.type != MessageType.AUDIO:
            # Typing, touching or controlling is activity too: a text-only client
            # was idle-closed after idle_timeout_s while chatting.
            session._last_activity = time.monotonic()
        if msg.type == MessageType.AUDIO:
            # During TTS playback: check for user interrupt (barge-in)
            if getattr(session, "_playing", False):
                self._check_interrupt(session, msg.payload)
                return

            self.audio_handler.add_audio(session, msg.payload)
            session._last_audio_time = time.monotonic()
            # A device actively streaming mic audio is not idle — without this,
            # always-on bodies (e.g. the Pi thin client) get idle-closed mid-turn.
            session._last_activity = time.monotonic()

            # Start VAD monitor if not running (a finished task counts as not running)
            task = getattr(session, "_silence_task", None)
            if task is None or task.done():
                session._silence_task = asyncio.create_task(self._vad_monitor(ws, adapter, session))

        elif msg.type == MessageType.CONTROL:
            action = msg.payload.get("action", "") if isinstance(msg.payload, dict) else ""

            if action == "listen":
                state = msg.payload.get("state", "")
                if state == "start":
                    mic_format = str(msg.payload.get("format", "opus")).lower()
                    session._mic_pcm = mic_format == "pcm16"
                    self.audio_handler.start_listening(session, pcm=session._mic_pcm)
                    session._last_audio_time = time.monotonic()
                    logger.info("gateway.listen_start")
                elif state == "stop":
                    # Cancel silence detector
                    if getattr(session, "_silence_task", None):
                        session._silence_task.cancel()
                        session._silence_task = None
                    audio = self.audio_handler.stop_listening(session)
                    if audio:
                        self._spawn_turn(session, self._process_and_respond(ws, adapter, session, audio))

            elif action == "event_choice":
                await self._handle_event_choice(
                    ws,
                    adapter,
                    session,
                    msg.payload.get("event_id", ""),
                    int(msg.payload.get("choice_index", 0)),
                )

            elif action == "set_app_mode":
                await self._handle_set_app_mode(
                    ws, adapter, session, msg.payload.get("app_mode", "dating_sim")
                )

            elif action == "abort":
                if getattr(session, "_silence_task", None):
                    session._silence_task.cancel()
                    session._silence_task = None
                self._cancel_turns(session)  # stop the reply that is thinking or playing
                self.audio_handler.abort(session)
                out = OutboundMessage(
                    type=MessageType.CONTROL,
                    payload={"type": "tts", "state": "stop"},
                )
                await ws.send_text(await adapter.encode(out))

            elif action == "reaction_event":
                await self._handle_reaction_event(ws, adapter, session, msg.payload)

            elif action == "face_pos":
                # Device camera saw a human face — servo-eye tracking
                face_engine = getattr(self, "face_engine", None)
                if face_engine:
                    face_engine.on_face_pos(msg.payload.get("dx"), msg.payload.get("dy"))

        elif msg.type == MessageType.TEXT:
            # Camera frame upload (reply to a "capture" control we sent)
            if isinstance(msg.payload, dict) and msg.payload.get("type") == "vision_frame":
                fut = getattr(session, "_pending_frame", None)
                if fut is not None and not fut.done():
                    fut.set_result(msg.payload.get("data") or "")
                return
            text = msg.payload if isinstance(msg.payload, str) else str(msg.payload)
            if text:

                async def _text_turn(turn_text=text):
                    # off the receive loop, so a camera frame reply can still arrive
                    image = await self._vision_frame_for(ws, adapter, session, turn_text)
                    await self._process_text_and_respond(ws, adapter, session, turn_text, image)

                self._spawn_turn(session, _text_turn())

        elif msg.type == MessageType.TOUCH:
            self._spawn_turn(session, self._handle_touch(ws, adapter, session, msg))

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
            if getattr(session, "_mic_pcm", False):
                pcm = opus_data  # body streams raw PCM16 (no WebCodecs)
                if not hasattr(session, "_interrupt_count"):
                    session._interrupt_count = 0
            else:
                decoder = getattr(session, "_interrupt_decoder", None)
                if not decoder:
                    import opuslib

                    session._interrupt_decoder = opuslib.Decoder(16000, 1)
                    decoder = session._interrupt_decoder
                    session._interrupt_count = 0

                pcm = decoder.decode(opus_data, 960, decode_fec=False)
            if len(pcm) < 4:
                return
            samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
            rms = (sum(s * s for s in samples) / len(samples)) ** 0.5

            # High energy = user is trying to speak over TTS
            # Threshold must be well above speaker echo level (~3000-8000 RMS)
            if rms > settings.barge_in_rms_threshold:
                session._interrupt_count += 1
                if session._interrupt_count >= settings.barge_in_sustain_frames:
                    session._interrupted = True
                    logger.info("gateway.barge_in detected rms=%d", int(rms))
            else:
                session._interrupt_count = max(0, getattr(session, "_interrupt_count", 0) - 1)
        except Exception:
            logger.debug("gateway.barge_in_decode_error", exc_info=True)

    def _rearm_listening(self, ws, adapter, session) -> None:
        """Listen for the next utterance (same mic format) with a fresh VAD monitor.

        Every way a voice turn ends comes back here: a browser sends "listen
        start" only once, so a turn that forgot to re-arm left the mic deaf."""
        self.audio_handler.start_listening(session, pcm=getattr(session, "_mic_pcm", False))
        session._last_audio_time = time.monotonic()
        session._silence_task = asyncio.create_task(self._vad_monitor(ws, adapter, session))

    async def _vad_monitor(self, ws, adapter, session):
        """Monitor VAD state and trigger processing when speech ends.

        Instead of a fixed timeout, this checks the AudioHandler's VAD state
        every 100ms. Processing is triggered only when:
        1. Speech was detected (not just noise)
        2. Followed by sufficient silence (VAD says speech_complete)
        Whatever happens, listening is re-armed afterwards (unless cancelled).
        """
        MAX_WAIT = 30.0  # absolute max wait time
        try:
            start = time.monotonic()
            while time.monotonic() - start < MAX_WAIT:
                await asyncio.sleep(0.1)
                if not self.audio_handler.is_speech_complete(session):
                    continue
                # Anchor for first-word latency: VAD said the user stopped talking
                t_speech_end = time.monotonic()
                # Try streaming ASR first (low latency)
                asr_text = await self.audio_handler.get_streaming_asr_result(session)
                session._t_speech_end = t_speech_end
                session._asr_finalize_ms = (time.monotonic() - t_speech_end) * 1000
                audio = self.audio_handler.stop_listening(session)
                try:
                    await self._voice_turn(ws, adapter, session, asr_text, audio)
                finally:
                    session._processing = False
                break
            else:
                logger.info("gateway.vad_timeout no speech detected")
                self.audio_handler.stop_listening(session)
            self._rearm_listening(ws, adapter, session)
        except asyncio.CancelledError:
            pass

    async def _voice_turn(self, ws, adapter, session, asr_text: str | None, audio: bytes | None):
        """One finished utterance: plugin answer, batch-ASR fallback or the full pipeline."""
        # Streaming ASR failed or returned garbage: fall back to batch ASR in AI Core.
        if not asr_text or len(asr_text) < 2 or asr_text.startswith("sentence_id"):
            if audio and asr_text:
                logger.info("gateway.streaming_asr_fallback bad=%s", asr_text[:30])
            if audio:
                session._processing = True
                await self._process_and_respond(ws, adapter, session, audio)
            else:
                logger.info("gateway.vad_trigger empty asr")
            return

        logger.info("gateway.vad_trigger asr=%s", asr_text[:50])
        session._last_activity = time.monotonic()
        if getattr(session, "_life", None):
            session._life.notify_activity()

        # Plugins first: simple queries (time, date, math) skip the brain
        plugin_result = match_plugin(asr_text)
        if plugin_result:
            handler, name = plugin_result
            try:
                reply = handler(asr_text)
                if reply:
                    logger.info("gateway.plugin hit=%s reply=%s", name, reply[:30])
                    await self._send_quick_reply(ws, adapter, session, reply)
                    return
            except Exception:
                logger.exception("gateway.plugin_error name=%s", name)

        image_data = await self._vision_frame_for(ws, adapter, session, asr_text)
        session._processing = True
        await self._process_text_and_respond_streaming(
            ws, adapter, session, asr_text, image_data=image_data
        )

    async def _vision_frame_for(self, ws, adapter, session, text: str) -> str | None:
        """A camera frame for a vision utterance, or None when it would be wasted.

        Only the legacy ai-core pipeline consumes images; the Character Runtime
        path ignores them, so capturing would only add up to 5 s of latency."""
        if not self._is_vision_trigger(text) or settings.character_runtime_url:
            return None
        logger.info("gateway.vision_trigger text=%s", text[:30])
        # "" = vision turn whose capture failed: ai-core says honestly it can't see
        return await self._request_frame(ws, adapter, session) or ""

    # Utterances that ask the character to look at something through the
    # device camera. Substring match on the ASR text, same style as plugins.
    VISION_TRIGGERS = (
        "看看这",
        "看看我",
        "看一下这",
        "看一眼",
        "这是什么",
        "这个是什么",
        "我拿的是什么",
        "我手里",
        "你看到了什么",
        "能看到",
        "看到我",
        "看得到",
        "前面有什么",
        "帮我看看",
        "识别一下",
        "猜猜这是什么",
        "拍照",
        "拍张照",
        "拍个照",
        "穿的什么",
        "穿什么",
        "穿了什么",
        "什么衣服",
        "我长什么样",
        "我是什么样",
    )

    def _is_vision_trigger(self, text: str) -> bool:
        t = (text or "").replace(" ", "")
        return any(k in t for k in self.VISION_TRIGGERS)

    async def _request_frame(self, ws, adapter, session, timeout_s: float = 5.0) -> str | None:
        """Ask the device for one camera frame; None if it can't or won't.

        Devices without a camera simply never answer — the timeout keeps the
        turn moving and the pipeline degrades to an honest "看不到" reply.
        """
        loop = asyncio.get_running_loop()
        session._pending_frame = loop.create_future()
        try:
            out = OutboundMessage(type=MessageType.CONTROL, payload={"type": "capture"})
            await ws.send_text(await adapter.encode(out))
            frame = await asyncio.wait_for(session._pending_frame, timeout=timeout_s)
            return frame or None
        except (TimeoutError, asyncio.TimeoutError):
            logger.info("gateway.vision_capture_timeout device=%s", session.device_id)
            return None
        except Exception:
            logger.exception("gateway.vision_capture_error")
            return None
        finally:
            session._pending_frame = None

    async def _send_control(self, ws, adapter, payload: dict) -> None:
        """Forward a control payload (emotion / relationship / event …) to the device.

        Devices that don't know the payload type ignore it. Failures never
        interrupt the audio playback path.
        """
        try:
            out = OutboundMessage(type=MessageType.CONTROL, payload=payload)
            await ws.send_text(await adapter.encode(out))
        except Exception:
            logger.exception("gateway.control_send_error", payload_type=payload.get("type"))

    async def _send_emotion(self, ws, adapter, chunk):
        """Forward a per-turn emotion event (PAD snapshot + hardware hint)."""
        face_engine = getattr(self, "face_engine", None)
        if face_engine and chunk.pad:
            try:
                face_engine.on_pad(chunk.pad)
            except Exception:
                logger.exception("gateway.face_engine_error")
        await self._send_control(
            ws,
            adapter,
            {
                "type": "emotion",
                "emotion": chunk.emotion,
                "pad": chunk.pad,
                "hardware": chunk.hardware,
                "causes": chunk.causes or [],
                "energy": chunk.energy,
            },
        )

    async def _send_expression(self, ws, adapter, chunk):
        """Expression cue for the sentence whose audio follows next on this socket.

        Sent immediately before the sentence's clip so the client binds it to that
        clip and applies it when the clip actually starts playing (TTS audio lags
        the text). Clients that do not know the type ignore it."""
        if chunk.expression:
            await self._send_control(ws, adapter, {**chunk.expression, "type": "expression"})

    async def _send_relationship(self, ws, adapter, chunk):
        if chunk.relationship:
            await self._send_control(ws, adapter, {**chunk.relationship, "type": "relationship"})

    @staticmethod
    def _remember_energy(session, payload: dict | None) -> None:
        """Keep the relationship's energy axis on the session for the life loop."""
        try:
            energy = (payload or {}).get("axes", {}).get("energy")
            if energy is not None:
                session._energy = int(energy)
        except (TypeError, ValueError, AttributeError):
            pass

    async def _send_event(self, ws, adapter, chunk):
        if chunk.event:
            await self._send_control(ws, adapter, {**chunk.event, "type": "event"})

    async def _handle_event_choice(self, ws, adapter, session, event_id: str, choice_index: int):
        """Scene choice from the body → ai-core → speak the canned line + push relationship."""
        if not (session.end_user_id and session.character_id and event_id):
            return
        try:
            resp = await self.orchestrator.client.post(
                f"/relationship/{session.end_user_id}/{session.character_id}/events/{event_id}/choice",
                json={"choice_index": choice_index},
            )
            if resp.status_code != 200:
                logger.warning("gateway.event_choice_rejected", status=resp.status_code)
                return
            data = resp.json()
        except Exception:
            logger.exception("gateway.event_choice_error")
            return
        if data.get("relationship"):
            await self._send_control(ws, adapter, {**data["relationship"], "type": "relationship"})
        line = data.get("response") or ""
        nxt = data.get("next_scene") or {}
        if nxt.get("dialogue"):
            line = f"{line} {nxt['dialogue']}".strip()
        if line:
            await self._send_quick_reply(ws, adapter, session, line)

    async def _handle_set_app_mode(self, ws, adapter, session, app_mode: str):
        if not (session.end_user_id and session.character_id):
            return
        try:
            resp = await self.orchestrator.client.patch(
                f"/relationship/{session.end_user_id}/{session.character_id}",
                json={"app_mode": app_mode},
            )
            if resp.status_code == 200:
                await self._send_control(ws, adapter, {**resp.json(), "type": "relationship"})
        except Exception:
            logger.exception("gateway.set_app_mode_error")

    async def _push_relationship_snapshot(self, ws, adapter, session) -> None:
        """On connect: tell the body where the relationship stands right now."""
        if not (session.end_user_id and session.character_id):
            return
        try:
            resp = await self.orchestrator.client.get(
                f"/relationship/{session.end_user_id}/{session.character_id}"
            )
            if resp.status_code == 200:
                payload = resp.json()
                self._remember_energy(session, payload)
                await self._send_control(ws, adapter, {**payload, "type": "relationship"})
        except Exception:
            logger.debug("gateway.relationship_snapshot_unavailable", exc_info=True)

    async def _send_quick_reply(self, ws, adapter, session, text: str):
        """Send a quick text+TTS reply without going through the full LLM pipeline.

        Used for plugin responses (time, date, math) that don't need AI.
        """
        try:
            async with speech_lock(session), PlaybackChannel(ws, adapter, session) as pb:
                await pb.send_start()
                await pb.send_sentence(text)

                # TTS for the reply, in the character's own voice
                try:
                    from gateway.handlers.audio_codec import mp3_to_pcm_24k, pcm_to_opus_frames

                    tts = await self.orchestrator.synthesize_tts(
                        text,
                        character_id=session.character_id,
                        brand_id=session.brand_id,
                    )
                    if tts:
                        pcm = await mp3_to_pcm_24k(tts)
                        if pcm:
                            await pb.send_sentence_start()
                            await pb.send_frames(pcm_to_opus_frames(pcm, sample_rate=24000))
                except Exception:
                    logger.exception("gateway.quick_reply_tts_error")

                await pb.finish(wait_drain=False)
            logger.info("gateway.quick_reply sent: %s", text[:30])

        except Exception:
            logger.exception("gateway.quick_reply_error")

    def _record_voice_turn(
        self,
        session,
        t_ref: float,
        first_chunk_ms: float | None,
        first_word_ms: float | None,
        core_stages: dict | None,
        interrupted: bool,
        route: str = "voice_turn",
    ):
        """Record one voice turn's latency: speech-end → first Opus frame.

        `respond` covers up to the last frame sent, excluding the
        playback-wait sleeps. ai-core's breakdown is merged with a
        `core_` prefix.
        """
        stages = {
            "asr_finalize": getattr(session, "_asr_finalize_ms", None),
            "first_chunk": first_chunk_ms,
            "first_word": first_word_ms,
            "respond": (time.monotonic() - t_ref) * 1000,
        }
        if core_stages:
            for k, v in core_stages.items():
                stages[f"core_{k}"] = v
        # numbers only: a stage may carry a marker such as {"asr_only": "no_transcript"}
        stages = {
            k: v for k, v in stages.items() if isinstance(v, int | float) and not isinstance(v, bool)
        }
        session._asr_finalize_ms = None
        latency_tracker.record_turn(route, stages)
        logger.info(
            "gateway.latency",
            route=route,
            interrupted=interrupted,
            **{k: int(v) for k, v in stages.items()},
        )

    async def _process_text_and_respond_streaming(
        self, ws, adapter, session, text: str, image_data: str | None = None
    ):
        """A voice turn from streaming ASR: paced playback, barge-in, thinking filler."""
        life = getattr(session, "_life", None)
        return await render_turn(
            self,
            ws,
            adapter,
            session,
            self.orchestrator.process_text_stream(
                session, text, stream_audio=True, image_data=image_data
            ),
            TurnStyle(
                voice=True,
                route="voice_turn",
                filler=life.pop_filler() if life else None,
                user_text=text,
            ),
        )

    async def _process_text_and_respond(
        self, ws, adapter, session, text: str, image_data: str | None = None
    ):
        """A typed turn: the device buffers freely, no barge-in."""
        return await render_turn(
            self,
            ws,
            adapter,
            session,
            self.orchestrator.process_text_stream(session, text, image_data=image_data),
            TurnStyle(voice=False, user_text=text),
        )

    async def _handle_touch(self, ws, adapter, session, msg):
        """Forward touch event to ai-core and optionally trigger a response."""
        payload = msg.payload if isinstance(msg.payload, dict) else {}
        if getattr(session, "_life", None):
            session._life.notify_activity()
        receipt = None
        try:
            result = await self.orchestrator.process_touch(session, payload)
            receipt = result.get("playback_receipt") if result else None
            state = result.get("cognitive_state") if result else None
            if state:
                from gateway.pipeline.orchestrator import StreamChunk

                await self._send_emotion(
                    ws,
                    adapter,
                    StreamChunk(
                        text="",
                        audio_data=None,
                        index=-1,
                        kind="emotion",
                        emotion=state.get("emotion", ""),
                        pad=state.get("pad"),
                    ),
                )
            if result and result.get("text"):
                # Touch triggered a verbal response (no "start": touch replies
                # never began a thinking indicator on the device)
                async with speech_lock(session), PlaybackChannel(
                    ws, adapter, session, pace=False, check_interrupt=False, claim=False
                ) as pb:
                    await pb.send_sentence(result["text"])
                    if result.get("audio_data"):
                        await pb.send_clip(result["audio_data"], sentence_start=False)
                    await pb.finish(settle=False)
                if receipt:
                    await self.orchestrator.confirm_playback(
                        receipt,
                        played=not pb.interrupted,
                        detail="touch playback interrupted" if pb.interrupted else "",
                    )
                    receipt = None
        except asyncio.CancelledError:
            if receipt:
                await self.orchestrator.confirm_playback(
                    receipt, played=False, detail="touch playback cancelled"
                )
            raise
        except Exception:
            if receipt:
                await self.orchestrator.confirm_playback(
                    receipt, played=False, detail="touch playback error"
                )
            logger.exception("gateway.touch_error")

    async def _handle_reaction_event(self, ws, adapter, session, payload: dict):
        """Forward normalized device events to ai-core reaction loop."""
        payload = payload if isinstance(payload, dict) else {}
        event_type = str(payload.get("event_type") or "").strip()
        if not event_type:
            logger.warning("gateway.reaction_event_missing_type")
            return
        try:
            result = await self.orchestrator.process_reaction_event(
                session,
                event_type=event_type,
                event=payload.get("event") or {},
                context=payload.get("context") or {},
                device_manifest=payload.get("device_manifest") or {},
                device_state=payload.get("device_state") or {},
            )
            out = OutboundMessage(
                type=MessageType.CONTROL,
                payload={"type": "reaction", **result},
            )
            await ws.send_text(await adapter.encode(out))
            if getattr(session, "_life", None):
                session._life.notify_activity()
        except Exception:
            logger.exception("gateway.reaction_event_error")

    async def _process_and_respond(self, ws, adapter, session, audio_data: bytes):
        """A voice turn from batch ASR (ai-core transcribes); the user text comes back
        on the done chunk. A legacy-path vision request re-runs as a streaming turn."""
        result = await render_turn(
            self,
            ws,
            adapter,
            session,
            self.orchestrator.process_audio_stream(session, audio_data),
            TurnStyle(voice=True, route="voice_turn_batch"),
        )
        if result.need_vision:
            logger.info("gateway.vision_trigger text=%s", result.need_vision[:30])
            image = await self._request_frame(ws, adapter, session) or ""
            return await self._process_text_and_respond_streaming(
                ws, adapter, session, result.need_vision, image_data=image
            )
        return result
