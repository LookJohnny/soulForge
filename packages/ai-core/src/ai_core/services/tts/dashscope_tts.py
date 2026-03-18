"""DashScope CosyVoice TTS — instruct mode for voice persona control.

Uses cosyvoice-v3-flash with natural language voice instructions:
  "用甜美软萌的奶音说话，语气轻柔活泼"
"""

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
    """DashScope CosyVoice TTS with instruct mode.

    cosyvoice-v3-flash supports the `instruction` parameter:
    - Natural language voice acting direction (max 100 chars, CN=2)
    - e.g., "用甜美软萌的奶音说话，语气活泼可爱"
    - Falls back gracefully if instruct not supported for a voice

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
        instruction: str = "",
    ) -> bytes:
        dashscope.api_key = settings.dashscope_api_key
        voice_id = voice or DEFAULT_VOICE

        kwargs: dict = {
            "model": settings.tts_model,
            "voice": voice_id,
        }

        # Instruct mode — natural language voice direction
        if instruction:
            kwargs["instruction"] = instruction

        logger.info(
            "tts.synthesize",
            voice=voice_id,
            model=settings.tts_model,
            instruction=instruction[:30] + "..." if len(instruction) > 30 else instruction,
            text_len=len(text),
        )

        synth = SpeechSynthesizer(**kwargs)
        audio = synth.call(text)

        # If instruct failed (returns None), retry without instruction
        if audio is None and instruction:
            logger.warning("tts.instruct_not_available", voice=voice_id)
            kwargs.pop("instruction", None)
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
        instruction: str = "",
    ) -> bytes:
        return await self.synthesize(text, voice, speed, pitch_rate, speech_rate, instruction)

    def get_voices(self) -> dict[str, str]:
        return dict(PRESET_VOICES)
