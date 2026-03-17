"""ASR Provider registry."""

import structlog

from ai_core.config import settings
from ai_core.services.asr.base import ASRProvider

logger = structlog.get_logger()


def create_asr_provider(provider: str | None = None) -> ASRProvider:
    """Create an ASR provider by name.

    Args:
        provider: "dashscope". Defaults to settings.asr_provider.
    """
    name = provider or settings.asr_provider

    # Currently only DashScope is supported; extensible for Whisper, etc.
    from ai_core.services.asr.dashscope_asr import DashScopeASRProvider
    logger.info("asr.create_provider", provider=name)
    return DashScopeASRProvider()
