"""Protected inference/control routes never reach the brain without credentials."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from gateway.config import settings


@pytest.fixture
def gateway_app(monkeypatch):
    # Importing the real app must never start a configured physical face.
    monkeypatch.setattr(settings, "face_host", "")
    module = importlib.import_module("gateway.main")
    orchestrator = SimpleNamespace(process_external_utterance=AsyncMock(return_value={"text": "来自唯一大脑"}))
    monkeypatch.setattr(module, "ws_server", SimpleNamespace(orchestrator=orchestrator))
    monkeypatch.setattr(settings, "gateway_api_token", "test-private-gateway-token")
    monkeypatch.setattr(settings, "character_runtime_url", "ws://127.0.0.1:8765")
    return module.app, orchestrator


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/admin/runtime-agent"])
@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic anything"])
async def test_missing_or_invalid_auth_never_calls_brain(gateway_app, path, authorization):
    app, brain = gateway_app
    headers = {"Authorization": authorization} if authorization else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, headers=headers, json={"messages": [], "agent_id": "joi"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    brain.process_external_utterance.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfigured_secret_disables_write_routes_but_not_health(gateway_app, monkeypatch):
    app, brain = gateway_app
    monkeypatch.setattr(settings, "gateway_api_token", "")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/v1/chat/completions", "/admin/runtime-agent"):
            response = await client.post(path, json={"messages": [], "agent_id": "joi"})
            assert response.status_code == 503
        assert (await client.get("/health")).status_code == 200
    brain.process_external_utterance.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_face_submits_once_without_playback_claim(gateway_app):
    app, brain = gateway_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-private-gateway-token"},
            json={"user": "conversation-A", "messages": [{"role": "user", "content": "你好"}]})
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "来自唯一大脑"
    brain.process_external_utterance.assert_awaited_once_with("你好", body_id="tavus-face", session_id="conversation-A")


@pytest.mark.asyncio
async def test_external_brain_failure_is_not_a_successful_placeholder(gateway_app):
    app, brain = gateway_app
    brain.process_external_utterance.side_effect = RuntimeError("provider failed")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-private-gateway-token"},
            json={"stream": True, "messages": [{"role": "user", "content": "你好"}]})
    assert response.status_code == 502
    assert "嗯，我在" not in response.text
