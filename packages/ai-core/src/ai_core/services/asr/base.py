"""ASR Provider abstract base class."""

from abc import ABC, abstractmethod


class ASRProvider(ABC):
    """Abstract base for all ASR providers."""

    name: str = "base"

    @abstractmethod
    async def recognize(self, audio_data: bytes) -> str:
        """Recognize speech from audio bytes (16kHz PCM).

        Returns transcribed text.
        """
        ...
