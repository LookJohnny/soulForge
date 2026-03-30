"""Audio frame handler - manages audio streaming between device and AI pipeline.

Supports Opus packet decoding and Silero VAD (neural network voice activity detection).
Only triggers processing when real speech is detected, robust against ambient noise.
"""

import logging
import struct

import opuslib
import torch
from silero_vad import load_silero_vad

from gateway.handlers.streaming_asr import StreamingASR
from gateway.protocols.base import MessageType, OutboundMessage
from gateway.session import Session

logger = logging.getLogger(__name__)

# Silero VAD configuration
# Silero needs 512 samples (32ms) at 16kHz per chunk
SILERO_CHUNK_SAMPLES = 512
SILERO_CHUNK_BYTES = SILERO_CHUNK_SAMPLES * 2  # 1024 bytes per chunk
SPEECH_PROB_THRESHOLD = 0.5  # Silero probability threshold for speech
SPEECH_START_FRAMES = 3      # consecutive voiced frames to confirm speech start
SILENCE_END_FRAMES = 20      # consecutive silent frames to confirm speech end (~640ms)

# Load model once at module level (shared across all sessions)
_silero_model = load_silero_vad()
logger.info("Silero VAD model loaded")


class AudioHandler:
    """Collects audio frames from device with Opus decoding and VAD filtering.

    Flow:
    1. Device sends Opus packets → decoded to PCM
    2. VAD analyzes each PCM frame for voice activity
    3. Only buffers audio after speech is detected
    4. Signals speech_complete when silence follows speech
    """

    def __init__(self, dashscope_api_key: str = "", asr_model: str = "paraformer-realtime-v2"):
        self._buffers: dict[str, bytearray] = {}       # PCM buffer (for VAD)
        self._raw_opus: dict[str, list[bytes]] = {}     # Raw Opus packets (for reliable ASR)
        self._decoders: dict[str, opuslib.Decoder] = {}
        self._vad_states: dict[str, dict] = {}
        self._asr_sessions: dict[str, StreamingASR] = {}
        self._dashscope_api_key = dashscope_api_key
        self._asr_model = asr_model

    def start_listening(self, session: Session):
        """Start collecting audio for a session."""
        self._buffers[session.session_id] = bytearray()
        self._raw_opus[session.session_id] = []
        self._decoders[session.session_id] = opuslib.Decoder(16000, 1)
        # Start streaming ASR session
        if self._dashscope_api_key:
            asr = StreamingASR(api_key=self._dashscope_api_key, model=self._asr_model)
            asr.start()
            self._asr_sessions[session.session_id] = asr

        # Reset Silero model state for new session
        _silero_model.reset_states()
        self._vad_states[session.session_id] = {
            "pcm_pending": bytearray(),   # accumulates PCM until we have a full Silero chunk
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

        # Save raw Opus packet for later batch decoding (more reliable than per-frame)
        raw_list = self._raw_opus.get(sid)
        if raw_list is not None:
            raw_list.append(audio_data)

        # Decode Opus to PCM (for VAD only — final ASR uses batch decode)
        decoder = self._decoders.get(sid)
        if decoder:
            try:
                pcm = decoder.decode(audio_data, 960, decode_fec=False)
            except Exception:
                pcm = audio_data
        else:
            pcm = audio_data

        # Feed PCM to streaming ASR (runs in parallel with VAD)
        asr = self._asr_sessions.get(sid)
        if asr:
            asr.feed(pcm)

        # Accumulate PCM for Silero VAD processing
        state["pcm_pending"].extend(pcm)

        # Process complete Silero chunks (512 samples = 1024 bytes each)
        while len(state["pcm_pending"]) >= SILERO_CHUNK_BYTES:
            frame = bytes(state["pcm_pending"][:SILERO_CHUNK_BYTES])
            del state["pcm_pending"][:SILERO_CHUNK_BYTES]

            # Convert to float32 tensor for Silero [-1, 1]
            samples = struct.unpack(f"<{SILERO_CHUNK_SAMPLES}h", frame)
            audio_tensor = torch.FloatTensor(samples) / 32768.0

            # Run Silero VAD inference
            speech_prob = _silero_model(audio_tensor, 16000).item()
            is_speech = speech_prob > SPEECH_PROB_THRESHOLD

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
                    # Keep a rolling pre-speech buffer (~300ms)
                    state["pre_speech_buf"].extend(frame)
                    if len(state["pre_speech_buf"]) > SILERO_CHUNK_BYTES * 10:
                        del state["pre_speech_buf"][:SILERO_CHUNK_BYTES * 5]

    def is_speech_complete(self, session: Session) -> bool:
        """Check if VAD detected end of speech."""
        state = self._vad_states.get(session.session_id)
        return state is not None and state.get("speech_complete", False)

    def has_speech(self, session: Session) -> bool:
        """Check if any speech has been detected."""
        state = self._vad_states.get(session.session_id)
        return state is not None and state.get("speech_started", False)

    def stop_listening(self, session: Session) -> bytes | None:
        """Stop collecting and return PCM audio decoded from raw Opus packets.

        Uses a fresh decoder to batch-decode all saved Opus packets,
        which is more reliable than the per-frame decode used for VAD.
        """
        raw_packets = self._raw_opus.pop(session.session_id, None)
        self._buffers.pop(session.session_id, None)
        self._decoders.pop(session.session_id, None)
        self._vad_states.pop(session.session_id, None)

        if not raw_packets or len(raw_packets) < 5:
            return None

        # Batch decode all Opus packets with a fresh decoder
        fresh_decoder = opuslib.Decoder(16000, 1)
        pcm_buf = bytearray()
        for pkt in raw_packets:
            try:
                pcm = fresh_decoder.decode(pkt, 960, decode_fec=False)
                pcm_buf.extend(pcm)
            except Exception:
                pass

        if len(pcm_buf) < SILERO_CHUNK_BYTES * 5:
            return None

        logger.info("vad.collected packets=%d pcm_bytes=%d duration=%.1fs",
                     len(raw_packets), len(pcm_buf), len(pcm_buf) / 32000)

        # Debug: save WAV for inspection
        try:
            import wave as _wave, io as _io
            wav_buf = _io.BytesIO()
            with _wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
                wf.writeframes(pcm_buf)
            with open("/tmp/xiaozhi_latest.wav", "wb") as f:
                f.write(wav_buf.getvalue())
        except Exception:
            pass

        return bytes(pcm_buf)

    async def get_streaming_asr_result(self, session: Session) -> str:
        """Finalize and return the streaming ASR result.

        Called after VAD detects end-of-speech. The ASR has been processing
        audio in parallel, so this typically returns almost immediately.
        """
        asr = self._asr_sessions.pop(session.session_id, None)
        if asr:
            return await asr.finish()
        return ""

    def abort(self, session: Session):
        """Discard buffered audio."""
        self._buffers.pop(session.session_id, None)
        self._raw_opus.pop(session.session_id, None)
        self._decoders.pop(session.session_id, None)
        self._vad_states.pop(session.session_id, None)
        asr = self._asr_sessions.pop(session.session_id, None)
        if asr:
            asr.abort()

    @staticmethod
    def make_audio_response(audio_data: bytes) -> OutboundMessage:
        """Wrap audio bytes in an outbound message."""
        return OutboundMessage(type=MessageType.AUDIO, payload=audio_data)
