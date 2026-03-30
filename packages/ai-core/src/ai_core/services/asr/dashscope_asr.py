"""DashScope FunASR provider."""

import asyncio
import io
import tempfile
import os
import wave

import dashscope
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ai_core.config import settings
from ai_core.services.asr.base import ASRProvider

_RETRYABLE = (RuntimeError, TimeoutError, ConnectionError, OSError)


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw PCM bytes in a WAV header, with gain normalization."""
    import struct

    # Normalize volume: find peak and amplify to ~80% of max
    if len(pcm_data) >= 2:
        samples = list(struct.unpack(f"<{len(pcm_data)//2}h", pcm_data))
        peak = max(abs(s) for s in samples) if samples else 1
        if peak < 5000 and peak > 0:
            # Audio is too quiet — normalize to ~80% of max range
            gain = min(26000 / peak, 10.0)  # cap at 10x to avoid noise amplification
            samples = [max(-32768, min(32767, int(s * gain))) for s in samples]
            pcm_data = struct.pack(f"<{len(samples)}h", *samples)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


class DashScopeASRProvider(ASRProvider):
    """DashScope FunASR wrapper with retry and timeout."""

    name = "dashscope"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def recognize(self, audio_data: bytes, audio_format: str = "pcm") -> str:
        def _sync_recognize():
            # Always wrap PCM in WAV for reliable ASR recognition
            # (raw PCM files without WAV headers may fail to be recognized)
            wav_data = _pcm_to_wav(audio_data, sample_rate=16000)

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            try:
                tmp.write(wav_data)
                tmp.close()
                recognition = dashscope.audio.asr.Recognition(
                    model=settings.asr_model,
                    format="wav",
                    sample_rate=16000,
                    callback=None,
                    api_key=settings.dashscope_api_key,
                )
                return recognition.call(tmp.name)
            finally:
                os.unlink(tmp.name)

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
