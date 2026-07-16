"""Audio pipeline: normalization, VAD/ASR provider seams, self-voice filtering
and barge-in.

The REAL streaming stack (Opus decode, Silero VAD, DashScope streaming ASR,
Fish TTS) already exists in packages/gateway — this module does NOT reimplement
it. It defines the provider contracts the gateway plugs into, plus deterministic
mock implementations for offline tests. See gateway/pipeline/character_bridge.py
for the live wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator, Protocol, runtime_checkable

from engine.perception.models import AuditoryObservation, SpeakerObservation
from engine.perception.sources import AudioChunk

_SUPPORTED_FORMATS = ("pcm_s16le_16k", "opus_48k", "wav")


class InvalidAudioError(ValueError):
    pass


def normalize_chunk(chunk: AudioChunk) -> AudioChunk:
    """Format gate. Opus decode itself lives in the gateway (existing code);
    fixtures arrive as PCM/WAV. Unknown formats are rejected, not guessed."""
    if chunk.format not in _SUPPORTED_FORMATS:
        raise InvalidAudioError(f"unsupported audio format {chunk.format!r}")
    if chunk.pcm is not None and len(chunk.pcm) == 0:
        raise InvalidAudioError("empty audio chunk")
    return chunk


@runtime_checkable
class VADProvider(Protocol):
    def is_speech(self, chunk: AudioChunk) -> bool: ...


@runtime_checkable
class ASRProvider(Protocol):
    name: str

    def transcribe(self, chunk: AudioChunk) -> AuditoryObservation: ...


@runtime_checkable
class SoundEventProvider(Protocol):
    """Non-speech acoustics: doorbell, glass break, alarm ..."""

    def classify(self, chunk: AudioChunk) -> AuditoryObservation | None: ...


class MockVAD:
    """Sidecar-driven VAD for fixtures ({"speech": true})."""

    def is_speech(self, chunk: AudioChunk) -> bool:
        return bool(chunk.sidecar.get("speech", bool(chunk.pcm)))


class MockASRProvider:
    """Deterministic ASR: transcript comes from the fixture sidecar."""

    name = "mock-asr"

    def transcribe(self, chunk: AudioChunk) -> AuditoryObservation:
        sidecar = chunk.sidecar or {}
        speaker = SpeakerObservation(
            speaker_id=sidecar.get("speaker", "user"),
            is_self_voice=bool(sidecar.get("self_voice", False)),
            confidence=float(sidecar.get("speaker_confidence", 0.95)),
        )
        return AuditoryObservation(
            ts=chunk.ts, kind="speech",
            transcript=sidecar.get("transcript", ""),
            speaker=speaker, audio_ref=chunk.ref,
            provider=self.name,
            confidence=float(sidecar.get("confidence", 0.95)),
            is_final=bool(sidecar.get("final", True)),
        )


class MockSoundEvents:
    def classify(self, chunk: AudioChunk) -> AuditoryObservation | None:
        label = (chunk.sidecar or {}).get("sound_label", "")
        if not label:
            return None
        return AuditoryObservation(
            ts=chunk.ts, kind="sound", sound_label=label, audio_ref=chunk.ref,
            provider="mock-sound", confidence=float(chunk.sidecar.get("confidence", 0.8)),
        )


@dataclass
class SelfVoiceFilter:
    """Echo suppression at the semantic level: while the character's own TTS is
    playing, speech attributed to the robot itself is dropped; genuinely new
    user speech passes through (that is exactly barge-in)."""

    tts_active: bool = False
    recent_tts_text: str = ""

    def on_tts_start(self, text: str) -> None:
        self.tts_active = True
        self.recent_tts_text = text

    def on_tts_end(self) -> None:
        self.tts_active = False

    def allow(self, observation: AuditoryObservation) -> bool:
        speaker = observation.speaker
        if speaker and speaker.is_self_voice:
            return False
        if (self.tts_active and observation.transcript
                and observation.transcript.strip() == self.recent_tts_text.strip()):
            return False                     # acoustic echo of our own sentence
        return True


@dataclass
class BargeInController:
    """User speech during TTS => stop speaking, pause interruptible motion,
    hand the new utterance to the Character Runtime for a fresh decision.

    Deterministic: driven by VAD + SelfVoiceFilter; no LLM in this path.
    """

    stop_tts: Callable[[], None]
    pause_motion: Callable[[str], None]           # reason -> safe pause request
    self_voice: SelfVoiceFilter = field(default_factory=SelfVoiceFilter)
    triggered_count: int = 0

    def on_speech_detected(self, observation: AuditoryObservation) -> bool:
        """Returns True when a barge-in was performed."""
        if not self.self_voice.tts_active:
            return False
        if not self.self_voice.allow(observation):
            return False                          # our own voice / echo
        self.stop_tts()
        self.self_voice.on_tts_end()
        self.pause_motion("user_barge_in")
        self.triggered_count += 1
        return True


def run_audio_pipeline(chunks: Iterator[AudioChunk], vad: VADProvider,
                       asr: ASRProvider, sounds: SoundEventProvider | None = None,
                       self_voice: SelfVoiceFilter | None = None,
                       barge_in: BargeInController | None = None,
                       ) -> Iterator[AuditoryObservation]:
    """Fixture-friendly synchronous pipeline (the gateway runs its own async
    streaming version; contracts are identical)."""
    # One echo state must govern both barge-in and final delivery.  Previously
    # the controller could reject our TTS echo while a second default filter
    # immediately let the same observation reach the planner.
    if self_voice is None:
        self_voice = barge_in.self_voice if barge_in is not None else SelfVoiceFilter()
    elif barge_in is not None and barge_in.self_voice is not self_voice:
        barge_in.self_voice = self_voice
    for chunk in chunks:
        chunk = normalize_chunk(chunk)
        if vad.is_speech(chunk):
            observation = asr.transcribe(chunk)
            if barge_in is not None:
                barge_in.on_speech_detected(observation)
            if not self_voice.allow(observation):
                continue
            if observation.transcript and observation.is_final:
                yield observation
        elif sounds is not None:
            sound = sounds.classify(chunk)
            if sound is not None:
                yield sound
