"""TTS Client — thin wrapper with provider fallback (DashScope → Edge TTS)."""

import structlog

from ai_core.services.tts.registry import create_tts_provider

logger = structlog.get_logger()


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
