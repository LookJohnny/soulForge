"""DashScope CosyVoice TTS provider."""

import io
import struct

import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer

from ai_core.config import settings
from ai_core.services.tts.base import TTSProvider

PRESET_VOICES = {
    "longxiaochun": "甜美少女",
    "longxiaoxia": "温柔姐姐",
    "longshu": "知性大姐",
    "longlaotie": "东北老铁",
    "longshuo": "阳光男孩",
    "longjielidou": "活力少女",
    "longyue": "优雅女声",
    "longcheng": "沉稳男声",
}

DEFAULT_VOICE = "longxiaochun"


def pcm_to_wav(
    pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16
) -> bytes:
    """Convert raw PCM bytes to WAV format."""
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8

    buf = io.BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", bits))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm_data)
    return buf.getvalue()


class DashScopeTTSProvider(TTSProvider):
    """DashScope CosyVoice TTS provider."""

    name = "dashscope"

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        dashscope.api_key = settings.dashscope_api_key
        synth = SpeechSynthesizer(
            model=settings.tts_model,
            voice=voice or DEFAULT_VOICE,
        )
        audio = synth.call(text)
        if isinstance(audio, bytes) and len(audio) > 0:
            return audio
        raise RuntimeError(f"TTS synthesis failed for voice={voice}")

    async def synthesize_to_wav(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        pcm_data = await self.synthesize(text, voice, speed)
        return pcm_to_wav(pcm_data)

    def get_voices(self) -> dict[str, str]:
        return dict(PRESET_VOICES)
