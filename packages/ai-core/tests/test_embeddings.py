"""Embedding service: fake backend, caching, graceful unavailability, vector helpers."""

import pytest

from ai_core.services.embeddings import (
    EmbeddingService,
    FakeEmbedder,
    build_embedding_service,
    cosine,
    parse_vector,
    vector_literal,
)


def test_fake_embedder_is_deterministic_and_semantic_ish():
    e = FakeEmbedder(dim=64)
    a, b = e.encode(["我喜欢抹茶拿铁", "我喜欢抹茶拿铁"])
    assert a == b and len(a) == 64
    same_topic = cosine(*e.encode(["下午想喝抹茶拿铁", "抹茶拿铁真好喝"]))
    unrelated = cosine(*e.encode(["下午想喝抹茶拿铁", "明天有一场重要考试"]))
    assert same_topic > unrelated


def test_vector_literal_round_trip():
    v = [0.1, -0.25, 1.0]
    lit = vector_literal(v)
    assert lit.startswith("[") and lit.endswith("]")
    assert parse_vector(lit) == pytest.approx(v)
    assert parse_vector(None) is None
    assert parse_vector("garbage") is None


@pytest.mark.asyncio
async def test_service_caches_and_reports_availability():
    svc = EmbeddingService(FakeEmbedder(16))
    assert svc.available and svc.dim == 16
    v1 = await svc.embed_one("你好")
    v2 = await svc.embed_one("你好")
    assert v1 is v2  # cached object
    got = await svc.embed(["你好", "", "再见"])
    assert got[0] is v1 and got[1] is None and got[2] is not None


@pytest.mark.asyncio
async def test_disabled_service_returns_nones():
    svc = EmbeddingService(None, enabled=False)
    assert not svc.available
    assert await svc.embed(["x", "y"]) == [None, None]


@pytest.mark.asyncio
async def test_backend_failure_disables_without_raising():
    class Boom:
        dim = 4

        def encode(self, texts):
            raise RuntimeError("no model")

    svc = EmbeddingService(Boom())
    assert await svc.embed_one("x") is None
    assert not svc.available


def test_build_from_settings_fake_and_disabled():
    class S:
        memory_embedding_enabled = True
        memory_embedding_backend = "fake"
        memory_embedding_dim = 32

    assert build_embedding_service(S()).available

    class Off:
        memory_embedding_enabled = False

    assert not build_embedding_service(Off()).available
