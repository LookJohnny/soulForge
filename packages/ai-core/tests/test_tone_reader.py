"""Nous Tone per-sentence readouts: split parity with the gateway, wire shape, graceful failure."""

import json
import re
from types import SimpleNamespace

import httpx
import pytest

from ai_core.config import settings
from ai_core.services import tone_reader as tr
from ai_core.services.llm import registry
from tests.test_cognition import decision, run, stack  # noqa: F401  (fixture reuse)

# The gateway's per-sentence TTS split (orchestrator.py, Character Runtime path).
GATEWAY_SPLIT = r"[^。！？!?]+[。！？!?]*"


def fake_server(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        segs = [
            {
                "start": s,
                "end": e,
                "tokens": e - s,
                "readout": {"joy": 0.7 if "开心" in body["text"][s:e] else 0.1, "neutral": 0.2},
                "expression": {
                    "happy": 0.9 if "开心" in body["text"][s:e] else 0.0,
                    "neutral": 0.1,
                },
            }
            for s, e in body["segments"]
        ]
        return httpx.Response(
            200,
            json={
                "readout": {"joy": 0.4},
                "expression": {"happy": 0.3},
                "tokens": 9,
                "segments": segs,
            },
        )

    return handler


@pytest.mark.parametrize(
    "text",
    ["你好！今天真开心。我们走吧", "Hi! How are you? fine", "没有标点", "……嗯。  ！好", "a?b!c。"],
)
def test_sentence_spans_match_gateway_split(text):
    ours = [text[s:e] for s, e in tr.sentence_spans(text)]
    gateway = [s for s in re.findall(GATEWAY_SPLIT, text) if s.strip()]
    assert ours == gateway


@pytest.mark.asyncio
async def test_read_line_returns_one_reading_per_sentence(monkeypatch):
    monkeypatch.setattr(settings, "nous_tone_read_enabled", True)
    seen = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake_server(seen)))
    reader = tr.ToneReader(base_url="http://tone.local/", client=client)
    out = await reader.read_line("你好。今天真开心！", user_text="周末去哪")
    assert seen[0][0] == "/v1/tone/read"
    assert seen[0][1] == {
        "text": "你好。今天真开心！",
        "segments": [[0, 3], [3, 9]],
        "user": "周末去哪",
    }
    assert [s["text"] for s in out["sentences"]] == ["你好。", "今天真开心！"]
    assert out["sentences"][1]["expression"]["happy"] == 0.9
    assert out["expression"] == {"happy": 0.3}


@pytest.mark.asyncio
async def test_read_failures_degrade_to_none(monkeypatch):
    monkeypatch.setattr(settings, "nous_tone_read_enabled", True)

    def down(request):
        raise httpx.ConnectError("refused")

    reader = tr.ToneReader(
        base_url="http://tone.local", client=httpx.AsyncClient(transport=httpx.MockTransport(down))
    )
    assert await reader.read_line("你好。") is None

    def short(request):
        return httpx.Response(200, json={"readout": {}, "expression": {}, "segments": []})

    reader = tr.ToneReader(
        base_url="http://tone.local", client=httpx.AsyncClient(transport=httpx.MockTransport(short))
    )
    assert await reader.read_line("你好。再见。") is None  # segment count mismatch is not trusted

    def bad(request):
        return httpx.Response(400, json={"detail": "no probe"})

    reader = tr.ToneReader(
        base_url="http://tone.local", client=httpx.AsyncClient(transport=httpx.MockTransport(bad))
    )
    assert await reader.read_line("你好。") is None


@pytest.mark.asyncio
async def test_disabled_without_server_or_by_flag(monkeypatch):
    monkeypatch.setattr(settings, "nous_tone_url", "")
    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert not tr.ToneReader().enabled
    monkeypatch.setattr(settings, "llm_provider", "nous_tone")
    monkeypatch.setattr(settings, "llm_base_url", "http://127.0.0.1:7999/v1/")
    assert tr.ToneReader().base_url == "http://127.0.0.1:7999"
    monkeypatch.setattr(settings, "nous_tone_read_enabled", False)
    reader = tr.ToneReader()
    assert not reader.enabled and await reader.read_line("你好。") is None


def test_registry_local_provider_and_tone_fields(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "llm_api_key", "sk-hosted-provider-key")
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    monkeypatch.setattr(settings, "nous_tone_steer", '{"warmth": 0.8}')
    monkeypatch.setattr(settings, "nous_tone_target", "")
    p = registry.create_llm_provider("nous_tone")
    assert str(p.client.base_url).startswith("http://127.0.0.1:7880/v1")
    assert p.model == "Qwen3-4B-Instruct-2507" and p.client.api_key == "local"
    assert p.extra_body == {"tone": {"warmth": 0.8}}
    assert p.client.max_retries == 0  # never silently re-run a slow local generation
    assert registry.create_llm_provider("openai", api_key="k").client.max_retries > 0
    assert registry.create_llm_provider("openai", api_key="k").extra_body == {}
    monkeypatch.setattr(settings, "nous_tone_target", '["joy"]')
    with pytest.raises(ValueError):
        registry.create_llm_provider("nous_tone")


@pytest.mark.asyncio
async def test_extra_body_reaches_the_request(monkeypatch):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    from ai_core.services.llm.openai_compat import OpenAICompatProvider

    p = OpenAICompatProvider(
        "http://tone.local/v1",
        "local",
        "m",
        extra_body={"tone_target": {"joy": 0.6}},
        supports_priority=True,
        supports_prefill=True,
    )
    p.client = p.client.with_options(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    assert await p.generate("sys", "hi", json_mode=True, priority=1, prefill='{"a": ') == "{}"
    assert sent[0]["tone_target"] == {"joy": 0.6} and sent[0]["response_format"] == {
        "type": "json_object"
    }
    assert sent[0]["priority"] == 1 and sent[0]["prefill"] == '{"a": '
    # a hosted API never sees the field (it rejects unknown arguments)
    hosted = OpenAICompatProvider("http://api.example/v1", "k", "m")
    hosted.client = hosted.client.with_options(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await hosted.generate("sys", "hi", priority=1, prefill='{"a": ')
    assert not {"priority", "prefill", "tone_target"} & set(sent[1])
    assert p.extra_body == {
        "tone_target": {"joy": 0.6}
    }  # per-call fields never leak into the shared body


class Reader(SimpleNamespace):
    enabled = True


@pytest.mark.asyncio
async def test_cognition_attaches_tone_to_each_line(stack):  # noqa: F811  (imported fixture)
    calls = []

    async def read_line(text, user_text=""):
        calls.append((text, user_text))
        return (
            None
            if "失败" in text
            else {"readout": {}, "expression": {"happy": 0.5}, "sentences": [{"text": text}]}
        )

    fixture = stack
    fixture.service.tone_reader = Reader(read_line=read_line)
    fixture.llm.chat.return_value = decision(
        dialogue=[
            {"agent": "luna", "text": "真好呀。", "emotion": "happy"},
            {"agent": "luna", "text": "读数失败也照常说。", "emotion": "calm"},
        ]
    )
    result = await run(fixture, text="我考过了")
    lines = result["decision"]["dialogue"]
    assert calls == [("真好呀。", "我考过了"), ("读数失败也照常说。", "我考过了")]
    assert lines[0]["tone_readout"]["expression"] == {"happy": 0.5}
    assert "tone_readout" not in lines[1]
    # one model completion still decides the turn; reading is not a second completion
    fixture.llm.chat.assert_awaited_once()
    assert (
        fixture.llm.chat.await_args.kwargs["priority"] == 1
    )  # a user turn jumps a local model's queue
    # dialogue first, speaker pinned: a small model can't echo its input or speak for others
    assert fixture.llm.chat.await_args.kwargs["prefill"] == '{"dialogue": [{"agent": "luna", "text": "'


def test_row_stringify_keeps_floats_numeric():
    """Floats have .hex() too: a `hasattr(v, "hex")` UUID check turned voice_speed
    1.0 into "1.0" and broke the character voice in /tts/synthesize."""
    from uuid import uuid4

    from ai_core.services.memory import _stringify_row

    uid = uuid4()
    row = _stringify_row({"id": uid, "importance": 0.8, "voice_speed": 1.0})
    assert row == {"id": str(uid), "importance": 0.8, "voice_speed": 1.0}


@pytest.mark.asyncio
async def test_a_logging_failure_never_discards_a_generated_reply(stack):  # noqa: F811
    async def broken(*a, **k):
        raise RuntimeError("raw_event_logs missing")

    stack.memory.record_raw_event = broken
    result = await run(stack, text="我叫小乔")
    assert result["decision"]["dialogue"][0]["text"] == "我在听。"
    assert stack.memory.rows  # the declared memory is still stored
    stack.rel.apply_turn.assert_awaited_once()
