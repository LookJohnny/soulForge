from contextlib import asynccontextmanager
from http import HTTPStatus
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiohttp import web
import pytest

from studio import gateway_proxy
from scripts import gateway_public, tavus_setup


def request(origin="http://127.0.0.1:8899", remote="127.0.0.1", agent="joi"):
    return SimpleNamespace(
        remote=remote,
        scheme="http",
        host="127.0.0.1:8899",
        headers={"Origin": origin},
        json=AsyncMock(return_value={"agent_id": agent}),
    )


@asynccontextmanager
async def context(value):
    yield value


async def messages(*values):
    for value in values:
        yield value


@pytest.mark.parametrize(
    "origin,remote",
    [
        ("https://evil.example", "127.0.0.1"),
        ("http://127.0.0.1:8899", "192.168.1.2"),
        ("", "127.0.0.1"),
    ],
)
def test_only_same_origin_local_browser_controls_are_allowed(origin, remote):
    with pytest.raises(web.HTTPForbidden):
        gateway_proxy.require_local_browser(request(origin, remote))


@pytest.mark.parametrize(
    "url",
    [
        "https://outside.example",
        "http://token@localhost:8081",
        "http://localhost:8081/?redirect=x",
    ],
)
def test_server_token_cannot_be_sent_to_external_or_credentialed_urls(url):
    with pytest.raises(ValueError):
        gateway_proxy.local_url(url)


@pytest.mark.asyncio
async def test_missing_token_blocks_switch_before_runtime_reload(monkeypatch):
    connect = Mock(side_effect=AssertionError("must not touch runtime"))
    monkeypatch.setattr(gateway_proxy.websockets, "connect", connect)
    response = await gateway_proxy.switch_agent(
        request(),
        gateway_url="http://127.0.0.1:8081",
        token="",
        runtime_url="ws://127.0.0.1:8765",
        agent_ids={"joi"},
    )
    assert response.status == 503
    connect.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(200, 200), (401, 502), (503, 502)])
async def test_switch_forwards_token_server_side_and_reports_rejection(
    monkeypatch, status, expected
):
    class FakeSocket:
        send = AsyncMock()

        def __aiter__(self):
            return messages('{"type":"tick"}', '{"type":"personas","agents":["joi"]}')

    ws = FakeSocket()
    monkeypatch.setattr(
        gateway_proxy.websockets, "connect", lambda *a, **kw: context(ws)
    )
    upstream = SimpleNamespace(
        status=status, json=AsyncMock(return_value={"ok": True, "agent_id": "joi"})
    )
    client = SimpleNamespace(post=Mock(return_value=context(upstream)))
    monkeypatch.setattr(
        gateway_proxy.aiohttp, "ClientSession", lambda **kw: context(client)
    )
    result = await gateway_proxy.switch_agent(
        request(),
        gateway_url="http://127.0.0.1:8081",
        token="private-token",
        runtime_url="ws://127.0.0.1:8765/body",
        agent_ids={"joi"},
    )
    assert result.status == expected
    assert client.post.call_args.kwargs["headers"] == {
        "Authorization": "Bearer private-token"
    }
    assert b"private-token" not in result.body


@pytest.mark.asyncio
async def test_provider_health_unreachable_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(
        gateway_proxy.aiohttp, "ClientSession", Mock(side_effect=OSError("offline"))
    )
    result = await gateway_proxy.provider_health("ws://127.0.0.1:8765/body")
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,expected",
    [
        ('{"status":"degraded","ready":true}', "degraded"),
        ("not valid JSON", "unavailable"),
        ('{"ready":true}', "unavailable"),
    ],
)
async def test_runtime_websockets_health_accepts_json_with_duplicate_content_type(
    body, expected
):
    async def http_response(connection, _request):
        response = connection.respond(HTTPStatus.OK, body)
        # Reproduce the Runtime response: websockets Headers append on assignment.
        response.headers["Content-Type"] = "application/json"
        return response

    async def handler(_socket):
        raise AssertionError("Health reads must never establish a WebSocket")

    async with gateway_proxy.websockets.serve(
        handler,
        "127.0.0.1",
        0,
        process_request=http_response,
    ) as server:
        port = server.sockets[0].getsockname()[1]
        result = await gateway_proxy._runtime_health(f"ws://127.0.0.1:{port}/body")
        assert result["status"] == expected


def runtime_health():
    return {
        "status": "ok",
        "ready": True,
        "fallback_active": False,
        "fallback_count": 0,
        "providers": [
            {
                "provider": "ai-core",
                "model": "central",
                "status": "ok",
                "calls": 2,
                "successes": 2,
                "failures": 0,
            }
        ],
        "memory": {
            "persistent": True,
            "ready": True,
            "pending_writes": 0,
            "writes_completed": 1,
            "last_error": None,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "core_status,expected",
    [
        ("ok", "ok"),
        ("unknown", "unknown"),
        ("degraded", "degraded"),
        ("unavailable", "degraded"),
    ],
)
async def test_provider_health_reports_both_services_without_upgrading_unknown(
    monkeypatch, core_status, expected
):
    monkeypatch.setattr(
        gateway_proxy, "_runtime_health", AsyncMock(return_value=runtime_health())
    )
    core = {"status": core_status}
    if core_status != "unavailable":
        core["providers"] = [
            {
                "kind": "llm",
                "provider": "deepseek",
                "model": "chat",
                "status": core_status,
                "success_count": 2,
                "failure_count": 1,
            }
        ]
    monkeypatch.setattr(gateway_proxy, "_ai_core_health", AsyncMock(return_value=core))
    result = await gateway_proxy.provider_health("ws://127.0.0.1:8765/body")
    assert result["status"] == expected
    assert result["ready"] is True
    assert {p["service"] for p in result["providers"]} == {"runtime", "ai-core"}
    assert result["providers"][1]["status"] == core_status
    if core_status != "unavailable":
        assert result["providers"][1]["provider"] == "ai-core · llm · deepseek"
        assert result["providers"][1]["calls"] == 3
        assert result["providers"][1]["successes"] == 2
        assert result["providers"][1]["failures"] == 1


@pytest.mark.asyncio
async def test_runtime_disconnect_is_unavailable_even_when_ai_core_is_healthy(
    monkeypatch,
):
    monkeypatch.setattr(
        gateway_proxy,
        "_runtime_health",
        AsyncMock(return_value={"status": "unavailable"}),
    )
    monkeypatch.setattr(
        gateway_proxy,
        "_ai_core_health",
        AsyncMock(
            return_value={
                "status": "ok",
                "providers": [{"kind": "llm", "provider": "deepseek", "status": "ok"}],
            }
        ),
    )
    result = await gateway_proxy.provider_health("ws://127.0.0.1:8765/body")
    assert result["status"] == "unavailable"
    assert result["ready"] is False
    assert result["providers"][0]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_provider_health_preserves_fallback_without_inferring_from_history(
    monkeypatch,
):
    runtime = runtime_health()
    runtime["fallback_active"] = True
    runtime["fallback_count"] = 3
    monkeypatch.setattr(
        gateway_proxy, "_runtime_health", AsyncMock(return_value=runtime)
    )
    monkeypatch.setattr(
        gateway_proxy,
        "_ai_core_health",
        AsyncMock(
            return_value={
                "status": "ok",
                "providers": [
                    {
                        "kind": "tts",
                        "provider": "edge",
                        "status": "ok",
                        "success_count": 4,
                        "failure_count": 1,
                    }
                ],
            }
        ),
    )
    result = await gateway_proxy.provider_health("ws://127.0.0.1:8765/body")
    assert result["status"] == "degraded" and result["fallback_active"] is True
    assert result["fallback_count"] == 3
    assert result["providers"][1]["fallback_active"] is False
    assert result["providers"][1]["fallback_count"] is None


@pytest.mark.asyncio
async def test_health_credentials_stay_on_fixed_local_request_and_are_never_redirected(
    monkeypatch,
):
    upstream = SimpleNamespace(
        status=200, json=AsyncMock(return_value={"status": "unknown", "providers": []})
    )
    client = SimpleNamespace(get=Mock(return_value=context(upstream)))
    factory = Mock(return_value=context(client))
    monkeypatch.setattr(gateway_proxy.aiohttp, "ClientSession", factory)
    result = await gateway_proxy._ai_core_health(
        "http://127.0.0.1:8100", "private-token", "brand-id"
    )
    assert result["status"] == "unknown"
    assert client.get.call_args.args == ("http://127.0.0.1:8100/health/providers",)
    assert client.get.call_args.kwargs["headers"] == {
        "X-Service-Token": "private-token",
        "X-Brand-Id": "brand-id",
    }
    assert client.get.call_args.kwargs["allow_redirects"] is False
    assert factory.call_args.kwargs["trust_env"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,token,brand",
    [
        ("http://evil.example", "secret", "brand"),
        ("http://127.0.0.1:8100", "", "brand"),
        ("http://127.0.0.1:8100", "secret", ""),
    ],
)
async def test_ai_core_health_missing_credentials_or_external_url_fails_closed(
    monkeypatch, url, token, brand
):
    read = AsyncMock(side_effect=AssertionError("must not make an HTTP request"))
    monkeypatch.setattr(gateway_proxy, "_read_health", read)
    assert await gateway_proxy._ai_core_health(url, token, brand) == {
        "status": "unavailable"
    }
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_aggregated_health_exposes_only_safe_fields_and_sanitized_failures(
    monkeypatch,
):
    runtime = runtime_health()
    runtime["memory"]["last_error"] = (
        "private-token failed at http://localhost:8100/memory"
    )
    runtime["private_url"] = "http://localhost:8100?token=private-token"
    monkeypatch.setattr(
        gateway_proxy, "_runtime_health", AsyncMock(return_value=runtime)
    )
    monkeypatch.setattr(
        gateway_proxy,
        "_ai_core_health",
        AsyncMock(
            return_value={
                "status": "degraded",
                "token": "private-token",
                "providers": [
                    {
                        "kind": "asr",
                        "provider": "whisper",
                        "status": "degraded",
                        "model": "private-token",
                        "last_error": {
                            "type": "HTTPStatusError",
                            "status_code": 429,
                            "detail": "http://localhost:8100 secret private-token",
                        },
                    },
                    {
                        "kind": "tts",
                        "provider": "edge",
                        "status": "unknown",
                        "last_error": "Error http://localhost:8100?token=private-token",
                    },
                ],
            }
        ),
    )
    result = await gateway_proxy.provider_health(
        "ws://127.0.0.1:8765/body", service_token="private-token"
    )
    serialized = json.dumps(result)
    assert "private-token" not in serialized
    assert "http://" not in serialized
    assert "private_url" not in result and "token" not in result
    assert result["providers"][1]["last_error"] == "HTTPStatusError (HTTP 429)"
    assert result["providers"][2]["calls"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("memory", [None, {}, {"persistent": True, "ready": False}])
async def test_missing_or_unready_memory_never_becomes_healthy(monkeypatch, memory):
    runtime = runtime_health()
    runtime["memory"] = memory
    monkeypatch.setattr(
        gateway_proxy, "_runtime_health", AsyncMock(return_value=runtime)
    )
    monkeypatch.setattr(
        gateway_proxy,
        "_ai_core_health",
        AsyncMock(
            return_value={
                "status": "ok",
                "providers": [{"status": "ok", "provider": "deepseek"}],
            }
        ),
    )
    assert (await gateway_proxy.provider_health("ws://127.0.0.1:8765/body"))[
        "status"
    ] == "unknown"


def test_public_relay_does_not_expose_ws_or_admin():
    app = gateway_public.build_app("http://127.0.0.1:8081")
    paths = {route.resource.canonical for route in app.router.routes()}
    assert paths == {"/health", "/v1/chat/completions"}


def test_tavus_configuration_uses_protected_bridge_without_speculation(monkeypatch):
    monkeypatch.setattr(
        tavus_setup,
        "setting",
        lambda name: {
            "TAVUS_PUBLIC_BASE_URL": "https://face.example",
            "GATEWAY_API_TOKEN": "private-token",
        }.get(name, ""),
    )
    config = tavus_setup.connection_config()
    assert config == {
        "model": "soulforge-brain",
        "base_url": "https://face.example/v1",
        "api_key": "private-token",
        "speculative_inference": False,
    }


def test_tavus_missing_gateway_token_fails_before_paid_calls(monkeypatch):
    monkeypatch.setattr(
        tavus_setup,
        "setting",
        lambda name: "https://face.example" if name == "TAVUS_PUBLIC_BASE_URL" else "",
    )
    monkeypatch.setattr(
        tavus_setup, "list_faces", Mock(side_effect=AssertionError("no API calls"))
    )
    with pytest.raises(SystemExit, match="GATEWAY_API_TOKEN"):
        tavus_setup.cmd_up()
