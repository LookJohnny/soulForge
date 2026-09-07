"""Measured unified stages travel through the real voice recorder and endpoint.

The clock, Runtime/TTS response and device transport are synthetic. No server,
provider, codec, hardware or audio playback is started by this test.
"""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from gateway.config import settings
from gateway.latency import LatencyTracker
from gateway.protocols.base import MessageType
from gateway.session import Session


class Clock:
    now = 100.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.mark.asyncio
async def test_done_stages_reach_gateway_latency_endpoint_after_voice_delivery(monkeypatch):
    monkeypatch.setattr(settings, "face_host", "")
    monkeypatch.setattr(settings, "character_runtime_url", "ws://synthetic.test")
    main = importlib.import_module("gateway.main")
    server_module = importlib.import_module("gateway.server")
    pipeline_module = importlib.import_module("gateway.pipeline.orchestrator")
    playback_module = importlib.import_module("gateway.playback")
    latency_module = importlib.import_module("gateway.latency")
    clock, tracker = Clock(), LatencyTracker()
    for module in (server_module, pipeline_module, playback_module):
        monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(latency_module, "latency_tracker", tracker)
    monkeypatch.setattr(server_module, "latency_tracker", tracker)
    monkeypatch.setattr(playback_module, "speaking_hook", None)
    monkeypatch.setattr(playback_module, "audio_hook", None)
    monkeypatch.setattr(playback_module, "SETTLE_SECS", 0)
    monkeypatch.setattr(playback_module, "MIN_DRAIN_SECS", 0)
    provide_audio = True

    async def decide(session, text):
        clock.advance(0.120)
        return None, {"text": "合成回复。", "commands": [{"dialogue": "合成回复。"}]}

    async def synthesize(*args, **kwargs):
        clock.advance(0.080)
        return b"synthetic-encoded-audio" if provide_audio else None

    class Adapter:
        async def encode(self, message):
            if message.type == MessageType.AUDIO:
                clock.advance(0.030)  # independent audio conversion/delivery boundary
                return [b"synthetic-opus-frame"]
            return json.dumps({"payload": message.payload, "metadata": message.metadata})

    orchestrator = pipeline_module.PipelineOrchestrator.__new__(
        pipeline_module.PipelineOrchestrator
    )
    orchestrator._runtime_decision = AsyncMock(side_effect=decide)
    orchestrator.synthesize_tts = AsyncMock(side_effect=synthesize)
    server = server_module.WebSocketServer.__new__(server_module.WebSocketServer)
    server.orchestrator = orchestrator
    server.session_manager = SimpleNamespace(add_to_history=AsyncMock())
    session = Session("synthetic", "synthetic", character_id="synthetic", brand_id="synthetic")
    session._t_speech_end = 99.950  # VAD anchor is earlier than the decision request.
    ws = SimpleNamespace(send_text=AsyncMock(), send_bytes=AsyncMock())
    adapter = Adapter()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://synthetic.test"
    ) as client:
        assert (await client.get("/metrics/latency")).json() == {}
        await server._process_text_and_respond_streaming(ws, adapter, session, "合成输入")
        ws.send_bytes.assert_awaited_once_with(b"synthetic-opus-frame")
        snapshot = (await client.get("/metrics/latency")).json()["voice_turn"]
        assert snapshot["last_turn"]["decision_ms"] == 120
        assert snapshot["last_turn"]["first_audio_ms"] == 200
        assert snapshot["last_turn"]["first_word"] == 280
        assert snapshot["last_turn"]["core_first_audio_ms"] == 200

        # A TTS failure still has a measured decision, but no generated audio
        # and no sent frame. It must not become a fast zero-millisecond sample.
        provide_audio = False
        await server._process_text_and_respond_streaming(ws, adapter, session, "第二个合成输入")
        snapshot = (await client.get("/metrics/latency")).json()["voice_turn"]
        assert snapshot["turns"] == 2
        assert snapshot["stages_ms"]["decision_ms"]["count"] == 2
        assert snapshot["stages_ms"]["first_audio_ms"]["count"] == 1
        assert snapshot["stages_ms"]["first_audio_ms"]["missing_count"] == 1
        assert "first_audio_ms" not in snapshot["last_turn"]
        assert "first_word" not in snapshot["last_turn"]
        assert ws.send_bytes.await_count == 1
