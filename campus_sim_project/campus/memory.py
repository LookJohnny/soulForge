from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class Memory:
    """A single memory item stored by an agent."""

    time: str
    description: str
    importance: int
    tags: list[str]
    sequence: int


class MemoryStream:
    """Append-only memory stream with simple keyword retrieval."""

    def __init__(self) -> None:
        self.items: list[Memory] = []

    def add(self, time: str, description: str, importance: int, tags: Iterable[str]) -> Memory:
        if not 1 <= importance <= 10:
            raise ValueError("importance must be between 1 and 10")

        memory = Memory(
            time=time,
            description=description,
            importance=importance,
            tags=list(tags),
            sequence=len(self.items),
        )
        self.items.append(memory)
        return memory

    def retrieve(self, query: str, top_k: int = 3) -> list[Memory]:
        """Return memories ranked by relevance, importance, and recency."""
        query_terms = _tokenize(query)
        if not query_terms:
            return list(reversed(self.items[-top_k:]))

        scored = [(self._score(memory, query_terms), memory) for memory in self.items]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [memory for score, memory in scored[:top_k] if score > 0]

    def _score(self, memory: Memory, query_terms: set[str]) -> float:
        memory_terms = _tokenize(memory.description)
        memory_terms.update(tag.lower() for tag in memory.tags)

        overlap = len(query_terms & memory_terms)
        relevance_score = overlap * 3.0
        importance_score = memory.importance / 2.0
        recency_score = memory.sequence / max(len(self.items), 1)

        return relevance_score + importance_score + recency_score


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
