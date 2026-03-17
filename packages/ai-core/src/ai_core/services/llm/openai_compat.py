"""Unified OpenAI-compatible LLM provider.

Covers: DashScope/Qwen, DeepSeek, Moonshot/Kimi, GLM-4, OpenAI, local Ollama.
All use the same OpenAI SDK with different base_url + api_key.
"""

from collections.abc import AsyncIterator

import httpx
import structlog
from openai import AsyncOpenAI

from ai_core.services.llm.base import LLMProvider

logger = structlog.get_logger()


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible LLM provider (covers most Chinese LLM APIs)."""

    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        # Use a custom httpx client to bypass system SOCKS proxy
        http_client = httpx.AsyncClient(proxy=None)
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, http_client=http_client)
        logger.info("llm.provider_init", provider=self.name, base_url=base_url, model=model)

    def _build_messages(
        self, system_prompt: str, user_input: str, history: list[dict] | None
    ) -> list[dict]:
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        return messages

    async def generate(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
        *,
        temperature: float = 0.8,
        top_p: float = 0.9,
        max_tokens: int = 256,
    ) -> str:
        messages = self._build_messages(system_prompt, user_input, history)
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def generate_stream(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
        *,
        temperature: float = 0.8,
        top_p: float = 0.9,
        max_tokens: int = 256,
    ) -> AsyncIterator[str]:
        messages = self._build_messages(system_prompt, user_input, history)
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
