"""Offline media contract tests: fake cognition, TTS, ASR and body transport."""
import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from starlette.requests import ClientDisconnect

from gateway.config import settings
from gateway.media_api import MediaSessions, TurnRequest, build_router
from gateway.pipeline.character_bridge import CharacterBridge, RuntimeNoDialogueError

pytestmark = pytest.mark.asyncio


class FakeBridge:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.agent_id = "joi"
        self.closed = False
        self.calls = []
        self.observations = []
        self.started = asyncio.Event()
        self.gate = None
        self.ignore_cancel = False

    async def start(self):
        pass

    async def close(self):
        self.closed = True

    async def confirm_spoken(self, command_id, **kwargs):
        self.observations.append((command_id, kwargs))

    async def process_utterance(self, text, *, payload):
        self.calls.append((text, payload))
        self.started.set()
        if self.gate:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                if not self.ignore_cancel:
                    raise
                await self.gate.wait()
        return {"text": "你好。慢慢说。", "commands": [{
            "command_id": f"c{len(self.calls)}", "dialogue": "你好。慢慢说。",
            "params": {"emotion": "warm", "cognitive_state": {
                "emotion": "curious", "pad": {"p": 0.2, "a": 0.1, "d": 0.3}}},
        }]}


@pytest_asyncio.fixture
async def media(monkeypatch):
    for key, value in {"gateway_api_token": "media-test-token", "service_token": "core-test-token",
                       "soulforge_brand_id": "brand-configured", "soulforge_user_id": "owner-configured",
                       "character_runtime_url": "ws://fake.invalid", "character_runtime_agent": "joi"}.items():
        monkeypatch.setattr(settings, key, value)
    bridges = []

    def factory(**kwargs):
        bridge = FakeBridge(**kwargs)
        bridges.append(bridge)
        return bridge

    async def resolve(body, sid, *, agent_id):
        return {"user_id": "owner-configured", "character_id": "character-canonical",
                "agent_id": agent_id, "body_id": body, "session_id": sid}

    brain = SimpleNamespace(
        _resolve_runtime_identity=AsyncMock(side_effect=resolve),
        synthesize_tts=AsyncMock(return_value=b"ID3-fake-audio"),
        _transcribe_audio=AsyncMock(return_value="识别文本"),
        _beat_emotion=lambda commands: commands[0].get("params", {}).get("emotion"),
    )
    manager = MediaSessions(brain, bridge_factory=factory)
    app = FastAPI()
    app.include_router(build_router(manager))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fake",
                                headers={"Authorization": "Bearer media-test-token"}) as client:
        yield manager, brain, bridges, client
    await manager.close_all()


async def new(media):
    response = await media[3].post("/media/sessions", json={"body_id": "joi-face"})
    assert response.status_code == 200
    return response.json()["session_id"]


async def rendered(media, sid, turn_id="t1"):
    response = await media[3].post(f"/media/sessions/{sid}/turn", json={"text": "你好", "turn_id": turn_id})
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines()]


@pytest.mark.parametrize("path,payload", [
    ("/media/sessions", {"body_id": "joi"}),
    ("/media/sessions/x/turn", {"text": "hi", "turn_id": "t"}),
    ("/media/sessions/x/interrupt", {"turn_id": "t"}),
    ("/media/sessions/x/receipt", {"receipt_id": "r", "played": True}),
    ("/media/sessions/x/close", {}),
    ("/media/sessions/x/transcribe", {"audio_base64": "AAA="}),
])
async def test_every_media_route_requires_bearer(media, path, payload, monkeypatch):
    response = await media[3].post(path, json=payload, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    monkeypatch.setattr(settings, "gateway_api_token", "")
    assert (await media[3].post(path, json=payload)).status_code == 503
    assert media[2] == []


async def test_canonical_identity_and_one_runtime_call_with_persistent_bridge(media):
    manager, brain, bridges, client = media
    sid = await new(media)
    events = await rendered(media, sid)
    assert [e["type"] for e in events] == ["decision", "audio", "audio", "done"]
    assert events[0]["emotion"] == "curious"
    assert events[0]["pad"]["p"] == 0.2
    assert events[1]["emotion"] == "warm"
    assert events[1]["receipt_id"] == events[2]["receipt_id"]
    assert base64.b64decode(events[1]["audio_base64"]) == b"ID3-fake-audio"
    assert len(bridges[0].calls) == 1
    identity = bridges[0].calls[0][1]["identity"]
    assert identity["user_id"] == "owner-configured"
    assert identity["character_id"] == "character-canonical"
    assert identity["body_id"].startswith("media-joi-face-")
    assert bridges[0].autonomous_speech is False
    assert not bridges[0].observations, "synthesis and NDJSON delivery do not prove playback"
    await rendered(media, sid, "t2")
    assert len(bridges) == 1
    assert len(bridges[0].calls) == 2
    assert brain._resolve_runtime_identity.await_count == 1
    assert (await client.post(f"/media/sessions/{sid}/turn", json={"text": "changed", "turn_id": "t1"})).status_code == 409


async def test_media_correlation_survives_real_runtime_replanner_and_bridge(media, monkeypatch):
    """A fake decision over ephemeral real WS; no provider, DB, GPU or live port."""
    # The engine host lives at the repository root, outside the installed Gateway
    # package. Console-script pytest does not add that root like python -m pytest.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]))
    from engine.server.server import SoulForgeRuntimeServer
    from soulforge_harness.runtime.llm_interface import BehaviorDecision
    from soulforge_harness.runtime.models import ImpactLevel, Persona

    class Cognition:
        provider_name, model = "test", "media-correlation"

        def __init__(self):
            self.calls = []

        def decide(self, event, *args):
            self.calls.append(event)
            return BehaviorDecision(
                selected_intent="reply", emotional_read="calm", plan_delta="micro",
                impact=ImpactLevel.LOW, template_to_call="chatting",
                dialogue=[{"agent": "joi", "text": "收到。", "emotion": "calm"}],
            )

    cognition = Cognition()
    runtime = SoulForgeRuntimeServer([Persona("joi", "Joi", "creative_care")],
                                    llm=cognition, time_scale=.01, tick_hz=20)
    serve = asyncio.create_task(runtime.serve(port=0))
    manager, _, _, client = media
    try:
        await asyncio.wait_for(runtime.ready.wait(), 3)

        def factory(**kwargs):
            return CharacterBridge(**{**kwargs, "url": f"ws://127.0.0.1:{runtime.bound_port}",
                                      "agent_id": "joi", "timeout_s": 2})

        manager.bridge_factory = factory
        sid = await new(media)
        for turn_id in ("031ffdad-4bfc-4829-b52e-35ab80099c4a", "x" * 128, "client:turn.3"):
            events = await rendered(media, sid, turn_id)
            assert [item["type"] for item in events] == ["decision", "audio", "done"]
            assert events[1]["text"] == "收到。"
            command = events[0]["actions"][0]
            assert command["correlation_id"] == cognition.calls[-1].payload["event_id"]
            assert command["params"]["reply_body_id"] == manager.get(sid).bridge.body_id
            assert manager.get(sid).bridge._unsolicited.empty()
            assert (await client.post(f"/media/sessions/{sid}/receipt", json={
                "receipt_id": events[1]["receipt_id"], "played": False,
            })).status_code == 200
        assert len(cognition.calls) == 3
        assert len({event.payload["event_id"] for event in cognition.calls}) == 3
    finally:
        await manager.close_all()
        runtime.stop()
        await asyncio.wait_for(serve, 3)


async def test_completed_runtime_without_dialogue_is_not_reported_as_timeout(media):
    manager, brain, bridges, _ = media
    sid = await new(media)
    bridges[0].process_utterance = AsyncMock(side_effect=RuntimeNoDialogueError("completed without speech"))
    events = await rendered(media, sid)
    assert events == [{"type": "error", "turn_id": "t1", "error": "runtime_no_dialogue"}]
    bridges[0].process_utterance.assert_awaited_once()
    brain.synthesize_tts.assert_not_called()
    assert bridges[0].closed and not manager.get(sid).receipts


async def test_browser_cannot_supply_identity(media):
    client = media[3]
    for key in ("user_id", "brand_id", "character_id", "agent_id"):
        response = await client.post("/media/sessions", json={"body_id": "face", key: "attacker"})
        assert response.status_code == 422
    sid = await new(media)
    response = await client.post(f"/media/sessions/{sid}/turn", json={"text": "hi", "turn_id": "t", "identity": {}})
    assert response.status_code == 422
    assert not media[2][0].calls


async def test_receipts_are_session_owned_and_once_only_even_concurrently(media):
    manager, _, bridges, client = media
    sid, other = await new(media), await new(media)
    rid = (await rendered(media, sid))[1]["receipt_id"]
    payload = {"receipt_id": rid, "played": True, "detail": "audio and video drained"}
    assert (await client.post(f"/media/sessions/{other}/receipt", json=payload)).status_code == 404
    responses = await asyncio.gather(*(client.post(f"/media/sessions/{sid}/receipt", json=payload) for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [200, 404]
    assert len(bridges[0].observations) == 1
    assert bridges[0].observations[0][1]["played"] is True


async def test_inflight_conflict_and_interrupt_retires_bridge_before_next_turn(media):
    manager, _, bridges, client = media
    sid = await new(media)
    old = bridges[0]
    old.gate = asyncio.Event()
    response = manager.turn(sid, TurnRequest(text="first", turn_id="t1"))
    await old.started.wait()
    blocked = await client.post(f"/media/sessions/{sid}/turn", json={"text": "second", "turn_id": "t2"})
    assert blocked.status_code == 409
    assert (await client.post(f"/media/sessions/{sid}/interrupt", json={"turn_id": "other"})).json()["interrupted"] is False
    result = await client.post(f"/media/sessions/{sid}/interrupt", json={"turn_id": "t1"})
    assert result.json()["interrupted"] is True
    assert old.closed
    assert not media[1].synthesize_tts.called
    events = [json.loads(line) async for line in response.body_iterator]
    assert events == [{"type": "error", "turn_id": "t1", "error": "turn_interrupted"}]
    await rendered(media, sid, "t2")
    assert len(bridges) == 2
    assert bridges[1].body_id != old.body_id


async def test_cancel_before_producer_first_runs_does_not_leave_active_slot(media):
    manager = media[0]
    sid = await new(media)
    manager.turn(sid, TurnRequest(text="hello", turn_id="never-started"))
    await manager.interrupt(sid, "never-started")
    assert manager.sessions[sid].active is None
    await rendered(media, sid, "next")


async def test_late_result_from_cancellation_resistant_provider_is_never_published(media):
    manager, brain, bridges, _ = media
    sid = await new(media)
    bridge = bridges[0]
    bridge.gate = asyncio.Event()
    bridge.ignore_cancel = True
    response = manager.turn(sid, TurnRequest(text="hi", turn_id="t1"))
    await bridge.started.wait()
    await manager.interrupt(sid, "t1")
    assert manager.sessions[sid].active is not None
    bridge.gate.set()
    await manager.sessions[sid].active.task
    assert not brain.synthesize_tts.called
    assert all([json.loads(line)["type"] == "error" async for line in response.body_iterator])


async def test_disconnect_cancels_tts_and_marks_receipt_interrupted(media):
    manager, brain, bridges, _ = media
    sid = await new(media)
    entered = asyncio.Event()
    async def tts(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    brain.synthesize_tts.side_effect = tts
    response = manager.turn(sid, TurnRequest(text="hi", turn_id="t1"))
    iterator = response.body_iterator
    assert json.loads(await anext(iterator))["type"] == "decision"
    await entered.wait()
    await iterator.aclose()
    assert manager.sessions[sid].active is None
    assert not manager.sessions[sid].receipts
    assert bridges[0].observations[0][1]["played"] is False
    assert bridges[0].closed


@pytest.mark.parametrize("fail_at", ["http.response.start", "http.response.body"])
async def test_asgi_send_failure_always_cleans_even_before_first_yield(media, fail_at):
    manager, brain, bridges, _ = media
    sid = await new(media)
    async def tts(*args, **kwargs):
        await asyncio.Event().wait()
    brain.synthesize_tts.side_effect = tts
    response = manager.turn(sid, TurnRequest(text="hi", turn_id="broken-send"))
    async def send(message):
        if message["type"] == fail_at:
            raise OSError("connection gone")
    async def receive():
        await asyncio.Event().wait()
    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert manager.sessions[sid].active is None
    assert not manager.sessions[sid].receipts
    assert bridges[0].closed


async def test_asgi_disconnect_event_cancels_waiting_tts(media):
    manager, brain, bridges, _ = media
    sid = await new(media)
    delivered = asyncio.Event()
    async def tts(*args, **kwargs):
        await asyncio.Event().wait()
    brain.synthesize_tts.side_effect = tts
    response = manager.turn(sid, TurnRequest(text="hi", turn_id="disconnected"))
    async def send(message):
        if message["type"] == "http.response.body":
            delivered.set()
    async def receive():
        await delivered.wait()
        return {"type": "http.disconnect"}
    await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
    assert manager.sessions[sid].active is None
    assert not manager.sessions[sid].receipts
    assert bridges[0].observations[0][1]["played"] is False


async def test_receipt_transport_failure_is_still_consumed_once(media):
    _, _, bridges, client = media
    sid = await new(media)
    rid = (await rendered(media, sid))[1]["receipt_id"]
    bridges[0].confirm_spoken = AsyncMock(side_effect=RuntimeError("secret transport"))
    payload = {"receipt_id": rid, "played": True}
    first = await client.post(f"/media/sessions/{sid}/receipt", json=payload)
    assert first.status_code == 502
    assert "secret" not in first.text
    assert (await client.post(f"/media/sessions/{sid}/receipt", json=payload)).status_code == 404
    bridges[0].confirm_spoken.assert_awaited_once()


async def test_concurrent_close_interrupt_and_ack_cannot_replay_receipt(media):
    manager, _, bridges, client = media
    sid = await new(media)
    rid = (await rendered(media, sid))[1]["receipt_id"]
    await asyncio.gather(manager.interrupt(sid, "t1"), manager.close(sid),
                         client.post(f"/media/sessions/{sid}/receipt", json={"receipt_id": rid, "played": True}))
    assert len(bridges[0].observations) == 1
    assert bridges[0].closed
    assert sid not in manager.sessions


async def test_playback_cannot_ack_early_and_interrupt_after_done_settles_false(media):
    manager, brain, bridges, client = media
    sid = await new(media)
    pause = asyncio.Event()
    async def tts(*args, **kwargs):
        await pause.wait()
        return b"mp3"
    brain.synthesize_tts.side_effect = tts
    response = manager.turn(sid, TurnRequest(text="hi", turn_id="t1"))
    iterator = response.body_iterator
    await anext(iterator)
    rid = next(iter(manager.sessions[sid].receipts))
    assert (await client.post(f"/media/sessions/{sid}/receipt", json={"receipt_id": rid, "played": True})).status_code == 409
    pause.set()
    async for _ in iterator:
        pass
    assert (await manager.interrupt(sid, "t1"))["interrupted"] is True
    assert bridges[0].observations[0][1]["played"] is False
    assert (await client.post(f"/media/sessions/{sid}/receipt", json={"receipt_id": rid, "played": True})).status_code == 404


async def test_timeout_is_terminal_error_and_cleans_bridge(media):
    manager, _, bridges, _ = media
    sid = await new(media)
    manager.turn_timeout = 0.01
    bridges[0].gate = asyncio.Event()
    events = await rendered(media, sid)
    assert events == [{"type": "error", "turn_id": "t1", "error": "turn_timeout"}]
    assert bridges[0].closed
    assert manager.sessions[sid].active is None


async def test_tts_failure_never_yields_done_or_leaks_exception(media):
    manager, brain, bridges, _ = media
    sid = await new(media)
    brain.synthesize_tts.side_effect = RuntimeError("token=secret upstream details")
    events = await rendered(media, sid)
    assert events[-1]["type"] == "error"
    assert not any(e["type"] == "done" for e in events)
    assert "secret" not in json.dumps(events)
    assert bridges[0].observations[0][1]["played"] is False


async def test_close_and_idle_expiration_reclaim_pending_receipts(media, monkeypatch):
    # A fresh CI runner may have less uptime than idle_timeout. Control only the
    # media clock, keeping asyncio's real monotonic clock untouched.
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr("gateway.media_api.time", SimpleNamespace(monotonic=lambda: clock.now))
    manager, _, bridges, client = media
    sid = await new(media)
    await rendered(media, sid)
    clock.now = manager.sessions[sid].touched + manager.idle_timeout
    await manager.reap()
    assert sid in manager.sessions
    assert not bridges[0].closed and not bridges[0].observations
    clock.now += 1
    await manager.reap()
    assert sid not in manager.sessions
    assert bridges[0].closed
    assert bridges[0].observations[0][1]["played"] is False
    assert (await client.post(f"/media/sessions/{sid}/close", json={})).json() == {"ok": True}


async def test_transcribe_is_pcm_only_and_never_decides(media):
    _, brain, bridges, client = media
    sid = await new(media)
    payload = {"audio_base64": base64.b64encode(b"\x00\x00" * 160).decode(),
               "format": "pcm16", "sample_rate": 16000, "channels": 1}
    response = await client.post(f"/media/sessions/{sid}/transcribe", json=payload)
    assert response.json() == {"text": "识别文本"}
    brain._transcribe_audio.assert_awaited_once()
    assert not bridges[0].calls
    assert not brain.synthesize_tts.called
    for changed in ({"sample_rate": 48000}, {"channels": 2}, {"format": "mp3"},
                    {"audio_base64": "!bad!"}, {"audio_base64": "AA=="}):
        response = await client.post(f"/media/sessions/{sid}/transcribe", json={**payload, **changed})
        assert response.status_code == 400


async def test_identity_failure_and_capacity_fail_closed(media):
    manager, brain, bridges, client = media
    brain._resolve_runtime_identity.side_effect = RuntimeError("secret")
    assert (await client.post("/media/sessions", json={"body_id": "joi"})).status_code == 502
    assert manager.sessions == {}
    assert bridges[0].closed
    manager.max_sessions = 0
    assert (await client.post("/media/sessions", json={"body_id": "joi"})).status_code == 503


async def test_health_identifies_media_api_without_runtime_sessions_or_model_calls(media, monkeypatch):
    manager, brain, bridges, client = media
    for _ in range(3):
        result = await client.get("/media/health")
        assert result.status_code == 200
        data = result.json()
        assert data["service"] == "gateway-media"
        assert data["protocol"] == "ndjson-v1"
        assert data["ready"] is True
        assert data["readiness_scope"] == "configuration_only"
        assert data["dependencies"]["runtime"]["reachable"] is None
        assert data["end_to_end_verified"] is False
    assert manager.sessions == {}
    assert bridges == []
    brain._resolve_runtime_identity.assert_not_awaited()
    brain.synthesize_tts.assert_not_awaited()
    brain._transcribe_audio.assert_not_awaited()
    assert (await client.get("/media/health", headers={"Authorization": "Bearer wrong"})).status_code == 401
    monkeypatch.setattr(settings, "soulforge_brand_id", "")
    assert (await client.get("/media/health")).json()["ready"] is False
    monkeypatch.setattr(settings, "gateway_api_token", "")
    assert (await client.get("/media/health")).status_code == 503
