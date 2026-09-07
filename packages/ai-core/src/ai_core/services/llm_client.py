"""LLM Client — thin wrapper delegating to provider abstraction layer."""

import time
from collections.abc import AsyncIterator

from ai_core.config import settings
from ai_core.services import provider_health as observed
from ai_core.services.llm.registry import create_llm_provider


class LLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self._provider = create_llm_provider(provider=provider, model=model)
        self.provider = provider or settings.llm_provider
        self.model = getattr(self._provider, "model", None) or model or settings.llm_model

    async def chat(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        """Non-streaming chat completion."""
        start = time.monotonic()
        try:
            text = await self._provider.generate(
                system_prompt=system_prompt,
                user_input=user_input,
                history=history,
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
                max_tokens=max_tokens if max_tokens is not None else settings.llm_max_tokens,
                json_mode=json_mode,
            )
        except Exception as exc:
            observed.provider_health.record_failure(
                "llm", self.provider, self.model, (time.monotonic() - start) * 1000, exc
            )
            raise
        latency = (time.monotonic() - start) * 1000
        if text and text.strip():
            observed.provider_health.record_success("llm", self.provider, self.model, latency)
        else:
            observed.provider_health.record_failure(
                "llm", self.provider, self.model, latency, observed.EmptyProviderResponse()
            )
        return text

    async def chat_stream(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """Streaming chat completion, yields text chunks."""
        start, emitted = time.monotonic(), False
        try:
            async for chunk in self._provider.generate_stream(
                system_prompt=system_prompt,
                user_input=user_input,
                history=history,
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
                max_tokens=settings.llm_max_tokens,
                json_mode=json_mode,
            ):
                emitted = emitted or bool(chunk and chunk.strip())
                yield chunk
        except Exception as exc:
            observed.provider_health.record_failure(
                "llm", self.provider, self.model, (time.monotonic() - start) * 1000, exc
            )
            raise
        # Consumer cancellation/early generator close never reaches here: it
        # must not be counted as either a provider success or provider failure.
        latency = (time.monotonic() - start) * 1000
        if emitted:
            observed.provider_health.record_success("llm", self.provider, self.model, latency)
        else:
            observed.provider_health.record_failure(
                "llm", self.provider, self.model, latency, observed.EmptyProviderResponse()
            )
