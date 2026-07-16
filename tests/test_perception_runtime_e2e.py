"""Real WS acceptance: perception -> Runtime -> ActionCommand -> TTS -> ACK."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

GATEWAY_SRC = Path(__file__).resolve().parents[1] / "packages" / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from engine.perception import (  # noqa: E402
    MockVisionProvider,
    PerceptionFusion,
    PerceptionRuntime,
    RuntimePerceptionSink,
)
from engine.perception.sources import Frame  # noqa: E402
from engine.planner import MockBehaviorLLM, Persona  # noqa: E402
from engine.server import SoulForgeRuntimeServer  # noqa: E402
from gateway.config import settings  # noqa: E402
from gateway.pipeline.character_bridge import CharacterBridge  # noqa: E402
from gateway.pipeline.orchestrator import PipelineOrchestrator  # noqa: E402
from gateway.session import Session  # noqa: E402


async def _wait_until(predicate, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition did not become true before timeout")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_visual_event_reaches_tts_and_terminal_ack_over_real_websockets(
    monkeypatch,
):
    server = SoulForgeRuntimeServer(
        [Persona("kai", "Kai", "steady_caretaker")],
        start_minute=19 * 60,
        tick_hz=20,
        llm=MockBehaviorLLM(),
    )
    serve_task = asyncio.create_task(server.serve(port=0))
    await asyncio.wait_for(server.ready.wait(), timeout=3)
    runtime_url = f"ws://127.0.0.1:{server.bound_port}"
    monkeypatch.setattr(settings, "character_runtime_url", runtime_url)
    monkeypatch.setattr(settings, "character_runtime_agent", "kai")

    bridge = CharacterBridge(
        url=runtime_url,
        agent_id="kai",
        body_id="e2e-voice",
        timeout_s=2,
    )
    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator._character_bridge = bridge
    orchestrator._pending_playback = {}
    synthesized = []

    async def synthesize(text, character_id, brand_id=None):
        synthesized.append((text, character_id, brand_id))
        return b"offline-tts-audio"

    orchestrator.synthesize_tts = synthesize
    sink = RuntimePerceptionSink(runtime_url)

    try:
        await bridge.start()
        await sink.start()
        perception = PerceptionRuntime(
            fusion=PerceptionFusion(
                source_body="e2e-camera", target_agent="kai", debounce_s=0.0
            ),
            vision_provider=MockVisionProvider(),
            emit=sink.emit,
        )
        events = perception.process_frame(
            Frame(
                ts=1.0,
                ref="memory://person.png",
                data=b"\x89PNGfixture",
                sidecar={
                    "scene": "room",
                    "entities": [
                        {
                            "entity_id": "provider-person",
                            "label": "person",
                            "confidence": 0.9,
                            "bbox": [0.1, 0.1, 0.2, 0.4],
                        }
                    ],
                    "relations": [],
                },
            ),
            now=1.0,
        )
        assert len(events) == 1
        await asyncio.wait_for(sink.drain(), timeout=2)

        session = Session("e2e-session", "e2e-device", character_id="kai")
        chunk = await orchestrator.process_next_runtime_dialogue(session, timeout_s=3)
        assert chunk.text
        assert chunk.audio_data == b"offline-tts-audio"
        assert chunk.playback_receipt
        assert synthesized == [(chunk.text, "kai", None)]

        body = server.bodies[bridge.body_id]
        command = next(iter(body.sent_commands.values()))
        assert command.name == "speak_line"
        assert command.correlation_id == events[0].event_id

        assert await orchestrator.confirm_playback(chunk.playback_receipt, played=True)
        await _wait_until(lambda: command.command_id not in body.sent_commands)
        assert any(
            entry.kind == "observation"
            and entry.detail.get("status") == "done"
            and entry.detail.get("step") == "speak_line"
            for entry in server.runtime.trace
        )
    finally:
        await sink.close()
        await bridge.close()
        server.stop()
        await asyncio.wait_for(serve_task, timeout=3)
