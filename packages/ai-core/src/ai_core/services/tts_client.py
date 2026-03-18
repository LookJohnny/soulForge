"""TTS Client — thin wrapper delegating to provider abstraction layer."""

from ai_core.services.tts.registry import create_tts_provider


class TTSClient:
    def __init__(self, provider: str | None = None):
        self._provider = create_tts_provider(provider=provider)

    async def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0,
                         pitch_rate: int = 0, speech_rate: int = 0, instruction: str = "") -> bytes:
        return await self._provider.synthesize(text, voice, speed, pitch_rate, speech_rate, instruction)

    async def synthesize_to_wav(self, text: str, voice: str | None = None, speed: float = 1.0,
                                pitch_rate: int = 0, speech_rate: int = 0, instruction: str = "") -> bytes:
        return await self._provider.synthesize_to_wav(text, voice, speed, pitch_rate, speech_rate, instruction)

    def get_preset_voices(self) -> dict[str, str]:
        return self._provider.get_voices()
