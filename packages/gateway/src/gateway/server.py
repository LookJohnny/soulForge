"""WebSocket server core - handles connections and dispatches to protocol adapters."""

import structlog

from fastapi import WebSocket, WebSocketDisconnect

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
            self.audio_handler.add_audio(session, msg.payload)

        elif msg.type == MessageType.CONTROL:
            action = msg.payload.get("action", "") if isinstance(msg.payload, dict) else ""

            if action == "listen":
                state = msg.payload.get("state", "")
                if state == "start":
                    self.audio_handler.start_listening(session)
                elif state == "stop":
                    audio = self.audio_handler.stop_listening(session)
                    if audio:
                        await self._process_and_respond(ws, adapter, session, audio)

            elif action == "abort":
                self.audio_handler.abort(session)
                out = OutboundMessage(
                    type=MessageType.CONTROL,
                    payload={"type": "tts", "state": "stop"},
                )
                await ws.send_text(await adapter.encode(out))

        elif msg.type == MessageType.HEARTBEAT:
            pass

    async def _process_and_respond(self, ws, adapter, session, audio_data: bytes):
        """Process audio through AI pipeline and send response back."""
        try:
            thinking = OutboundMessage(
                type=MessageType.TEXT,
                payload="",
                metadata={"state": "start"},
            )
            await ws.send_text(await adapter.encode(thinking))

            result = await self.orchestrator.process_audio(session, audio_data)

            text_out = OutboundMessage(
                type=MessageType.TEXT,
                payload=result["text"],
                metadata={"state": "sentence"},
            )
            await ws.send_text(await adapter.encode(text_out))

            if result.get("audio_data"):
                audio_out = AudioHandler.make_audio_response(result["audio_data"])
                raw = await adapter.encode(audio_out)
                if isinstance(raw, bytes):
                    await ws.send_bytes(raw)

            done = OutboundMessage(
                type=MessageType.TEXT,
                payload="",
                metadata={"state": "stop"},
            )
            await ws.send_text(await adapter.encode(done))

            await self.session_manager.add_to_history(
                session.session_id, "assistant", result["text"]
            )

        except Exception:
            logger.exception("gateway.pipeline_error")
            error_out = OutboundMessage(
                type=MessageType.CONTROL,
                payload={"type": "tts", "state": "stop"},
            )
            await ws.send_text(await adapter.encode(error_out))
