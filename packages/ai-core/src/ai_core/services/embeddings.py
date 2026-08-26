"""Local sentence embeddings for companion memory (pgvector).

Default backend is ``sentence-transformers`` with ``BAAI/bge-small-zh-v1.5``
(512-dim, ~95 MB, strong on Chinese, fine on English). The model loads lazily
on first use in a worker thread so ai-core startup stays fast; if the package
or the model is unavailable the service reports ``available == False`` and
memory retrieval silently falls back to lexical relevance.

``FakeEmbedder`` is a deterministic, dependency-free backend for tests and for
CI boxes that must not download models: cosine similarity between texts that
share characters is high, unrelated texts low — enough to exercise ranking.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import threading
from collections import OrderedDict
from collections.abc import Sequence
from typing import Protocol

import structlog

logger = structlog.get_logger()

_CACHE_MAX = 2048


class Embedder(Protocol):
    dim: int

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


def normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def vector_literal(vec: Sequence[float]) -> str:
    """pgvector text form: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def parse_vector(raw) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    try:
        return [float(x) for x in s.split(",") if x.strip()]
    except ValueError:
        return None


class FakeEmbedder:
    """Character-hash bag-of-features embedding — deterministic, no deps."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            chars = list(text or "")
            grams = chars + ["".join(p) for p in zip(chars, chars[1:], strict=False)]
            for g in grams:
                h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)  # noqa: S324
                vec[h % self.dim] += 1.0 if len(g) == 1 else 1.5
            out.append(normalize(vec) if any(vec) else vec)
        return out


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, dim: int, hf_home: str | None = None):
        self.model_name = model_name
        self.dim = dim
        self._model = None
        self._lock = threading.Lock()
        self._hf_home = hf_home

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    import os

                    if self._hf_home:
                        os.environ.setdefault("HF_HOME", self._hf_home)
                    from sentence_transformers import SentenceTransformer

                    model = SentenceTransformer(self.model_name, device="cpu")
                    got = model.get_sentence_embedding_dimension()
                    if got and got != self.dim:
                        logger.warning("embeddings.dim_mismatch", configured=self.dim, model=got)
                        self.dim = got
                    self._model = model
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        arr = model.encode(list(texts), normalize_embeddings=True, batch_size=32)
        return [[float(x) for x in row] for row in arr]


class EmbeddingService:
    """Async façade with an LRU cache; ``available`` is False when disabled or
    the backend failed to import/load."""

    def __init__(self, backend: Embedder | None, *, enabled: bool = True):
        self._backend = backend
        self.enabled = enabled and backend is not None
        self._failed = False
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    @property
    def available(self) -> bool:
        return self.enabled and not self._failed

    @property
    def dim(self) -> int:
        return self._backend.dim if self._backend else 0

    @property
    def model_name(self) -> str:
        return getattr(
            self._backend, "model_name", type(self._backend).__name__ if self._backend else ""
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float] | None]:
        """Embed many texts (cached). Returns None entries when unavailable."""
        if not self.available:
            return [None] * len(texts)
        todo = [t for t in texts if t and t not in self._cache]
        if todo:
            try:
                vecs = await asyncio.to_thread(self._backend.encode, list(dict.fromkeys(todo)))
            except Exception:
                logger.exception("embeddings.backend_failed — semantic memory disabled")
                self._failed = True
                return [None] * len(texts)
            for t, v in zip(list(dict.fromkeys(todo)), vecs, strict=False):
                self._cache[t] = v
                self._cache.move_to_end(t)
            while len(self._cache) > _CACHE_MAX:
                self._cache.popitem(last=False)
        return [self._cache.get(t) if t else None for t in texts]

    async def embed_one(self, text: str) -> list[float] | None:
        return (await self.embed([text]))[0]


def build_embedding_service(settings) -> EmbeddingService:
    """Construct from ai-core settings; never raises."""
    if not getattr(settings, "memory_embedding_enabled", True):
        return EmbeddingService(None, enabled=False)
    backend_name = getattr(settings, "memory_embedding_backend", "sentence_transformers")
    dim = int(getattr(settings, "memory_embedding_dim", 512))
    if backend_name == "fake":
        return EmbeddingService(FakeEmbedder(dim))
    try:
        import sentence_transformers  # noqa: F401
    except Exception:
        logger.warning("embeddings.unavailable — install ai-core[semantic] to enable vector memory")
        return EmbeddingService(None, enabled=False)
    return EmbeddingService(
        SentenceTransformerEmbedder(
            getattr(settings, "memory_embedding_model", "BAAI/bge-small-zh-v1.5"),
            dim,
            hf_home=getattr(settings, "hf_home", "") or None,
        )
    )
