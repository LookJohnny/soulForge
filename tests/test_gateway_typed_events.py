"""Typed body events preserve source semantics and real playback boundaries."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.pipeline.character_bridge import CharacterBridge, RuntimeNoDialogueError
from gateway import server as server_module


@pytest.mark.asyncio
async def test_environment_event_wire_completes_without_dialogue(monkeypatch):
    bridge = CharacterBridge(
        url="ws://unused.invalid", agent_id="kai", body_id="touch-body"
    )
    sent = []

    async def send(frame):
        data = json.loads(frame)
        sent.append(data)
        event_id = data["payload"]["event_id"]
        await bridge._waiters[event_id].put(
            {
                "type": "decision_complete",
                "correlation_id": event_id,
                "provider_health": {"status": "ok"},
            }
        )

    monkeypatch.setattr(
        bridge, "_ensure_connected", AsyncMock(return_value=SimpleNamespace(send=send))
    )
    result = await bridge.process_event(
        "environment",
        source="touch_sensor",
        payload={"touch": {"gesture": "hug"}},
    )
    assert sent[0]["kind"] == "environment" and sent[0]["source"] == "touch_sensor"
    assert sent[0]["payload"]["touch"]["gesture"] == "hug"
    assert result["text"] == "" and result["commands"] == []
    assert result["provider_health"]["status"] == "ok"
    assert not bridge._waiters


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_empty_utterance_decision_is_distinct_from_deadline(
    monkeypatch, completed
):
    bridge = CharacterBridge(url="ws://unused.invalid", agent_id="kai", timeout_s=0.02)

    async def send(frame):
        correlation = json.loads(frame)["payload"]["event_id"]
        if completed:
            await bridge._waiters[correlation].put(
                {
                    "type": "decision_complete",
                    "correlation_id": correlation,
                }
            )

    monkeypatch.setattr(
        bridge, "_ensure_connected", AsyncMock(return_value=SimpleNamespace(send=send))
    )
    error = RuntimeNoDialogueError if completed else TimeoutError
    with pytest.raises(error) as caught:
        await bridge.process_utterance("请回应")
    assert isinstance(caught.value, TimeoutError) is not completed
    assert not bridge._waiters


@pytest.mark.asyncio
async def test_retired_bridge_does_not_reconnect_after_a_late_identity_resolve(
    monkeypatch,
):
    connect = AsyncMock()
    monkeypatch.setattr("gateway.pipeline.character_bridge.websockets.connect", connect)
    bridge = CharacterBridge(url="ws://unused.invalid", agent_id="kai")
    await bridge.close()
    with pytest.raises(ConnectionError, match="retired"):
        await bridge.process_utterance("旧角色的迟到请求")
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_silent_touch_reaches_live_runtime_once_and_completes_without_timeout():
    from engine.server.server import SoulForgeRuntimeServer
    from soulforge_harness.runtime.llm_interface import BehaviorDecision
    from soulforge_harness.runtime.models import EventKind, ImpactLevel, Persona

    class Cognition:
        calls = []
        provider_name, model = "test", "silent-environment"

        def decide(self, event, *args):
            self.calls.append(event)
            return BehaviorDecision(
                selected_intent="notice_touch",
                emotional_read="calm",
                plan_delta="micro",
                impact=ImpactLevel.LOW,
                template_to_call="chatting",
                dialogue=[],
            )

    llm = Cognition()
    runtime = SoulForgeRuntimeServer(
        [Persona("kai", "Kai", "steady_caretaker")],
        llm=llm,
        time_scale=0.01,
        tick_hz=10,
    )
    task = asyncio.create_task(runtime.serve(port=0))
    await asyncio.wait_for(runtime.ready.wait(), 3)
    bridge = CharacterBridge(
        url=f"ws://127.0.0.1:{runtime.bound_port}", agent_id="kai", timeout_s=2
    )
    try:
        result = await bridge.process_event(
            "environment", source="touch_sensor", payload={"touch": {"gesture": "pat"}}
        )
        assert result["text"] == "" and result["commands"] == []
        assert len(llm.calls) == 1
        assert llm.calls[0].kind is EventKind.ENVIRONMENT
        assert llm.calls[0].payload["touch"] == {"gesture": "pat"}
        assert result["provider_health"]["fallback_count"] == 0
    finally:
        await bridge.close()
        runtime.stop()
        await asyncio.wait_for(task, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_touch_server_confirms_only_after_playback_or_reports_failure(
    monkeypatch, fails
):
    events = []

    class Playback:
        interrupted = False

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def send_sentence(self, text):
            events.append("text")

        async def send_clip(self, audio, **kwargs):
            events.append("audio")
            if fails:
                raise RuntimeError("playback failure")

        async def finish(self, **kwargs):
            assert kwargs.get("wait_drain") is not False
            events.append("drained")

    async def confirm(receipt, *, played, detail):
        assert receipt == "touch-receipt"
        events.append("done" if played else "interrupted")

    server = server_module.WebSocketServer.__new__(server_module.WebSocketServer)
    server.orchestrator = SimpleNamespace(
        process_touch=AsyncMock(
            return_value={
                "text": "收到。",
                "audio_data": b"audio",
                "playback_receipt": "touch-receipt",
            }
        ),
        confirm_playback=confirm,
    )
    monkeypatch.setattr(server_module, "PlaybackChannel", Playback)
    await server._handle_touch(
        None, None, SimpleNamespace(), SimpleNamespace(payload={"gesture": "hug"})
    )
    assert events == (
        ["text", "audio", "interrupted"]
        if fails
        else ["text", "audio", "drained", "done"]
    )
