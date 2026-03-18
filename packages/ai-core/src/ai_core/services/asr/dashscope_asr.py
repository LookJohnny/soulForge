"""DashScope FunASR provider."""

import asyncio

import dashscope
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ai_core.config import settings
from ai_core.services.asr.base import ASRProvider

_RETRYABLE = (RuntimeError, TimeoutError, ConnectionError, OSError)


class DashScopeASRProvider(ASRProvider):
    """DashScope FunASR wrapper with retry and timeout."""

    name = "dashscope"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def recognize(self, audio_data: bytes) -> str:
        def _sync_recognize():
            recognition = dashscope.audio.asr.Recognition(
                model=settings.asr_model,
                format="pcm",
                sample_rate=16000,
                api_key=settings.dashscope_api_key,
            )
            return recognition.call(audio_data)

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_sync_recognize),
                timeout=settings.asr_timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"ASR recognition timed out after {settings.asr_timeout}s")

        if result.status_code != 200:
            raise RuntimeError(f"ASR failed: {result.message}")

        sentences = result.get_sentence()
        if sentences:
            return "".join(s["text"] for s in sentences)
        return ""
