"""ASR Client — thin wrapper delegating to provider abstraction layer."""

import time

from ai_core.config import settings
from ai_core.services import provider_health as observed
from ai_core.services.asr.registry import create_asr_provider


class ASRClient:
    def __init__(self, provider: str | None = None):
        self._provider = create_asr_provider(provider=provider)

    async def recognize(self, audio_data: bytes, audio_format: str = "pcm") -> str:
        """Recognize speech from audio bytes (PCM or Opus)."""
        start = time.monotonic()
        provider = self._provider.name
        try:
            text = await self._provider.recognize(audio_data, audio_format=audio_format)
        except Exception as exc:
            observed.provider_health.record_failure(
                "asr", provider, settings.asr_model, (time.monotonic() - start) * 1000, exc
            )
            raise
        # Silence is a valid ASR result; transport/provider completion succeeded.
        observed.provider_health.record_success(
            "asr", provider, settings.asr_model, (time.monotonic() - start) * 1000
        )
        return text
