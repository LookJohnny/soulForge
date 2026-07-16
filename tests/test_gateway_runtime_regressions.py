"""Regression tests for the Character Runtime <-> gateway voice bridge."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

GATEWAY_SRC = Path(__file__).resolve().parents[1] / "packages" / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from engine.planner import MockBehaviorLLM, Persona  # noqa: E402
from engine.server import SoulForgeRuntimeServer  # noqa: E402
from gateway.config import settings  # noqa: E402
from gateway.pipeline.character_bridge import CharacterBridge  # noqa: E402
from gateway.pipeline.orchestrator import PipelineOrchestrator  # noqa: E402
from gateway.session import Session  # noqa: E402


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true before timeout")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_ephemeral_runtime_voice_bridge_uses_two_phase_ack_and_rejects_forgery():
    server = SoulForgeRuntimeServer(
        [
            Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.8}),
            Persona("luna", "Luna", "creative_care", relationships={"user": 0.8}),
        ],
        start_minute=19 * 60,
        time_scale=1.0,
        tick_hz=8.0,
        llm=MockBehaviorLLM(),
    )
    serve_task = asyncio.create_task(server.serve(port=0))
    await asyncio.wait_for(server.ready.wait(), timeout=5)
    bridge = CharacterBridge(
        url=f"ws://127.0.0.1:{server.bound_port}",
        agent_id="kai",
        timeout_s=2.0,
        body_id="gateway-voice-test",
    )

    try:
        decision = await bridge.process_utterance("我今天很难过")
        assert decision["text"]
        assert decision["commands"]
        assert all(command.get("dialogue") for command in decision["commands"])

        body = server.bodies[bridge.body_id]
        assert body.manifest.supported_steps == ["speak_line"]
        assert body.manifest.supported_templates == []
        assert body.manifest.features == {
            "speech": True,
            "speech_only": True,
            "gaze": False,
            "nav": False,
        }

        command_id = decision["commands"][0]["command_id"]
        # CharacterBridge has sent accepted, but accepted is not completion.
        await _wait_until(lambda: command_id in body.sent_commands)
        accepted = [
            item
            for item in server.runtime.trace
            if item.kind == "observation" and item.detail.get("status") == "accepted"
        ]
        assert any(item.detail.get("step") == "speak_line" for item in accepted)

        # A forged cross-agent terminal receipt must not consume the command.
        await bridge._socket.send(
            json.dumps(
                {
                    "type": "observation",
                    "command_id": command_id,
                    "agent_id": "luna",
                    "status": "done",
                    "body_id": bridge.body_id,
                }
            )
        )
        await _wait_until(
            lambda: any(
                item.kind == "observation_rejected"
                and item.detail.get("reason") == "agent_id mismatch"
                for item in server.runtime.trace
            )
        )
        assert command_id in body.sent_commands

        # Only actual playback completion removes the pending command.
        await bridge.confirm_spoken(command_id)
        await _wait_until(lambda: command_id not in body.sent_commands)
        terminal = [
            item
            for item in server.runtime.trace
            if item.kind == "observation" and item.detail.get("status") == "done"
        ]
        assert any(item.detail.get("step") == "speak_line" for item in terminal)
    finally:
        await bridge.close()
        server.stop()
        await asyncio.wait_for(serve_task, timeout=5)


class _FakeBridge:
    def __init__(self):
        self.utterances: list[str] = []
        self.confirmations: list[tuple[str, bool, str]] = []

    async def process_utterance(self, text: str):
        self.utterances.append(text)
        return {
            "text": "我听到了。",
            "correlation_id": "turn-1",
            "commands": [
                {
                    "command_id": "speech-1",
                    "dialogue": "我听到了。",
                    "correlation_id": "turn-1",
                }
            ],
        }

    async def confirm_spoken(self, command_id: str, *, played: bool, detail: str):
        self.confirmations.append((command_id, played, detail))


class _ExplodingLegacyClient:
    def stream(self, *args, **kwargs):
        raise AssertionError("legacy /pipeline/chat/stream must not be called")


def _orchestrator_with_fake_bridge(fake: _FakeBridge) -> PipelineOrchestrator:
    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator._character_bridge = fake
    orchestrator._pending_playback = {}
    orchestrator.stream_client = _ExplodingLegacyClient()
    return orchestrator


@pytest.mark.asyncio
async def test_tts_yield_never_confirms_before_explicit_playback_receipt(monkeypatch):
    fake = _FakeBridge()
    orchestrator = _orchestrator_with_fake_bridge(fake)
    session = Session("s1", "device-1", character_id="character-1")

    async def synthesize(*args, **kwargs):
        return b"mp3-audio"

    orchestrator.synthesize_tts = synthesize
    monkeypatch.setattr(settings, "character_runtime_url", "ws://runtime")

    stream = orchestrator.process_text_stream(session, "你好")
    sentence = await anext(stream)
    assert sentence.audio_data == b"mp3-audio"
    assert sentence.playback_receipt
    assert fake.confirmations == []

    done = await anext(stream)
    assert done.is_done
    assert done.playback_receipt == sentence.playback_receipt
    assert fake.confirmations == []

    assert await orchestrator.confirm_playback(sentence.playback_receipt)
    assert fake.confirmations == [("speech-1", True, "")]
    assert not await orchestrator.confirm_playback(sentence.playback_receipt)


@pytest.mark.asyncio
async def test_tts_exception_marks_accepted_command_interrupted(monkeypatch):
    fake = _FakeBridge()
    orchestrator = _orchestrator_with_fake_bridge(fake)
    session = Session("s1", "device-1", character_id="character-1")

    async def synthesize(*args, **kwargs):
        raise RuntimeError("provider offline")

    orchestrator.synthesize_tts = synthesize
    monkeypatch.setattr(settings, "character_runtime_url", "ws://runtime")

    stream = orchestrator.process_text_stream(session, "你好")
    with pytest.raises(RuntimeError, match="provider offline"):
        await anext(stream)
    assert fake.confirmations == [
        ("speech-1", False, "TTS synthesis raised an error"),
    ]
    assert orchestrator._pending_playback == {}


@pytest.mark.asyncio
async def test_audio_fallback_is_asr_only_then_character_runtime(monkeypatch):
    fake = _FakeBridge()
    orchestrator = _orchestrator_with_fake_bridge(fake)
    session = Session("s1", "device-1", character_id="character-1")

    async def transcribe(audio_data: bytes, audio_format: str = "pcm") -> str:
        assert audio_data == b"buffered-pcm"
        assert audio_format == "pcm"
        return "离线转写文本"

    async def synthesize(*args, **kwargs):
        return b"mp3-audio"

    orchestrator._transcribe_audio = transcribe
    orchestrator.synthesize_tts = synthesize
    monkeypatch.setattr(settings, "character_runtime_url", "ws://runtime")

    chunks = [
        chunk
        async for chunk in orchestrator.process_audio_stream(
            session, b"buffered-pcm", audio_format="pcm"
        )
    ]
    assert fake.utterances == ["离线转写文本"]
    assert chunks[0].text == "我听到了。"
    assert chunks[-1].is_done and chunks[-1].user_text == "离线转写文本"
    assert fake.confirmations == []


@pytest.mark.asyncio
async def test_asr_only_failure_drops_turn_without_legacy_llm(monkeypatch):
    fake = _FakeBridge()
    orchestrator = _orchestrator_with_fake_bridge(fake)
    session = Session("s1", "device-1", character_id="character-1")

    async def transcribe(audio_data: bytes, audio_format: str = "pcm") -> str:
        return ""

    orchestrator._transcribe_audio = transcribe
    monkeypatch.setattr(settings, "character_runtime_url", "ws://runtime")

    chunks = [
        chunk
        async for chunk in orchestrator.process_audio_stream(session, b"bad-audio")
    ]
    assert len(chunks) == 1 and chunks[0].is_done
    assert chunks[0].stages == {"asr_only": "no_transcript"}
    assert fake.utterances == []
