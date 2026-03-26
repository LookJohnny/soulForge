"""TTS Provider registry."""

import structlog

from ai_core.config import settings
from ai_core.services.tts.base import TTSProvider

logger = structlog.get_logger()


def create_tts_provider(provider: str | None = None) -> TTSProvider:
    """Create a TTS provider by name.

    Args:
        provider: "dashscope" or "edge". Defaults to settings.tts_provider.
    """
    name = provider or settings.tts_provider

    if name == "fish":
        from ai_core.services.tts.fish_audio_tts import FishAudioTTSProvider
        logger.info("tts.create_provider", provider="fish")
        return FishAudioTTSProvider()
    elif name == "edge":
        from ai_core.services.tts.edge_tts_provider import EdgeTTSProvider
        logger.info("tts.create_provider", provider="edge")
        return EdgeTTSProvider()
    else:
        from ai_core.services.tts.dashscope_tts import DashScopeTTSProvider
        logger.info("tts.create_provider", provider="dashscope")
        return DashScopeTTSProvider()
