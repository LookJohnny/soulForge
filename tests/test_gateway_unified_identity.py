"""Resolve and route one cognition request per voice turn, without live services."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from gateway.config import settings
from gateway.pipeline import character_bridge
from gateway.pipeline.orchestrator import PipelineOrchestrator
from gateway.session import Session


@pytest.fixture
def unified(monkeypatch):
    brand, user = str(uuid4()), str(uuid4())
    characters = {"kai": str(uuid4()), "luna": str(uuid4())}
    for key, value in {
        "soulforge_brand_id": brand,
        "soulforge_user_id": user,
        "service_token": "test-service-token",
        "character_runtime_url": "ws://unused.invalid",
        "character_runtime_agent": "kai",
        "character_runtime_voice_device_id": "",
    }.items():
        monkeypatch.setattr(settings, key, value)
    bridges, requests = [], []

    class Bridge:
        def __init__(self, *, body_id, timeout_s, autonomous_speech):
            self.body_id = body_id
            self.agent_id = settings.character_runtime_agent
            self.autonomous_speech = autonomous_speech
            self.process_utterance = AsyncMock(
                return_value={
                    "text": "我记得。",
                    "commands": [{"command_id": "speech-1", "dialogue": "我记得。"}],
                }
            )
            self.process_event = AsyncMock(
                return_value={
                    "text": "我收到这个拥抱啦。",
                    "commands": [
                        {"command_id": "touch-speech", "dialogue": "我收到这个拥抱啦。"}
                    ],
                }
            )
            self.confirm_spoken = AsyncMock()
            self.close = AsyncMock()
            bridges.append(self)

    monkeypatch.setattr(character_bridge, "CharacterBridge", Bridge)

    async def resolve(request):
        assert request.url.path == "/runtime/resolve", (
            "legacy chat or duplicate cognition call"
        )
        assert request.headers["X-Service-Token"] == "test-service-token"
        assert request.headers["X-Brand-Id"] == brand
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["user_id"] == user
        return httpx.Response(
            200,
            json={
                "identity": {
                    **payload,
                    "character_id": characters[payload["agent_id"]],
                }
            },
        )

    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orchestrator.client = httpx.AsyncClient(
        base_url="http://unused.invalid",
        transport=httpx.MockTransport(resolve),
        headers={"X-Service-Token": "test-service-token"},
    )
    orchestrator._pending_playback = {}
    return SimpleNamespace(
        orchestrator=orchestrator,
        bridges=bridges,
        requests=requests,
        brand=brand,
        user=user,
        characters=characters,
    )


@pytest.mark.asyncio
async def test_two_sessions_share_durable_identity_but_not_voice_body_and_resolve_once(
    unified,
):
    first, second = (
        Session("session-one", "body-one"),
        Session("session-two", "body-two"),
    )
    orchestrator = unified.orchestrator
    bridge_one, _ = await orchestrator._runtime_decision(first, "我叫阿明")
    bridge_again, _ = await orchestrator._runtime_decision(first, "记得吗")
    bridge_two, _ = await orchestrator._runtime_decision(second, "你还记得吗")
    assert bridge_one is bridge_again and bridge_one is not bridge_two
    assert bridge_one.body_id != bridge_two.body_id
    assert bridge_one.process_utterance.await_count == 2
    assert bridge_two.process_utterance.await_count == 1
    assert len(unified.requests) == 2
    assert first.end_user_id == second.end_user_id == unified.user
    assert first.character_id == second.character_id == unified.characters["kai"]
    for bridge in unified.bridges:
        for call in bridge.process_utterance.await_args_list:
            identity = call.kwargs["payload"]["identity"]
            assert identity["body_id"] == bridge.body_id
            assert identity["agent_id"] == bridge.agent_id
            assert identity["user_id"] == unified.user
    await orchestrator.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_field", ["end_user_id", "brand_id"])
async def test_bound_foreign_session_is_rejected_before_any_cognition(
    unified, foreign_field
):
    session = Session("foreign", "body", **{foreign_field: str(uuid4())})
    with pytest.raises(PermissionError):
        await unified.orchestrator._runtime_decision(session, "不要写入其他人的记忆")
    assert all(bridge.process_utterance.await_count == 0 for bridge in unified.bridges)
    await unified.orchestrator.client.aclose()


@pytest.mark.asyncio
async def test_external_face_resolves_once_decides_once_and_never_claims_playback(
    unified,
):
    result = await unified.orchestrator.process_external_utterance(
        "跨身体还记得我吗",
        body_id="external-video",
        session_id="external-session",
    )
    (bridge,) = unified.bridges
    assert result["text"] == "我记得。"
    assert len(unified.requests) == bridge.process_utterance.await_count == 1
    assert not bridge.autonomous_speech
    identity = bridge.process_utterance.await_args.kwargs["payload"]["identity"]
    assert identity["user_id"] == unified.user
    assert identity["character_id"] == unified.characters["kai"]
    assert identity["session_id"] == "external-session"
    assert identity["body_id"] == bridge.body_id
    assert bridge.confirm_spoken.await_args.kwargs["played"] is False
    bridge.close.assert_awaited_once()
    await unified.orchestrator.client.aclose()


@pytest.mark.asyncio
async def test_completed_turn_switch_rebinds_character_without_changing_user(
    unified, monkeypatch
):
    orchestrator = unified.orchestrator
    session = Session("ongoing", "body")
    old, _ = await orchestrator._runtime_decision(session, "你好凯")
    await orchestrator.reset_runtime_bridges()
    monkeypatch.setattr(settings, "character_runtime_agent", "luna")
    new, _ = await orchestrator._runtime_decision(session, "你好露娜")
    old.close.assert_awaited_once()
    assert old is not new and new.agent_id == "luna"
    assert session.end_user_id == unified.user
    assert session.character_id == unified.characters["luna"]
    identity = new.process_utterance.await_args.kwargs["payload"]["identity"]
    assert identity["agent_id"] == "luna" and identity["body_id"] == new.body_id
    await orchestrator.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [False, True])
async def test_character_switch_during_resolve_never_sends_identity_to_a_different_body(
    unified,
    monkeypatch,
    external,
):
    client = unified.orchestrator.client
    original = client._transport.handler

    async def switching_resolve(request):
        response = await original(request)
        monkeypatch.setattr(settings, "character_runtime_agent", "luna")
        return response

    client._transport.handler = switching_resolve
    if external:
        await unified.orchestrator.process_external_utterance(
            "你好", body_id="video", session_id="one"
        )
        bridge = unified.bridges[0]
    else:
        bridge, _ = await unified.orchestrator._runtime_decision(
            Session("one", "body"), "你好"
        )
    sent = bridge.process_utterance.await_args.kwargs["payload"]["identity"]
    assert sent["agent_id"] == bridge.agent_id == "kai"
    assert sent["body_id"] == bridge.body_id
    assert sent["character_id"] == unified.characters["kai"]
    await client.aclose()


@pytest.mark.asyncio
async def test_cached_binding_still_rejects_a_changed_user(unified):
    session = Session("one", "body")
    bridge, _ = await unified.orchestrator._runtime_decision(session, "你好")
    session.end_user_id = str(uuid4())
    with pytest.raises(PermissionError):
        await unified.orchestrator._runtime_decision(session, "其他用户")
    assert bridge.process_utterance.await_count == 1
    await unified.orchestrator.client.aclose()


@pytest.mark.asyncio
async def test_touch_uses_one_environment_decision_and_retains_playback_receipt(
    unified,
):
    orchestrator = unified.orchestrator
    orchestrator.synthesize_tts = AsyncMock(return_value=b"audio")
    session = Session("touch-session", "device")
    result = await orchestrator.process_touch(
        session,
        {
            "gesture": "hug",
            "pressure": 0.3,
            "identity": {"user_id": str(uuid4())},
            "text": "我叫伪造的用户",
        },
    )
    (bridge,) = unified.bridges
    bridge.process_utterance.assert_not_awaited()
    bridge.process_event.assert_awaited_once()
    call = bridge.process_event.await_args
    assert call.args == ("environment",) and call.kwargs["source"] == "touch_sensor"
    assert call.kwargs["payload"]["touch"] == {"gesture": "hug", "pressure": 0.3}
    assert call.kwargs["payload"]["identity"]["user_id"] == unified.user
    assert orchestrator.synthesize_tts.await_args.args[1] == unified.characters["kai"]
    assert result["audio_data"] == b"audio" and result["playback_receipt"]
    bridge.confirm_spoken.assert_not_awaited()
    await orchestrator.confirm_playback(result["playback_receipt"], played=True)
    assert bridge.confirm_spoken.await_args.kwargs["played"] is True
    await orchestrator.client.aclose()


@pytest.mark.asyncio
async def test_touch_silent_decision_needs_no_tts_or_fake_spoken_receipt(unified):
    orchestrator = unified.orchestrator
    orchestrator.synthesize_tts = AsyncMock()
    session = Session("touch-silent", "device")
    bridge = orchestrator._runtime_bridge(session)
    bridge.process_event.return_value = {"text": "", "commands": []}
    result = await orchestrator.process_touch(session, {"gesture": "pat"})
    assert result["text"] == "" and result["playback_receipt"] is None
    orchestrator.synthesize_tts.assert_not_awaited()
    await orchestrator.client.aclose()


@pytest.mark.asyncio
async def test_touch_tts_failure_marks_runtime_speech_interrupted(unified):
    orchestrator = unified.orchestrator
    orchestrator.synthesize_tts = AsyncMock(side_effect=RuntimeError("tts offline"))
    with pytest.raises(RuntimeError, match="tts offline"):
        await orchestrator.process_touch(
            Session("touch-failed", "device"), {"gesture": "hug"}
        )
    (bridge,) = unified.bridges
    assert bridge.confirm_spoken.await_args.kwargs["played"] is False
    assert orchestrator._pending_playback == {}
    await orchestrator.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["idle", "silence", "touch", "sensor_touch", "timer", "reflection"]
)
async def test_normal_reaction_cannot_start_an_independent_plan_in_unified_mode(
    unified, kind
):
    result = await unified.orchestrator.process_reaction_event(
        Session("one", "body"), kind
    )
    reaction = result["reaction"]
    assert not reaction["should_react"] and reaction["speech"] is None
    assert reaction["actions"] == [] and reaction["plan_patch"] == {}
    assert not unified.requests and not unified.bridges
    await unified.orchestrator.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["battery_low", "motor_error", "barge_in"])
async def test_unified_safety_reaction_keeps_stop_constraints_but_no_speech_or_motion(
    unified, kind
):
    client = unified.orchestrator.client
    resolve = client._transport.handler
    previews = []

    async def safe_api(request):
        if request.url.path == "/runtime/resolve":
            return await resolve(request)
        if request.url.path == "/memory/reaction":
            return httpx.Response(
                200,
                json={
                    "should_react": True,
                    "speech": {"text": "independent speech"},
                    "actions": [
                        {"channel": "audio", "command": "stop"},
                        {"channel": "motion", "command": "wave"},
                    ],
                    "plan_patch": {"resume_after_user_turn": True, "new_plan": "walk"},
                },
            )
        assert request.url.path == "/actions/preview"
        previews.append(json.loads(request.content))
        return httpx.Response(200, json={"commands": []})

    client._transport.handler = safe_api
    result = await unified.orchestrator.process_reaction_event(
        Session("safe-session", "device"),
        kind,
        event={"battery_percent": 4, "channel": "motor"},
    )
    reaction = result["reaction"]
    assert reaction["speech"] is None
    assert reaction["actions"] == [{"channel": "audio", "command": "stop"}]
    assert "resume_after_user_turn" not in reaction["plan_patch"]
    assert "new_plan" not in reaction["plan_patch"]
    assert previews[0]["action_plan"]["speech"] is None
    assert previews[0]["action_plan"]["actions"] == reaction["actions"]
    assert all(bridge.process_event.await_count == 0 for bridge in unified.bridges)
    await client.aclose()
