"""DashScope CosyVoice TTS — SSML mode for voice persona control.

Uses cosyvoice-v3-flash with SSML markup for pitch/rate/effect control:
  <speak pitch="1.35" rate="1.1" effect="lolita">你好呀主人~</speak>
"""

import asyncio

import structlog
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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

_RETRYABLE = (RuntimeError, TimeoutError, ConnectionError, OSError)


def _wrap_ssml(text: str, pitch: float, rate: float, effect: str) -> str:
    """Wrap text in SSML <speak> tags with pitch/rate/effect attributes.

    Only includes non-default attributes to keep the markup minimal.
    Returns plain text if all params are default (no SSML needed).
    """
    is_default = (pitch == 1.0 and rate == 1.0 and not effect)
    if is_default:
        return text

    attrs = []
    if pitch != 1.0:
        attrs.append(f'pitch="{pitch}"')
    if rate != 1.0:
        attrs.append(f'rate="{rate}"')
    if effect:
        attrs.append(f'effect="{effect}"')

    attr_str = " ".join(attrs)
    return f"<speak {attr_str}>{text}</speak>"


class DashScopeTTSProvider(TTSProvider):
    """DashScope CosyVoice TTS with SSML support.

    cosyvoice-v3-flash supports SSML markup:
    - pitch: 0.5-2.0 (音高)
    - rate: 0.5-2.0 (语速)
    - effect: lolita/robot/echo/lowpass (变声特效)
    - <break time="Xms"/> (自然停顿)

    Output format: MP3
    """

    name = "dashscope"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        pitch_rate: int = 0,
        speech_rate: int = 0,
        ssml_pitch: float = 1.0,
        ssml_rate: float = 1.0,
        ssml_effect: str = "",
    ) -> bytes:
        dashscope.api_key = settings.dashscope_api_key
        voice_id = voice or DEFAULT_VOICE

        # Wrap text in SSML if any non-default params
        ssml_text = _wrap_ssml(text, ssml_pitch, ssml_rate, ssml_effect)

        kwargs: dict = {
            "model": settings.tts_model,
            "voice": voice_id,
        }

        logger.info(
            "tts.synthesize",
            voice=voice_id,
            model=settings.tts_model,
            ssml_pitch=ssml_pitch,
            ssml_rate=ssml_rate,
            ssml_effect=ssml_effect or "none",
            text_len=len(text),
            is_ssml=ssml_text != text,
        )

        # Run synchronous DashScope call in thread pool with timeout
        def _sync_call():
            synth = SpeechSynthesizer(**kwargs)
            return synth.call(ssml_text)

        try:
            audio = await asyncio.wait_for(
                asyncio.to_thread(_sync_call),
                timeout=settings.tts_timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"TTS synthesis timed out after {settings.tts_timeout}s")

        # If SSML failed (returns None), retry with plain text
        if audio is None and ssml_text != text:
            logger.warning("tts.ssml_fallback", voice=voice_id)

            def _sync_fallback():
                synth = SpeechSynthesizer(**kwargs)
                return synth.call(text)

            audio = await asyncio.wait_for(
                asyncio.to_thread(_sync_fallback),
                timeout=settings.tts_timeout,
            )

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
        ssml_pitch: float = 1.0,
        ssml_rate: float = 1.0,
        ssml_effect: str = "",
    ) -> bytes:
        return await self.synthesize(
            text, voice, speed, pitch_rate, speech_rate,
            ssml_pitch, ssml_rate, ssml_effect,
        )

    def get_voices(self) -> dict[str, str]:
        return dict(PRESET_VOICES)
