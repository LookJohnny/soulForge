"""Health is based on actual calls, with no probes or provider-error secrets."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_core.api.health import provider_health as health_endpoint
from ai_core.services import asr_client, llm_client, provider_health, tts_client


@pytest.fixture
def registry(monkeypatch):
    registry = provider_health.ProviderHealthRegistry()
    monkeypatch.setattr(provider_health, "provider_health", registry)
    return registry


def state(registry, kind, provider):
    matches = [
        r
        for r in registry.snapshot()["providers"]
        if r["kind"] == kind and r["provider"] == provider
    ]
    return next((r for r in matches if r["success_count"] or r["failure_count"]), matches[0])


def fake_llm(monkeypatch, provider):
    monkeypatch.setattr(llm_client, "create_llm_provider", lambda **kwargs: provider)
    return llm_client.LLMClient(provider="deepseek", model="deepseek-chat")


@pytest.mark.asyncio
async def test_configured_provider_is_unknown_and_health_makes_no_requests(monkeypatch, registry):
    factory = AsyncMock(side_effect=AssertionError("health must not construct/call providers"))
    monkeypatch.setattr(llm_client, "create_llm_provider", factory)
    result = await health_endpoint()
    assert result["status"] == "unknown" and result["observation_only"] is True
    assert all(row["status"] == "unknown" for row in result["providers"])
    assert all(row["success_count"] == row["failure_count"] == 0 for row in result["providers"])
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_then_recovery_preserves_counts_without_error_secrets(
    monkeypatch, registry
):
    error = RuntimeError("sk-private-key https://provider.test?token=private user-transcript")
    error.status_code = 429
    provider = SimpleNamespace(generate=AsyncMock(side_effect=[error, "recovered"]))
    client = fake_llm(monkeypatch, provider)
    with pytest.raises(RuntimeError):
        await client.chat("private system prompt", "private user input")
    failed = state(registry, "llm", "deepseek")
    assert failed["status"] == "degraded"
    assert failed["last_error"] == {"type": "RuntimeError", "status_code": 429}
    serialized = json.dumps(await health_endpoint())
    assert "sk-private" not in serialized and "provider.test" not in serialized
    assert "user-transcript" not in serialized and "private user input" not in serialized
    assert await client.chat("system", "user") == "recovered"
    recovered = state(registry, "llm", "deepseek")
    assert recovered["status"] == "ok" and recovered["last_error"] is None
    assert recovered["success_count"] == recovered["failure_count"] == 1
    assert recovered["consecutive_failures"] == 0
    assert recovered["last_success_at"] and recovered["last_failure_at"]
    assert recovered["last_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_llm_stream_partial_failure_is_not_success_and_recovers(monkeypatch, registry):
    async def broken(**kwargs):
        yield "partial"
        raise TimeoutError("secret provider URL")

    async def complete(**kwargs):
        yield "hello"
        yield "world"

    provider = SimpleNamespace(generate_stream=broken)
    client = fake_llm(monkeypatch, provider)
    with pytest.raises(TimeoutError):
        async for _ in client.chat_stream("s", "u"):
            pass
    failed = state(registry, "llm", "deepseek")
    assert failed["failure_count"] == 1 and failed["success_count"] == 0
    provider.generate_stream = complete
    assert [chunk async for chunk in client.chat_stream("s", "u")] == ["hello", "world"]
    assert state(registry, "llm", "deepseek")["status"] == "ok"


@pytest.mark.asyncio
async def test_early_stream_close_does_not_falsify_provider_health(monkeypatch, registry):
    async def response(**kwargs):
        yield "first"
        yield "second"

    client = fake_llm(monkeypatch, SimpleNamespace(generate_stream=response))
    stream = client.chat_stream("system", "user")
    assert await anext(stream) == "first"
    await stream.aclose()
    assert all(
        r["success_count"] == r["failure_count"] == 0 for r in registry.snapshot()["providers"]
    )


@pytest.mark.asyncio
async def test_empty_llm_text_is_degraded(monkeypatch, registry):
    client = fake_llm(monkeypatch, SimpleNamespace(generate=AsyncMock(return_value="")))
    assert await client.chat("s", "u") == ""
    assert state(registry, "llm", "deepseek")["last_error"]["type"] == "EmptyProviderResponse"


@pytest.mark.asyncio
async def test_asr_records_silence_as_success_then_failure(monkeypatch, registry):
    provider = SimpleNamespace(
        name="dashscope", recognize=AsyncMock(side_effect=["", TimeoutError()])
    )
    monkeypatch.setattr(asr_client, "create_asr_provider", lambda **kwargs: provider)
    client = asr_client.ASRClient()
    assert await client.recognize(b"private audio") == ""
    assert state(registry, "asr", "dashscope")["status"] == "ok"
    with pytest.raises(TimeoutError):
        await client.recognize(b"private audio")
    assert state(registry, "asr", "dashscope")["status"] == "degraded"


def fake_tts(monkeypatch, fish, edge):
    monkeypatch.setattr(
        tts_client,
        "create_tts_provider",
        lambda provider=None: fish if provider == "fish" else edge,
    )
    return tts_client.TTSClient(provider="fish")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["synthesize", "synthesize_to_wav"])
async def test_tts_fallback_does_not_hide_primary_failure(monkeypatch, registry, method, capsys):
    fish = SimpleNamespace(name="fish", model="s1")
    edge = SimpleNamespace(name="edge")
    setattr(fish, method, AsyncMock(side_effect=RuntimeError("sk-secret URL/user-content")))
    setattr(edge, method, AsyncMock(return_value=b"wav"))
    client = fake_tts(monkeypatch, fish, edge)
    assert await getattr(client, method)("hello") == b"wav"
    assert state(registry, "tts", "fish")["status"] == "degraded"
    assert state(registry, "tts", "edge")["status"] == "ok"
    assert "sk-secret" not in json.dumps(registry.snapshot()) + capsys.readouterr().out


@pytest.mark.asyncio
async def test_tts_stream_partial_error_observed_without_duplicate_fallback(monkeypatch, registry):
    async def broken(**kwargs):
        yield b"first"
        raise RuntimeError("private URL")

    fish = SimpleNamespace(name="fish", model="s1", synthesize_stream=broken)
    edge = SimpleNamespace(name="edge", synthesize=AsyncMock(return_value=b"fallback"))
    client = fake_tts(monkeypatch, fish, edge)
    assert [chunk async for chunk in client.synthesize_stream("hello")] == [b"first"]
    assert state(registry, "tts", "fish")["status"] == "degraded"
    edge.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_tts_stream_success_counted_once(monkeypatch, registry):
    async def complete(**kwargs):
        yield b"one"
        yield b"two"

    fish = SimpleNamespace(name="fish", model="s1", synthesize_stream=complete)
    edge = SimpleNamespace(name="edge")
    client = fake_tts(monkeypatch, fish, edge)
    assert [chunk async for chunk in client.synthesize_stream("hello")] == [b"one", b"two"]
    assert state(registry, "tts", "fish")["success_count"] == 1


def test_snapshot_is_detached_and_does_not_publish_url_as_provider_label(registry):
    registry.record_failure("llm", "https://host/token-secret", "model", 3, RuntimeError("secret"))
    first = registry.snapshot()
    assert "token-secret" not in json.dumps(first)
    first["providers"][0]["status"] = "mutated"
    assert "mutated" not in json.dumps(registry.snapshot())
