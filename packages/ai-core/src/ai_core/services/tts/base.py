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
    ) -> bytes:
        """Synthesize text to PCM audio bytes (16kHz 16bit mono)."""
        ...

    @abstractmethod
    async def synthesize_to_wav(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize text and return WAV format."""
        ...

    @abstractmethod
    def get_voices(self) -> dict[str, str]:
        """Return available voice ID -> description mapping."""
        ...
