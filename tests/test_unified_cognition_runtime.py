"""Unified cognition through HTTP and two voice bodies through real WebSockets.

No external provider, hardware, persistent database or user's live ports.
"""

import asyncio
import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
import pytest
import websockets

from engine.server.server import SoulForgeRuntimeServer
from gateway.pipeline.character_bridge import CharacterBridge
from soulforge_harness.protocol.frames import ActionCommand, BodyHello, decode, encode
from soulforge_harness.runtime.cognition_client import AICoreBehaviorLLM
from soulforge_harness.runtime.llm_interface import BehaviorDecision, SafeDecisionLLM
from soulforge_harness.runtime.memory_store import InMemoryMemoryStore
from soulforge_harness.runtime.models import (
    Event,
    EventKind,
    ImpactLevel,
    Persona,
    WorldState,
)
from soulforge_harness.runtime.runtime import CompanionRuntime


def decision():
    return BehaviorDecision(
        selected_intent="greet",
        emotional_read="happy",
        plan_delta="micro",
        impact=ImpactLevel.LOW,
        template_to_call="chatting",
        dialogue=[{"agent": "joi", "text": "我记得，也向你挥手。", "emotion": "happy"}],
        body_actions=["wave"],
    )


def test_fallback_is_counted_and_recovery_clears_stale_error():
    class Provider:
        provider_name = "test-provider"
        model = "test-model"
        failed = True

        def decide(self, *args):
            if self.failed:
                raise RuntimeError("DO-NOT-LEAK-a-secret")
            return decision()

    provider = Provider()
    safe = SafeDecisionLLM(provider)
    args = (
        Event(0, EventKind.USER_UTTERANCE, "user", "你好"),
        Persona("joi", "Joi", "creative_care"),
        WorldState(),
        "chatting",
        True,
    )
    try:
        failed = safe.decide(*args)
        assert failed.provider_status["fallback"]
        snapshot = safe.health_snapshot()
        assert snapshot["fallback_count"] == 1
        assert "DO-NOT-LEAK" not in json.dumps(snapshot)
        provider.failed = False
        recovered = safe.decide(*args)
        assert not recovered.provider_status["fallback"]
        assert not safe.last_fallback_reason
        snapshot = safe.health_snapshot()
        assert snapshot["status"] == "ok"
        assert snapshot["fallback_count"] == 1
        assert snapshot["providers"][0]["last_error"] is None
    finally:
        safe.shutdown()


def test_runtime_restores_authoritative_mood_from_store():
    store = InMemoryMemoryStore()
    store.remember(
        "joi",
        "semantic",
        "cognitive_state",
        {
            "pad": {"p": 0.7, "a": -0.4, "d": 0.1},
            "relationship": {"energy": 83},
        },
    )
    runtime = CompanionRuntime(
        [Persona("joi", "Joi", "creative_care")], memory_store=store
    )
    assert runtime.personas["joi"].valence == pytest.approx(0.7)
    assert runtime.personas["joi"].arousal == pytest.approx(0.3)
    assert runtime.personas["joi"].energy == pytest.approx(0.83)


@pytest.mark.asyncio
async def test_one_core_call_yields_action_and_only_requesting_voice_speaks():
    requests = []

    class CoreHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.path == "/cognition/decide"
            assert self.headers["X-Service-Token"] == "test-only"
            requests.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            result = {
                "decision": asdict(decision()),
                "authoritative_state": {
                    "pad": {"p": 0.6, "a": 0.2, "d": 0.1},
                    "emotion": "happy",
                    "relationship": {"energy": 80},
                },
                "provider_status": {
                    "provider": "fake-core",
                    "model": "joint-test",
                    "status": "ok",
                },
            }
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    core = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = threading.Thread(target=core.serve_forever, daemon=True)
    thread.start()
    llm = AICoreBehaviorLLM(
        f"http://127.0.0.1:{core.server_port}",
        service_token="test-only",
        brand_id=str(uuid4()),
        user_id=str(uuid4()),
    )
    server = SoulForgeRuntimeServer(
        [Persona("joi", "Joi", "creative_care")], llm=llm, tick_hz=20, time_scale=0.01
    )
    task = asyncio.create_task(server.serve(port=0))
    await asyncio.wait_for(server.ready.wait(), 3)
    url = f"ws://127.0.0.1:{server.bound_port}"
    first = CharacterBridge(url=url, agent_id="joi", body_id="voice-one", timeout_s=3)
    second = CharacterBridge(url=url, agent_id="joi", body_id="voice-two", timeout_s=3)
    try:
        await first.start()
        await second.start()
        async with websockets.connect(url + "/body") as visual:
            await visual.send(
                encode(
                    BodyHello(
                        "visual",
                        "web",
                        ["joi"],
                        {
                            "supported_steps": ["wave", "speak_line"],
                            "features": {"speech": True},
                        },
                    )
                )
            )
            await visual.recv()
            start = asyncio.get_running_loop().time()
            result = await first.process_utterance("我喜欢蓝色，向我挥手")
            elapsed = asyncio.get_running_loop().time() - start
            assert len(requests) == 1
            assert requests[0]["identity"]["body_id"] == "voice-one"
            assert "wave" in requests[0]["available_actions"]
            assert result["text"] == "我记得，也向你挥手。"
            assert result["provider_health"]["fallback_count"] == 0
            assert elapsed < 0.6  # decision_complete removes the old quiet timer
            assert second._unsolicited.empty()
            wave = None
            for _ in range(30):
                frame = decode(await asyncio.wait_for(visual.recv(), 2))
                if isinstance(frame, ActionCommand):
                    assert not frame.dialogue  # visual still receives motion
                    if frame.name == "wave":
                        wave = frame
                        break
            assert wave is not None
            assert wave.params["cognitive_state"]["emotion"] == "happy"
            assert server.runtime.personas["joi"].valence == pytest.approx(0.6)
            async with httpx.AsyncClient(trust_env=False) as client:
                health = (
                    await client.get(
                        f"http://127.0.0.1:{server.bound_port}/health/providers"
                    )
                ).json()
            assert health["status"] == "ok"
            assert health["providers"][0]["model"] == "joint-test"
            # Re-use a different body without introducing a new user/character.
            await second.process_utterance("刚才说了什么")
            assert (
                requests[0]["identity"]["user_id"] == requests[1]["identity"]["user_id"]
            )
            assert (
                requests[0]["identity"]["character_id"]
                == requests[1]["identity"]["character_id"]
            )
    finally:
        await first.close()
        await second.close()
        server.stop()
        await asyncio.wait_for(task, 3)
        await asyncio.to_thread(core.shutdown)
        core.server_close()


def test_quiet_cognition_drops_empty_speech_slot_without_inventing_words():
    from ai_core.services.cognition import _parse_decision

    value = asdict(decision())
    value["dialogue"] = [{"agent": "joi", "text": "  ", "emotion": "calm"}]
    parsed, _, _ = _parse_decision(json.dumps(value), "joi", "chatting", [])
    assert parsed.dialogue == []


@pytest.mark.asyncio
async def test_sentence_tts_uses_current_emotion_and_frozen_character(monkeypatch):
    from gateway.config import settings
    from gateway.pipeline.orchestrator import PipelineOrchestrator
    from gateway.session import Session
    from unittest.mock import AsyncMock

    monkeypatch.setattr(settings, "character_runtime_url", "ws://test-only")
    session = Session("test", "test", character_id="old-character", brand_id="brand")
    bridge = type("Bridge", (), {"confirm_spoken": AsyncMock()})()
    command = {
        "command_id": "two-sentences",
        "dialogue": "第一句。第二句。",
        "params": {
            "identity": {"character_id": "decision-character"},
            "emotion": "happy",
            "cognitive_state": {"emotion": "happy", "pad": {"p": 0.5, "a": 0, "d": 0}},
        },
    }
    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator._runtime_decision = AsyncMock(
        return_value=(bridge, {"text": command["dialogue"], "commands": [command]})
    )
    orchestrator.synthesize_tts = AsyncMock(return_value=b"audio")
    stream = orchestrator.process_text_stream(session, "测试")
    emotion = await anext(stream)
    assert emotion.kind == "emotion" and emotion.emotion == "happy"
    assert not orchestrator.synthesize_tts.called
    first = await anext(stream)
    assert first.text == "第一句。" and first.audio_data
    assert orchestrator.synthesize_tts.call_count == 1
    session.character_id = "new-character"
    second = await anext(stream)
    assert second.text == "第二句。"
    assert all(
        call.args[1] == "decision-character"
        for call in orchestrator.synthesize_tts.call_args_list
    )
    assert all(
        call.kwargs["emotion"] == "happy"
        for call in orchestrator.synthesize_tts.call_args_list
    )
    done = await anext(stream)
    assert done.stages["first_audio_ms"] is not None
    assert not bridge.confirm_spoken.called
    await stream.aclose()
