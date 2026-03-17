"""Audio frame handler - manages audio streaming between device and AI pipeline."""

import logging

from gateway.protocols.base import MessageType, OutboundMessage
from gateway.session import Session

logger = logging.getLogger(__name__)


class AudioHandler:
    """Collects audio frames from device and dispatches to AI pipeline."""

    def __init__(self):
        self._buffers: dict[str, bytearray] = {}  # session_id -> audio buffer

    def start_listening(self, session: Session):
        """Start collecting audio for a session."""
        self._buffers[session.session_id] = bytearray()
        logger.debug(f"Started listening for session {session.session_id}")

    def add_audio(self, session: Session, audio_data: bytes):
        """Add audio chunk to buffer."""
        buf = self._buffers.get(session.session_id)
        if buf is not None:
            buf.extend(audio_data)

    def stop_listening(self, session: Session) -> bytes | None:
        """Stop collecting and return buffered audio."""
        buf = self._buffers.pop(session.session_id, None)
        if buf:
            logger.debug(
                f"Collected {len(buf)} bytes of audio for session {session.session_id}"
            )
            return bytes(buf)
        return None

    def abort(self, session: Session):
        """Discard buffered audio."""
        self._buffers.pop(session.session_id, None)

    @staticmethod
    def make_audio_response(audio_data: bytes) -> OutboundMessage:
        """Wrap audio bytes in an outbound message."""
        return OutboundMessage(type=MessageType.AUDIO, payload=audio_data)
