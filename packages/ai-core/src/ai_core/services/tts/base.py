"""TTS Provider abstract base class."""

from abc import ABC, abstractmethod


class TTSProvider(ABC):
    """Abstract base for all TTS providers."""

    name: str = "base"

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        pitch_rate: int = 0,
        speech_rate: int = 0,
    ) -> bytes:
        """Synthesize text to audio bytes."""
        ...

    @abstractmethod
    async def synthesize_to_wav(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        pitch_rate: int = 0,
        speech_rate: int = 0,
    ) -> bytes:
        """Synthesize text and return playable audio format."""
        ...

    @abstractmethod
    def get_voices(self) -> dict[str, str]:
        """Return available voice ID -> description mapping."""
        ...
