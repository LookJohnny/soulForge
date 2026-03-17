"""LLM Client — thin wrapper delegating to provider abstraction layer."""

from collections.abc import AsyncIterator

from ai_core.config import settings
from ai_core.services.llm.registry import create_llm_provider


class LLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self._provider = create_llm_provider(provider=provider, model=model)

    async def chat(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
    ) -> str:
        """Non-streaming chat completion."""
        return await self._provider.generate(
            system_prompt=system_prompt,
            user_input=user_input,
            history=history,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
            max_tokens=settings.llm_max_tokens,
        )

    async def chat_stream(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Streaming chat completion, yields text chunks."""
        async for chunk in self._provider.generate_stream(
            system_prompt=system_prompt,
            user_input=user_input,
            history=history,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
            max_tokens=settings.llm_max_tokens,
        ):
            yield chunk
