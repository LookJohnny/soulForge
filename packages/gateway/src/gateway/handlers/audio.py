"""Audio frame handler - manages audio streaming between device and AI pipeline.

Supports Opus packet decoding and server-side VAD (Voice Activity Detection).
Only triggers processing when real speech is detected, ignoring ambient noise.
"""

import logging
import struct

import opuslib

from gateway.protocols.base import MessageType, OutboundMessage
from gateway.session import Session

logger = logging.getLogger(__name__)

# Energy-based VAD configuration (no external dependency)
VAD_FRAME_MS = 20            # analysis window
VAD_FRAME_BYTES = 16000 * 2 * VAD_FRAME_MS // 1000  # 640 bytes per 20ms frame
SPEECH_ENERGY_THRESHOLD = 800   # RMS energy threshold for speech detection
SPEECH_START_FRAMES = 3      # consecutive voiced frames to confirm speech start
SILENCE_END_FRAMES = 20      # consecutive silent frames to confirm speech end (~400ms)


class AudioHandler:
    """Collects audio frames from device with Opus decoding and VAD filtering.

    Flow:
    1. Device sends Opus packets → decoded to PCM
    2. VAD analyzes each PCM frame for voice activity
    3. Only buffers audio after speech is detected
    4. Signals speech_complete when silence follows speech
    """

    def __init__(self):
        self._buffers: dict[str, bytearray] = {}
        self._decoders: dict[str, opuslib.Decoder] = {}
        self._vad_states: dict[str, dict] = {}

    def start_listening(self, session: Session):
        """Start collecting audio for a session."""
        self._buffers[session.session_id] = bytearray()
        self._decoders[session.session_id] = opuslib.Decoder(16000, 1)
        self._vad_states[session.session_id] = {
            "pcm_pending": bytearray(),   # accumulates PCM until we have a full VAD frame
            "speech_started": False,
            "voiced_count": 0,            # consecutive voiced frames
            "silent_count": 0,            # consecutive silent frames after speech
            "speech_complete": False,      # set True when speech→silence detected
            "pre_speech_buf": bytearray(), # small buffer of audio right before speech
        }
        logger.info("vad.listen_start session=%s", session.session_id)

    def add_audio(self, session: Session, audio_data: bytes):
        """Decode Opus packet to PCM, run VAD, buffer if speech detected."""
        sid = session.session_id
        buf = self._buffers.get(sid)
        state = self._vad_states.get(sid)
        if buf is None or state is None:
            return

        # Decode Opus to PCM
        decoder = self._decoders.get(sid)
        if decoder:
            try:
                pcm = decoder.decode(audio_data, 960, decode_fec=False)
            except Exception:
                pcm = audio_data
        else:
            pcm = audio_data

        # Accumulate PCM for VAD frame processing
        state["pcm_pending"].extend(pcm)

        # Process complete VAD frames (20ms = 640 bytes each)
        while len(state["pcm_pending"]) >= VAD_FRAME_BYTES:
            frame = bytes(state["pcm_pending"][:VAD_FRAME_BYTES])
            del state["pcm_pending"][:VAD_FRAME_BYTES]

            # Energy-based VAD: compute RMS of the frame
            samples = struct.unpack(f"<{len(frame)//2}h", frame)
            rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
            is_speech = rms > SPEECH_ENERGY_THRESHOLD

            if is_speech:
                state["voiced_count"] += 1
                state["silent_count"] = 0

                if not state["speech_started"] and state["voiced_count"] >= SPEECH_START_FRAMES:
                    state["speech_started"] = True
                    # Include pre-speech buffer for natural onset
                    buf.extend(state["pre_speech_buf"])
                    state["pre_speech_buf"].clear()
                    logger.info("vad.speech_start session=%s", sid)

                if state["speech_started"]:
                    buf.extend(frame)
            else:
                state["voiced_count"] = 0
                state["silent_count"] += 1

                if state["speech_started"]:
                    buf.extend(frame)  # include trailing silence
                    if state["silent_count"] >= SILENCE_END_FRAMES:
                        state["speech_complete"] = True
                        logger.info("vad.speech_end session=%s bytes=%d", sid, len(buf))
                else:
                    # Keep a rolling pre-speech buffer (~200ms)
                    state["pre_speech_buf"].extend(frame)
                    if len(state["pre_speech_buf"]) > VAD_FRAME_BYTES * 10:
                        del state["pre_speech_buf"][:VAD_FRAME_BYTES * 5]

    def is_speech_complete(self, session: Session) -> bool:
        """Check if VAD detected end of speech."""
        state = self._vad_states.get(session.session_id)
        return state is not None and state.get("speech_complete", False)

    def has_speech(self, session: Session) -> bool:
        """Check if any speech has been detected."""
        state = self._vad_states.get(session.session_id)
        return state is not None and state.get("speech_started", False)

    def stop_listening(self, session: Session) -> bytes | None:
        """Stop collecting and return buffered PCM audio."""
        buf = self._buffers.pop(session.session_id, None)
        self._decoders.pop(session.session_id, None)
        self._vad_states.pop(session.session_id, None)
        if buf and len(buf) > VAD_FRAME_BYTES * 5:  # at least ~100ms of audio
            logger.info("vad.collected bytes=%d duration=%.1fs", len(buf), len(buf) / 32000)
            return bytes(buf)
        return None

    def abort(self, session: Session):
        """Discard buffered audio."""
        self._buffers.pop(session.session_id, None)
        self._decoders.pop(session.session_id, None)
        self._vad_states.pop(session.session_id, None)

    @staticmethod
    def make_audio_response(audio_data: bytes) -> OutboundMessage:
        """Wrap audio bytes in an outbound message."""
        return OutboundMessage(type=MessageType.AUDIO, payload=audio_data)
