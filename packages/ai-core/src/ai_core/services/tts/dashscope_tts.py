"""DashScope CosyVoice TTS provider with pitch/speed persona control."""

import structlog
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer

from ai_core.config import settings
from ai_core.services.tts.base import TTSProvider

logger = structlog.get_logger()

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
    """DashScope CosyVoice TTS with pitch_rate and speech_rate support.

    CosyVoice v2 supports:
    - pitch_rate: -500 to 500 (higher = more cute/childlike)
    - speech_rate: -500 to 500 (higher = faster)
    - volume: 0 to 100

    Output format: MP3
    """

    name = "dashscope"

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        pitch_rate: int = 0,
        speech_rate: int = 0,
    ) -> bytes:
        dashscope.api_key = settings.dashscope_api_key

        voice_id = voice or DEFAULT_VOICE

        # Build SpeechSynthesizer with persona parameters
        kwargs = {
            "model": settings.tts_model,
            "voice": voice_id,
        }

        # CosyVoice v2 supports pitch_rate and speech_rate
        if pitch_rate != 0:
            kwargs["pitch_rate"] = pitch_rate
        if speech_rate != 0:
            kwargs["speech_rate"] = speech_rate

        logger.info(
            "tts.synthesize",
            voice=voice_id,
            pitch_rate=pitch_rate,
            speech_rate=speech_rate,
            text_len=len(text),
        )

        synth = SpeechSynthesizer(**kwargs)
        audio = synth.call(text)

        if isinstance(audio, bytes) and len(audio) > 0:
            return audio
        raise RuntimeError(f"TTS synthesis failed for voice={voice_id}")

    async def synthesize_to_wav(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        pitch_rate: int = 0,
        speech_rate: int = 0,
    ) -> bytes:
        # DashScope returns MP3 — browsers play it natively
        return await self.synthesize(text, voice, speed, pitch_rate, speech_rate)

    def get_voices(self) -> dict[str, str]:
        return dict(PRESET_VOICES)
