"""Unified OpenAI-compatible LLM provider.

Covers: DashScope/Qwen, DeepSeek, Moonshot/Kimi, GLM-4, OpenAI, local Ollama,
local Nous Tone.
All use the same OpenAI SDK with different base_url + api_key.
"""

from collections.abc import AsyncIterator

import httpx
import structlog
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ai_core.config import settings
from ai_core.services.llm.base import LLMProvider

logger = structlog.get_logger()

# Retryable exceptions (network/transient errors)
_RETRYABLE = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    TimeoutError,
    ConnectionError,
)


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible LLM provider (covers most Chinese LLM APIs)."""

    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        extra_body: dict | None = None,
        supports_priority: bool = False,
        supports_prefill: bool = False,
        max_retries: int | None = None,
    ):
        self.model = model
        # Provider-specific request fields (e.g. Nous Tone "tone"/"tone_target").
        self.extra_body = dict(extra_body or {})
        # Only a server that queues by "priority" (Nous Tone) gets the field;
        # hosted APIs reject unknown request arguments.
        self.supports_priority = supports_priority
        self.supports_prefill = supports_prefill
        # Use a custom httpx client to bypass system SOCKS proxy, with timeout
        http_client = httpx.AsyncClient(
            proxy=None,
            timeout=httpx.Timeout(settings.llm_timeout, connect=10.0),
        )
        # max_retries=0 for a local model: the SDK's silent retries re-ran a slow
        # generation up to 3x (~90 s) while the Runtime had long given up.
        extra = {} if max_retries is None else {"max_retries": max_retries}
        self.client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, http_client=http_client, **extra
        )
        logger.info("llm.provider_init", provider=self.name, base_url=base_url, model=model)

    def _build_messages(
        self, system_prompt: str, user_input: str, history: list[dict] | None
    ) -> list[dict]:
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        return messages

    def _body(self, priority: int) -> dict:
        body = dict(self.extra_body)
        if self.supports_priority and priority:
            body["priority"] = int(priority)
        return body

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def generate(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
        *,
        temperature: float = 0.8,
        top_p: float = 0.9,
        max_tokens: int = 256,
        json_mode: bool = False,
        priority: int = 0,
        prefill: str = "",
        preemptible: bool = False,
    ) -> str:
        messages = self._build_messages(system_prompt, user_input, history)
        kwargs: dict = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        body = self._body(priority)
        if prefill and self.supports_prefill:
            body["prefill"] = prefill
        if preemptible and self.supports_priority:
            body["preemptible"] = True  # background work: a waiting user takes the model
        if body:
            kwargs["extra_body"] = body
        resp = await self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    # NOTE: @retry on an async *generator* is inert — calling a generator
    # function returns the generator object instantly; network faults surface
    # during iteration, outside tenacity's scope. Removed rather than
    # pretending to retry. (audit F12)
    async def generate_stream(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict] | None = None,
        *,
        temperature: float = 0.8,
        top_p: float = 0.9,
        max_tokens: int = 256,
        json_mode: bool = False,
        priority: int = 0,
        prefill: str = "",
    ) -> AsyncIterator[str]:
        messages = self._build_messages(system_prompt, user_input, history)
        kwargs: dict = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=True,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        body = self._body(priority)
        if prefill and self.supports_prefill:
            body["prefill"] = prefill
        if body:
            kwargs["extra_body"] = body
        stream = await self.client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
