"""LLM Provider registry — factory that creates provider by config."""

import structlog

from ai_core.config import settings
from ai_core.services.llm.base import LLMProvider
from ai_core.services.llm.openai_compat import OpenAICompatProvider

logger = structlog.get_logger()

# Well-known provider configurations
PROVIDER_CONFIGS = {
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen2.5-7b-instruct",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5:7b",
    },
}


def create_llm_provider(
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: Provider name (dashscope, deepseek, moonshot, glm, openai, ollama).
                  Falls back to settings.llm_provider.
        model: Model name. Falls back to settings.llm_model.
        base_url: Override base URL. Falls back to well-known config.
        api_key: Override API key. Falls back to settings.
    """
    provider_name = provider or settings.llm_provider

    config = PROVIDER_CONFIGS.get(provider_name, {})
    resolved_base_url = base_url or settings.llm_base_url or config.get("base_url", "")
    resolved_model = model or settings.llm_model or config.get("default_model", "")
    resolved_api_key = api_key or settings.llm_api_key or settings.dashscope_api_key

    if not resolved_base_url:
        raise ValueError(f"No base_url configured for provider '{provider_name}'")

    logger.info(
        "llm.create_provider",
        provider=provider_name,
        model=resolved_model,
    )

    return OpenAICompatProvider(
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        model=resolved_model,
    )
