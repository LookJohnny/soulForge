"""DashScope CosyVoice TTS — SSML mode for voice persona control.

Uses cosyvoice-v2 with SSML markup for pitch/rate/effect control:
  <speak pitch="1.35" rate="1.1" effect="lolita">你好呀主人~</speak>

Measured against the previous Fish provider on the same sentence: ~1.1s here
versus ~6.9s there. Fish's cost is flat regardless of text length — two
characters also took 6.6s — so it is the round trip, not the synthesis.
"""

import asyncio

import dashscope
import structlog
from dashscope.audio.tts_v2 import SpeechSynthesizer
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ai_core.config import settings
from ai_core.services.tts.base import TTSProvider

logger = structlog.get_logger()

# Voice ids are versioned with the model: a v1 name against cosyvoice-v2/v3
# returns empty audio with engine code 418, not an error the SDK surfaces. The
# suffix here must therefore match VOICE_MODEL below — see test_dashscope_tts.
VOICE_MODEL = "cosyvoice-v2"

PRESET_VOICES = {
    "longxiaochun_v2": "甜美少女",
    "longxiaoxia_v2": "温柔姐姐",
    "longshu_v2": "知性大姐",
    "longlaotie_v2": "东北老铁",
    "longshuo_v2": "阳光男孩",
    "longjielidou_v2": "活力少女",
    "longyue_v2": "优雅女声",
    "longcheng_v2": "沉稳男声",
}

DEFAULT_VOICE = "longxiaochun_v2"

_RETRYABLE = (RuntimeError, TimeoutError, ConnectionError, OSError)

# The suffix the current model expects, e.g. "_v2" for cosyvoice-v2.
_MODEL_SUFFIX = "_v" + VOICE_MODEL.rsplit("-v", 1)[-1]
_BASE_VOICES = {v.rsplit("_v", 1)[0] for v in PRESET_VOICES}


def is_preset_voice(voice: str) -> bool:
    """True for a CosyVoice preset id in any of its version spellings.

    Routing needs this: a voice id that is not an Edge ``*Neural`` name was
    previously assumed to be Fish's, which sends every CosyVoice request to the
    wrong provider once DashScope is the configured one.
    """
    if not voice:
        return False
    base = voice.rsplit("_v", 1)[0] if "_v" in voice else voice
    return base in _BASE_VOICES


def normalize_voice(voice: str) -> str:
    """Retag a preset voice id to the suffix this model expects.

    The codebase carries three conventions for the same eight voices — bare
    names in the database and the Prisma seed, ``_v3`` in voice_matcher, ``_v2``
    here. A mismatched pair does not fail loudly: DashScope returns empty audio
    with engine code 418, which reaches the caller as "synthesis failed".

    Normalizing on the way out means existing rows keep working through a model
    bump instead of every call site having to be found and edited. Anything that
    is not a known preset — a cloned voice id, say — is passed through untouched.
    """
    if not voice:
        return voice
    base = voice.rsplit("_v", 1)[0] if "_v" in voice else voice
    if base not in _BASE_VOICES:
        return voice
    return base + _MODEL_SUFFIX


def _wrap_ssml(text: str, pitch: float, rate: float, effect: str) -> str:
    """Wrap text in SSML <speak> tags with pitch/rate/effect attributes.

    Only includes non-default attributes to keep the markup minimal.
    Returns plain text if all params are default (no SSML needed).
    """
    is_default = pitch == 1.0 and rate == 1.0 and not effect
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

    cosyvoice-v2 supports SSML markup:
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
        voice_id = normalize_voice(voice or DEFAULT_VOICE)

        # Wrap text in SSML if any non-default params
        ssml_text = _wrap_ssml(text, ssml_pitch, ssml_rate, ssml_effect)

        kwargs: dict = {
            "model": VOICE_MODEL,
            "voice": voice_id,
        }

        logger.info(
            "tts.synthesize",
            voice=voice_id,
            model=VOICE_MODEL,
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
        except TimeoutError as e:
            raise TimeoutError(f"TTS synthesis timed out after {settings.tts_timeout}s") from e

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
            text,
            voice,
            speed,
            pitch_rate,
            speech_rate,
            ssml_pitch,
            ssml_rate,
            ssml_effect,
        )

    def get_voices(self) -> dict[str, str]:
        return dict(PRESET_VOICES)
