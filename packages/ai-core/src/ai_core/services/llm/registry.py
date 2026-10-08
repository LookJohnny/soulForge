"""LLM Provider registry — factory that creates provider by config."""

import json

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
        "local": True,
    },
    # Local open model behind Nous Tone (AI-Emotion-Experiment/tone): OpenAI
    # compatible, plus tone steering ("tone"/"tone_target") and a readout probe.
    "nous_tone": {
        "base_url": "http://127.0.0.1:7880/v1",
        "default_model": "Qwen3-4B-Instruct-2507",
        "local": True,
    },
}


def tone_extra_body() -> dict:
    """Nous Tone steering fields, from NOUS_TONE_STEER / NOUS_TONE_TARGET.

    Malformed JSON is a configuration error and fails loudly at startup."""
    body = {}
    sources = (("tone", settings.nous_tone_steer), ("tone_target", settings.nous_tone_target))
    for field, raw in sources:
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and type(v) in (int, float) for k, v in value.items()
        ):
            name = "NOUS_TONE_STEER" if field == "tone" else "NOUS_TONE_TARGET"
            raise ValueError(f"{name} must be a JSON object of numbers")
        if value:
            body[field] = value
    return body


def create_llm_provider(
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: Provider name (dashscope, deepseek, moonshot, glm, openai, ollama, nous_tone).
                  Falls back to settings.llm_provider.
        model: Model name. Falls back to settings.llm_model.
        base_url: Override base URL. Falls back to well-known config.
        api_key: Override API key. Falls back to settings.
    """
    provider_name = provider or settings.llm_provider

    config = PROVIDER_CONFIGS.get(provider_name, {})
    resolved_base_url = base_url or settings.llm_base_url or config.get("base_url", "")
    resolved_model = model or settings.llm_model or config.get("default_model", "")
    if config.get("local"):
        # Never forward a hosted provider's LLM_API_KEY to a local server; the SDK
        # just needs a non-empty value. An explicit argument still wins.
        resolved_api_key = api_key or "local"
    else:
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
        extra_body=tone_extra_body() if provider_name == "nous_tone" else None,
        supports_priority=provider_name == "nous_tone",
        supports_prefill=provider_name == "nous_tone",
        max_retries=0 if config.get("local") else None,
    )
