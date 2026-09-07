from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import Mock

from aiohttp import web
import pytest

from studio import selfhost_proxy

CLIENT = "00000000-0000-4000-8000-000000000001"
SESSION = "00000000-0000-4000-8000-000000000002"
OFFER = {"client_id": CLIENT, "type": "offer", "sdp": "v=0\r\no=browser"}
ANSWER = {"session_id": SESSION, "type": "answer", "sdp": "v=0\r\no=server"}


class Content:
    def __init__(self, value):
        self.value = value if isinstance(value, bytes) else json.dumps(value).encode()

    async def iter_chunked(self, size):
        # Deliberately split valid JSON over several asynchronous reads.
        for offset in range(0, len(self.value), min(size, 29)):
            yield self.value[offset : offset + min(size, 29)]


def request(
    path="sessions",
    method="POST",
    body=None,
    origin="http://127.0.0.1:8899",
    remote="127.0.0.1",
):
    result = SimpleNamespace(
        method=method,
        remote=remote,
        scheme="http",
        host="127.0.0.1:8899",
        headers={"Origin": origin},
        match_info={"path": path},
        query_string="",
        content=Content(OFFER if body is None else body),
    )
    result.clone = lambda **kwargs: SimpleNamespace(**{**vars(result), **kwargs})
    return result


def setting(key):
    return {
        "SELFHOST_MEDIA_URL": "http://127.0.0.1:8902",
        "SELFHOST_MEDIA_TOKEN": "private-token",
    }.get(key, "")


@asynccontextmanager
async def context(value):
    yield value


def upstream(monkeypatch, body=None, status=200):
    response = SimpleNamespace(
        status=status, content=Content(ANSWER if body is None else body)
    )
    client = SimpleNamespace(request=Mock(return_value=context(response)))
    factory = Mock(return_value=context(client))
    monkeypatch.setattr(selfhost_proxy.aiohttp, "ClientSession", factory)
    return client, factory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin,remote",
    [
        ("https://evil.example", "127.0.0.1"),
        ("http://127.0.0.1:8899", "192.168.1.2"),
        ("", "127.0.0.1"),
    ],
)
async def test_remote_and_cross_origin_requests_never_reach_media_service(
    monkeypatch, origin, remote
):
    _, factory = upstream(monkeypatch)
    with pytest.raises(web.HTTPForbidden):
        await selfhost_proxy.proxy(
            request(origin=origin, remote=remote), setting=setting
        )
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_same_origin_health_fetch_without_origin_uses_browser_metadata(
    monkeypatch,
):
    upstream(
        monkeypatch,
        {
            "ready": True,
            "status": "ready",
            "token": "private-token",
            "url": "http://gpu",
        },
    )
    req = request("health", method="GET")
    req.headers = {
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    result = await selfhost_proxy.proxy(req, setting=setting)
    assert result.status == 200
    assert json.loads(result.body) == {"ready": True, "status": "ready"}
    req.headers["Sec-Fetch-Site"] = "same-site"
    with pytest.raises(web.HTTPForbidden):
        await selfhost_proxy.proxy(req, setting=setting)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example",
        "http://secret@localhost:8902",
        "http://localhost:8902?token=x",
        "http://localhost:8902/other",
    ],
)
async def test_server_credentials_cannot_be_redirected_or_forwarded_to_arbitrary_upstream(
    monkeypatch, url
):
    _, factory = upstream(monkeypatch)
    result = await selfhost_proxy.proxy(
        request(), setting=lambda key: url if key == "SELFHOST_MEDIA_URL" else "secret"
    )
    assert result.status == 503
    assert json.loads(result.body)["status"] == "unconfigured"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_missing_server_token_is_explicitly_unconfigured_without_probe(
    monkeypatch,
):
    _, factory = upstream(monkeypatch)
    result = await selfhost_proxy.proxy(
        request("health", method="GET"), setting=lambda key: ""
    )
    assert result.status == 503 and "GPU" in json.loads(result.body)["error"]
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,method",
    [
        ("sessions", "GET"),
        ("health", "POST"),
        ("sessions/../../health", "POST"),
        (f"sessions/{SESSION}/credentials", "POST"),
        ("sessions/------------------------------------/close", "POST"),
    ],
)
async def test_only_exact_operations_are_allowed(monkeypatch, path, method):
    _, factory = upstream(monkeypatch)
    result = await selfhost_proxy.proxy(request(path, method=method), setting=setting)
    assert result.status == 404
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_browser_query_cannot_change_fixed_media_target(monkeypatch):
    _, factory = upstream(monkeypatch)
    req = request()
    req.query_string = "url=http://evil.example"
    assert (await selfhost_proxy.proxy(req, setting=setting)).status == 404
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        [],
        {**OFFER, "url": "http://evil.example"},
        {**OFFER, "client_id": "not-uuid"},
        {**OFFER, "type": "answer"},
        {**OFFER, "sdp": "invalid"},
        {**OFFER, "sdp": "v=0" + "x" * 65536},
    ],
)
async def test_invalid_or_extra_offer_fields_are_not_forwarded(monkeypatch, body):
    _, factory = upstream(monkeypatch)
    assert (
        await selfhost_proxy.proxy(request(body=body), setting=setting)
    ).status == 400
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_chunked_offer_and_answer_forward_only_fixed_contract_and_server_auth(
    monkeypatch,
):
    client, factory = upstream(
        monkeypatch, {**ANSWER, "token": "private-token", "url": "http://gpu"}
    )
    result = await selfhost_proxy.proxy(request(), setting=setting)
    assert result.status == 200 and json.loads(result.body) == ANSWER
    assert result.headers["Cache-Control"] == "no-store"
    factory.assert_called_once_with(trust_env=False)
    args, kwargs = client.request.call_args
    assert args == ("POST", "http://127.0.0.1:8902/sessions")
    assert kwargs["headers"] == {"Authorization": "Bearer private-token"}
    assert kwargs["json"] == OFFER and kwargs["allow_redirects"] is False
    assert b"private-token" not in result.body


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["turn", "interrupt", "close"])
async def test_mutations_preserve_client_ownership_and_filter_provider_details(
    monkeypatch, operation
):
    client, _ = upstream(
        monkeypatch, {"ok": True, "turn_id": "turn_1", "epoch": 7, "token": "secret"}
    )
    body = {"client_id": CLIENT, **({"text": " hello "} if operation == "turn" else {})}
    result = await selfhost_proxy.proxy(
        request(f"sessions/{SESSION}/{operation}", body=body), setting=setting
    )
    assert json.loads(result.body) == {"ok": True, "turn_id": "turn_1", "epoch": 7}
    forwarded = client.request.call_args.kwargs["json"]
    assert forwarded["client_id"] == CLIENT
    if operation == "turn":
        assert forwarded["text"] == "hello"


@pytest.mark.asyncio
async def test_lost_offer_cleanup_can_only_target_requesting_client(monkeypatch):
    client, _ = upstream(monkeypatch, {"ok": True})
    result = await selfhost_proxy.proxy(
        request("sessions/close-owned", body={"client_id": CLIENT}), setting=setting
    )
    assert result.status == 200
    assert client.request.call_args.args == (
        "POST",
        "http://127.0.0.1:8902/sessions/close-owned",
    )
    assert client.request.call_args.kwargs["json"] == {"client_id": CLIENT}
    client.request.reset_mock()
    invalid = await selfhost_proxy.proxy(
        request(
            "sessions/close-owned", body={"client_id": CLIENT, "session_id": SESSION}
        ),
        setting=setting,
    )
    assert invalid.status == 400
    client.request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected", [(401, 502), (302, 502), (409, 409), (503, 503)]
)
async def test_upstream_errors_are_sanitized_and_never_claim_success(
    monkeypatch, status, expected
):
    upstream(monkeypatch, {"error": "private-token at http://gpu"}, status=status)
    result = await selfhost_proxy.proxy(request(), setting=setting)
    assert result.status == expected
    assert b"private-token" not in result.body and b"http://" not in result.body
    assert "error" in json.loads(result.body)


@pytest.mark.asyncio
async def test_semantic_failure_on_200_and_oversized_responses_fail_closed(monkeypatch):
    for data in [
        {"ok": False, "error": "secret"},
        b"x" * (selfhost_proxy.MAX_BODY + 1),
    ]:
        upstream(monkeypatch, data)
        result = await selfhost_proxy.proxy(
            request(f"sessions/{SESSION}/close", body={"client_id": CLIENT}),
            setting=setting,
        )
        assert result.status == 503
        assert b"secret" not in result.body


@pytest.mark.asyncio
async def test_oversized_request_is_rejected_before_upstream(monkeypatch):
    _, factory = upstream(monkeypatch)
    result = await selfhost_proxy.proxy(
        request(body=b"x" * (selfhost_proxy.MAX_BODY + 1)), setting=setting
    )
    assert result.status == 413
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_configured_health_does_not_invent_gpu_readiness(monkeypatch):
    upstream(monkeypatch, {"configured": True, "status": "ok", "ready": "true"})
    result = await selfhost_proxy.proxy(
        request("health", method="GET"), setting=setting
    )
    assert json.loads(result.body)["ready"] is False


@pytest.mark.asyncio
async def test_health_keeps_readiness_scope_without_exposing_upstream_configuration(
    monkeypatch,
):
    upstream(
        monkeypatch,
        {
            "ready": True,
            "status": "ready",
            "readiness_scope": "worker_loaded_and_brain_route_configured",
            "end_to_end_verified": False,
            "brain": {
                "ready": True,
                "configured": True,
                "readiness_scope": "config-only",
                "end_to_end_verified": False,
                "url": "http://brain",
                "token": "secret",
                "dependencies": {
                    "runtime": {
                        "configured": True,
                        "reachable": None,
                        "url": "http://runtime",
                    },
                    "asr": {"configured": True},
                    "secret": {"configured": True},
                },
            },
            "worker": {"token": "secret"},
        },
    )
    result = json.loads(
        (
            await selfhost_proxy.proxy(request("health", method="GET"), setting=setting)
        ).body
    )
    assert result["readiness_scope"] == "worker_loaded_and_brain_route_configured"
    assert result["end_to_end_verified"] is False
    assert result["brain"] == {
        "ready": True,
        "configured": True,
        "readiness_scope": "config-only",
        "end_to_end_verified": False,
        "dependencies": {
            "runtime": {"configured": True, "reachable": None},
            "asr": {"configured": True},
        },
    }
    assert "worker" not in result and "secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_no_content_close_is_normalized_to_readable_json(monkeypatch):
    upstream(monkeypatch, b"", status=204)
    result = await selfhost_proxy.proxy(
        request(f"sessions/{SESSION}/close", body={"client_id": CLIENT}),
        setting=setting,
    )
    assert result.status == 200 and json.loads(result.body) == {"ok": True}
