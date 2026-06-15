"""Tests for Gateway reaction event bridge."""

import json
from types import SimpleNamespace

from gateway.pipeline.orchestrator import PipelineOrchestrator
from gateway.protocols.base import MessageType
from gateway.protocols.generic_ws import GenericWSAdapter
from gateway.protocols.web_audio import WebAudioAdapter
from gateway.server import WebSocketServer
from gateway.session import Session


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def post(self, path, json=None, headers=None):
        self.calls.append({"path": path, "json": json, "headers": headers})
        if path == "/memory/reaction":
            return _FakeResponse(
                {
                    "should_react": True,
                    "reaction_type": "verbal_and_action",
                    "reason": "battery_low_requires_safe_degradation",
                    "speech": {"text": "我快没电了", "style": "soft"},
                    "actions": [{"channel": "led", "pattern": "breathe"}],
                    "plan_patch": {"mode": "power_saving"},
                    "safety_flags": ["low_power"],
                }
            )
        if path == "/actions/preview":
            return _FakeResponse(
                {
                    "status": "allowed",
                    "commands": [
                        {"channel": "speech", "text": "我快没电了", "style": "soft"},
                        {"channel": "led", "pattern": "breathe"},
                    ],
                    "audit": [],
                    "safety_flags": [],
                }
            )
        raise AssertionError(path)


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


class _FakeAdapter:
    async def encode(self, message):
        return json.dumps({"type": message.type.value, "payload": message.payload})


async def test_orchestrator_process_reaction_event_calls_ai_core_and_safety_preview():
    fake_client = _FakeClient()
    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator.client = fake_client
    orchestrator.stream_client = fake_client
    session = Session(
        session_id="s1",
        device_id="dev1",
        character_id="00000000-0000-0000-0000-000000000002",
        end_user_id="00000000-0000-0000-0000-000000000001",
        brand_id="brand1",
        protocol="generic_ws",
    )

    result = await orchestrator.process_reaction_event(
        session,
        event_type="battery_low",
        event={"battery_percent": 4},
        device_manifest={"channels": {"led": True}},
    )

    assert result["reaction"]["should_react"] is True
    assert result["action_preview"]["commands"][0]["channel"] == "speech"
    assert [call["path"] for call in fake_client.calls] == ["/memory/reaction", "/actions/preview"]
    assert fake_client.calls[0]["json"]["user_id"] == session.end_user_id
    assert fake_client.calls[0]["json"]["character_id"] == session.character_id
    assert fake_client.calls[1]["json"]["device_state"]["battery_percent"] == 4
    assert fake_client.calls[1]["headers"] == {"X-Brand-Id": "brand1"}


async def test_generic_ws_decodes_reaction_event_control_message():
    adapter = GenericWSAdapter()

    msg = await adapter.decode(
        json.dumps(
            {
                "action": "event",
                "event_type": "battery_low",
                "event": {"battery_percent": 4},
            }
        )
    )

    assert msg.type == MessageType.CONTROL
    assert msg.payload["action"] == "reaction_event"
    assert msg.payload["event_type"] == "battery_low"
    assert msg.payload["event"]["battery_percent"] == 4


async def test_web_audio_decodes_reaction_event_control_message():
    adapter = WebAudioAdapter()

    msg = await adapter.decode(
        json.dumps(
            {
                "type": "device_event",
                "event_type": "silence",
                "event": {"idle_seconds": 1800},
            }
        )
    )

    assert msg.type == MessageType.CONTROL
    assert msg.payload["action"] == "reaction_event"
    assert msg.payload["event_type"] == "silence"


async def test_server_reaction_event_sends_control_payload():
    server = WebSocketServer.__new__(WebSocketServer)

    async def fake_process_reaction_event(*args, **kwargs):
        assert kwargs["event_type"] == "battery_low"
        return {
            "reaction": {"should_react": True, "reaction_type": "verbal_and_action"},
            "action_preview": {"status": "allowed", "commands": []},
        }

    server.orchestrator = SimpleNamespace(process_reaction_event=fake_process_reaction_event)
    ws = _FakeWS()
    adapter = _FakeAdapter()
    session = Session(session_id="s1", device_id="dev1")

    await server._handle_reaction_event(
        ws,
        adapter,
        session,
        {"event_type": "battery_low", "event": {"battery_percent": 4}},
    )

    sent = json.loads(ws.sent[0])
    assert sent["type"] == "control"
    assert sent["payload"]["type"] == "reaction"
    assert sent["payload"]["reaction"]["should_react"] is True
