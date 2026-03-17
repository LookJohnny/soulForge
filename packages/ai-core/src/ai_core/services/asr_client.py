"""ASR Client — thin wrapper delegating to provider abstraction layer."""

from ai_core.services.asr.registry import create_asr_provider


class ASRClient:
    def __init__(self, provider: str | None = None):
        self._provider = create_asr_provider(provider=provider)

    async def recognize(self, audio_data: bytes) -> str:
        """Recognize speech from audio bytes (16kHz PCM)."""
        return await self._provider.recognize(audio_data)
