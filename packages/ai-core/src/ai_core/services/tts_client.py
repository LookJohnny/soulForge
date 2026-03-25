"""TTS Client — thin wrapper with provider fallback (DashScope → Edge TTS)."""

import re
import structlog

from ai_core.services.tts.registry import create_tts_provider

logger = structlog.get_logger()

# Strip action/stage-direction text before TTS synthesis.
# LLM often outputs (微微一笑) or （轻轻戳你的脸）or *微微一笑* — these should not be read aloud.
_ACTION_PATTERNS = [
    re.compile(r"[（(][^）)]{1,30}[）)]"),   # （动作描写） or (action)
    re.compile(r"\*[^*]{1,30}\*"),            # *动作描写*
    re.compile(r"\[emotion:\s*\w+\s*\]", re.IGNORECASE),  # [emotion:xxx] tag
]


def _clean_for_tts(text: str) -> str:
    """Remove action descriptions and emotion tags before TTS."""
    for pattern in _ACTION_PATTERNS:
        text = pattern.sub("", text)
    # Collapse multiple spaces/newlines
    text = re.sub(r"\s+", " ", text).strip()
    return text


class TTSClient:
    def __init__(self, provider: str | None = None):
        self._provider = create_tts_provider(provider=provider)
        # Create fallback provider if primary is not edge
        self._fallback = None
        if self._provider.name != "edge":
            try:
                self._fallback = create_tts_provider(provider="edge")
            except Exception:
                pass  # Edge TTS not available

    async def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0,
                         pitch_rate: int = 0, speech_rate: int = 0,
                         ssml_pitch: float = 1.0, ssml_rate: float = 1.0,
                         ssml_effect: str = "") -> bytes:
        text = _clean_for_tts(text)
        try:
            return await self._provider.synthesize(
                text, voice, speed, pitch_rate, speech_rate,
                ssml_pitch, ssml_rate, ssml_effect,
            )
        except Exception as e:
            if self._fallback:
                logger.warning("tts.primary_failed_using_fallback", error=str(e))
                return await self._fallback.synthesize(
                    text, voice, speed, pitch_rate, speech_rate,
                    ssml_pitch, ssml_rate, ssml_effect,
                )
            raise

    async def synthesize_to_wav(self, text: str, voice: str | None = None, speed: float = 1.0,
                                pitch_rate: int = 0, speech_rate: int = 0,
                                ssml_pitch: float = 1.0, ssml_rate: float = 1.0,
                                ssml_effect: str = "") -> bytes:
        text = _clean_for_tts(text)
        try:
            return await self._provider.synthesize_to_wav(
                text, voice, speed, pitch_rate, speech_rate,
                ssml_pitch, ssml_rate, ssml_effect,
            )
        except Exception as e:
            if self._fallback:
                logger.warning("tts.primary_failed_using_fallback", error=str(e))
                return await self._fallback.synthesize_to_wav(
                    text, voice, speed, pitch_rate, speech_rate,
                    ssml_pitch, ssml_rate, ssml_effect,
                )
            raise

    def get_preset_voices(self) -> dict[str, str]:
        return self._provider.get_voices()
