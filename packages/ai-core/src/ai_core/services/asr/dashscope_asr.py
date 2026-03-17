"""DashScope FunASR provider."""

import dashscope

from ai_core.config import settings
from ai_core.services.asr.base import ASRProvider


class DashScopeASRProvider(ASRProvider):
    """DashScope FunASR wrapper."""

    name = "dashscope"

    async def recognize(self, audio_data: bytes) -> str:
        recognition = dashscope.audio.asr.Recognition(
            model=settings.asr_model,
            format="pcm",
            sample_rate=16000,
            api_key=settings.dashscope_api_key,
        )

        result = recognition.call(audio_data)

        if result.status_code != 200:
            raise RuntimeError(f"ASR failed: {result.message}")

        sentences = result.get_sentence()
        if sentences:
            return "".join(s["text"] for s in sentences)
        return ""
