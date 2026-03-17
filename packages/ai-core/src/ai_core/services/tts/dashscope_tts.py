"""DashScope CosyVoice TTS provider."""

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


class DashScopeTTSProvider(TTSProvider):
    """DashScope CosyVoice TTS provider.

    Note: CosyVoice v2 SDK returns MP3 format (not raw PCM).
    """

    name = "dashscope"

    # The actual format returned by DashScope
    output_format = "mp3"

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
        # DashScope returns MP3 directly — browsers can play MP3 natively
        return await self.synthesize(text, voice, speed)

    def get_voices(self) -> dict[str, str]:
        return dict(PRESET_VOICES)
