"""LLM Provider abstract base class."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    name: str = "base"

    @abstractmethod
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
    ) -> str:
        """Non-streaming text generation."""
        ...

    @abstractmethod
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
    ) -> AsyncIterator[str]:
        """Streaming text generation, yields text chunks."""
        ...
        yield ""  # pragma: no cover
