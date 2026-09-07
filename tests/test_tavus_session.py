"""Offline lifecycle tests. All Tavus calls use a synthetic in-memory provider."""

import asyncio
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
import pytest
import pytest_asyncio

from studio import tavus_session
from studio.tavus_session import SessionError, TavusSessionManager, register


CLIENT_ID = "cc1d8c30-9918-4d4f-88a9-4dce26c4f995"
OTHER_CLIENT_ID = "c2c9c3d7-2c8b-4d46-bfd6-3b0b7c87e16a"
SETTINGS = {
    "TAVUS_API_KEY": "synthetic-tavus-secret",
    "TAVUS_PAL_ID": "p_synthetic",
    "TAVUS_PUBLIC_BASE_URL": "https://synthetic.trycloudflare.com",
    "GATEWAY_API_TOKEN": "synthetic-brain-secret",
}


@pytest.mark.asyncio
async def test_http_transport_handles_fragmented_json_without_redirect_or_proxy(
    monkeypatch,
):
    async def chunks(_size):
        for part in (b'{"status":', b'"active",', b'"conversation_id":"c_synthetic"}'):
            yield part

    @asynccontextmanager
    async def context(value):
        yield value

    upstream = SimpleNamespace(status=200, content=SimpleNamespace(iter_chunked=chunks))
    client = SimpleNamespace(request=Mock(return_value=context(upstream)))
    factory = Mock(return_value=context(client))
    monkeypatch.setattr(tavus_session.aiohttp, "ClientSession", factory)
    status, result = await tavus_session.tavus_request(
        "POST", "/v2/conversations", "synthetic-secret", {"require_auth": True}
    )
    assert status == 200 and result["conversation_id"] == "c_synthetic"
    assert factory.call_args.kwargs == {"trust_env": False}
    assert client.request.call_args.args == (
        "POST",
        "https://tavusapi.com/v2/conversations",
    )
    assert client.request.call_args.kwargs["allow_redirects"] is False
    assert client.request.call_args.kwargs["headers"] == {
        "x-api-key": "synthetic-secret"
    }


class Provider:
    def __init__(self):
        self.calls = []
        self.pal = {
            "pal_id": "p_synthetic",
            "default_face_id": "r_existing",
            "layers": {
                "llm": {
                    "model": "soulforge-brain",
                    "base_url": "https://synthetic.trycloudflare.com/v1",
                    "api_key": "synthetic-brain-secret",
                    "speculative_inference": False,
                }
            },
        }
        self.rooms = {}
        self.post_gate = None
        self.creation_status = 200
        self.response_override = {}
        self.lose_create_response = False
        self.end_status = 200
        self.list_fails = False

    async def __call__(self, method, path, key, body=None):
        assert key == SETTINGS["TAVUS_API_KEY"]
        self.calls.append((method, path, deepcopy(body)))
        if method == "GET" and path == "/v2/pals/p_synthetic":
            return 200, deepcopy(self.pal)
        if method == "POST" and path == "/v2/conversations":
            if self.post_gate:
                await self.post_gate.wait()
            if self.creation_status != 200:
                return self.creation_status, {"error": "do not expose provider secret"}
            cid = f"c_{len(self.rooms) + 1}"
            room = {
                "conversation_id": cid,
                "pal_id": body["pal_id"],
                "conversation_name": body["conversation_name"],
                "status": "active",
                "conversation_url": f"https://tavus.daily.co/{cid}",
            }
            self.rooms[cid] = room
            if self.lose_create_response:
                raise SessionError("Synthetic response lost")
            return 200, {
                **room,
                "meeting_token": "synthetic-short-lived-meeting-token",
                **self.response_override,
            }
        if method == "GET" and path.startswith("/v2/conversations?limit=100&page="):
            if self.list_fails:
                raise SessionError("Synthetic reconciliation unavailable")
            page = int(path.rsplit("=", 1)[1])
            return 200, {
                "data": deepcopy(
                    list(self.rooms.values())[(page - 1) * 100 : page * 100]
                ),
                "total_count": len(self.rooms),
            }
        if method == "GET" and path.startswith("/v2/conversations/"):
            room = self.rooms.get(path.rsplit("/", 1)[1])
            return (200, deepcopy(room)) if room else (404, {})
        if method == "POST" and path.endswith("/end"):
            cid = path.split("/")[-2]
            if self.end_status == 200:
                self.rooms[cid]["status"] = "ended"
            return self.end_status, {}
        raise AssertionError(f"Unexpected external operation: {method} {path}")

    def posts(self):
        return [
            body
            for method, path, body in self.calls
            if method == "POST" and path == "/v2/conversations"
        ]


async def stop_reaper(manager):
    manager._reaper.cancel()
    with suppress(asyncio.CancelledError):
        await manager._reaper
    manager._reaper = None


@pytest_asyncio.fixture
async def fixture(tmp_path):
    provider, now = Provider(), [1_780_000_000.0]
    settings = dict(SETTINGS)
    manager = TavusSessionManager(
        lambda key: settings.get(key, ""),
        tmp_path / "private" / "owned-session.json",
        request=provider,
        clock=lambda: now[0],
    )
    await manager.start()
    await stop_reaper(manager)
    yield manager, provider, now, settings
    await manager.close()


@pytest.mark.asyncio
async def test_status_is_local_read_only_and_create_uses_existing_pal_with_hard_caps(
    fixture,
):
    manager, provider, _, _ = fixture
    assert manager.snapshot()["status"] == "idle"
    assert manager.snapshot()["credential_verification"] == "not_checked"
    assert provider.calls == []
    result = await manager.create(CLIENT_ID)
    body = provider.posts()[0]
    assert body["pal_id"] == SETTINGS["TAVUS_PAL_ID"]
    assert "face_id" not in body and "replica_id" not in body
    assert body["require_auth"] is True and body["max_participants"] == 2
    assert body["properties"] == {
        "max_call_duration": 300,
        "participant_absent_timeout": 120,
        "participant_left_timeout": 10,
        "enable_recording": False,
        "auto_start_recording": False,
    }
    assert result["session"]["meeting_token"]
    assert result["reused"] is False
    assert result["credential_verification"] == "matched"
    assert "meeting_token" not in json.dumps(manager.snapshot())
    saved = manager.state_path.read_text()
    for secret in (*SETTINGS.values(), result["session"]["meeting_token"]):
        if secret != SETTINGS["TAVUS_PAL_ID"]:
            assert secret not in saved
    assert manager.state_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_simultaneous_clicks_make_exactly_one_paid_creation(fixture):
    manager, provider, _, _ = fixture
    provider.post_gate = asyncio.Event()
    tasks = [asyncio.create_task(manager.create(CLIENT_ID)) for _ in range(5)]
    await asyncio.sleep(0)
    provider.post_gate.set()
    results = await asyncio.gather(*tasks)
    assert len(provider.posts()) == 1
    assert len({r["session"]["conversation_id"] for r in results}) == 1
    assert [r["reused"] for r in results].count(False) == 1


@pytest.mark.asyncio
async def test_different_browser_pages_cannot_join_or_end_each_others_rooms(fixture):
    manager, provider, _, _ = fixture
    result = await manager.create(CLIENT_ID)
    cid = result["session"]["conversation_id"]
    with pytest.raises(SessionError) as create_error:
        await manager.create(OTHER_CLIENT_ID)
    assert create_error.value.status == 409
    with pytest.raises(SessionError) as end_error:
        await manager.end(cid, OTHER_CLIENT_ID)
    assert end_error.value.status == 403
    snapshot = json.dumps(manager.snapshot())
    assert CLIENT_ID not in snapshot and "meeting_token" not in snapshot
    assert len(provider.posts()) == 1 and provider.rooms[cid]["status"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("base_url", "https://wrong.example/v1"),
        ("model", "another-brain"),
        ("api_key", "wrong-secret"),
        ("speculative_inference", True),
        ("speculative_inference", None),
    ],
)
async def test_pal_mismatch_blocks_creation_without_reconfiguring_remote(
    fixture, field, value
):
    manager, provider, _, _ = fixture
    provider.pal["layers"]["llm"][field] = value
    with pytest.raises(SessionError, match="does not match"):
        await manager.create(CLIENT_ID)
    assert all(method == "GET" for method, _, _ in provider.calls)
    assert manager.record is None


@pytest.mark.asyncio
async def test_provider_mask_is_accepted_without_claiming_credential_readback(fixture):
    manager, provider, _, _ = fixture
    provider.pal["layers"]["llm"]["api_key"] = "********"
    result = await manager.create(CLIENT_ID)
    assert result["credential_verification"] == "provider_redacted"
    assert manager.snapshot()["credential_verification"] == "provider_redacted"
    assert len(provider.posts()) == 1
    assert not any(method == "PATCH" for method, _, _ in provider.calls)
    assert "********" not in json.dumps(manager.snapshot())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_key",
    [
        None,
        "",
        "wrong-key",
        "*******",
        "*********",
        "abcd****",
        "<redacted>",
        "[REDACTED]",
        "••••••••",
        "******** ",
    ],
)
async def test_only_exact_confirmed_provider_mask_can_bypass_plaintext_comparison(
    fixture, remote_key
):
    manager, provider, _, _ = fixture
    provider.pal["layers"]["llm"]["api_key"] = remote_key
    with pytest.raises(SessionError, match="does not match"):
        await manager.create(CLIENT_ID)
    assert provider.posts() == []
    assert manager.snapshot()["credential_verification"] == "not_checked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("base_url", "https://wrong.example/v1"),
        ("model", "another-brain"),
        ("speculative_inference", True),
    ],
)
async def test_redacted_key_does_not_bypass_other_pal_connection_checks(
    fixture, field, value
):
    manager, provider, _, _ = fixture
    provider.pal["layers"]["llm"].update({"api_key": "********", field: value})
    with pytest.raises(SessionError, match="does not match"):
        await manager.create(CLIENT_ID)
    assert provider.posts() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", list(SETTINGS))
async def test_missing_configuration_never_contacts_tavus(fixture, missing):
    manager, provider, _, settings = fixture
    settings[missing] = ""
    assert manager.snapshot()["configured"] is False
    with pytest.raises(SessionError):
        await manager.create(CLIENT_ID)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_journal_write_failure_prevents_paid_request(fixture, monkeypatch):
    manager, provider, _, _ = fixture
    with monkeypatch.context() as patch:
        patch.setattr(
            manager, "_save", Mock(side_effect=OSError("synthetic disk full"))
        )
        with pytest.raises(SessionError, match="no room was created"):
            await manager.create(CLIENT_ID)
    assert provider.posts() == [] and manager.record is None


@pytest.mark.asyncio
async def test_account_credential_change_does_not_end_room_with_different_account(
    fixture,
):
    manager, provider, _, settings = fixture
    cid = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    settings["TAVUS_API_KEY"] = "different-account-secret"
    with pytest.raises(SessionError, match="same Tavus account"):
        await manager.end(cid, CLIENT_ID)
    assert not any(path.endswith("/end") for _, path, _ in provider.calls)
    assert manager.record and manager.snapshot()["error"]
    settings["TAVUS_API_KEY"] = SETTINGS["TAVUS_API_KEY"]


@pytest.mark.asyncio
async def test_cancelled_creation_is_reconciled_and_does_not_retry_post(fixture):
    manager, provider, _, _ = fixture
    original = provider.__call__

    async def cancelled_response(method, path, key, body=None):
        result = await original(method, path, key, body)
        if method == "POST" and path == "/v2/conversations":
            raise asyncio.CancelledError()
        return result

    manager.request = cancelled_response
    with pytest.raises(asyncio.CancelledError):
        await manager.create(CLIENT_ID)
    assert manager.record is None
    assert provider.rooms["c_1"]["status"] == "ended" and len(provider.posts()) == 1


@pytest.mark.asyncio
async def test_provider_rejection_has_no_secret_error_or_journal_room(fixture):
    manager, provider, _, _ = fixture
    provider.creation_status = 401
    with pytest.raises(SessionError) as error:
        await manager.create(CLIENT_ID)
    assert "do not expose" not in str(error.value)
    assert manager.record is None


@pytest.mark.asyncio
async def test_repeat_end_and_old_browser_cannot_end_new_or_unrelated_room(fixture):
    manager, provider, _, _ = fixture
    first = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    with pytest.raises(SessionError, match="not the current"):
        await manager.end("c_someone_else", CLIENT_ID)
    assert (await manager.end(first, CLIENT_ID))["status"] == "idle"
    assert (await manager.end(first, CLIENT_ID))["status"] == "idle"
    second = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    with pytest.raises(SessionError):
        await manager.end(first, CLIENT_ID)
    assert provider.rooms[second]["status"] == "active"


@pytest.mark.asyncio
async def test_malformed_private_join_response_is_cleaned_not_exposed(fixture):
    manager, provider, _, _ = fixture
    provider.response_override = {"meeting_token": ""}
    with pytest.raises(SessionError, match="usable private room"):
        await manager.create(CLIENT_ID)
    assert provider.rooms["c_1"]["status"] == "ended"
    assert manager.snapshot()["session"] is None


@pytest.mark.asyncio
async def test_uncertain_create_reconciles_own_nonce_and_never_other_conversations(
    fixture,
):
    manager, provider, _, _ = fixture
    provider.rooms["c_unrelated"] = {
        "conversation_id": "c_unrelated",
        "status": "active",
        "pal_id": "p_synthetic",
        "conversation_name": "Another user's session",
    }
    provider.lose_create_response = True
    with pytest.raises(SessionError):
        await manager.create(CLIENT_ID)
    assert len(provider.posts()) == 1
    assert provider.rooms["c_unrelated"]["status"] == "active"
    assert provider.rooms["c_2"]["status"] == "ended"
    assert manager.record is None


@pytest.mark.asyncio
async def test_cleanup_failure_persists_and_restart_recovers_without_token(fixture):
    manager, provider, now, settings = fixture
    cid = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    provider.end_status = 503
    with pytest.raises(SessionError):
        await manager.end(cid, CLIENT_ID)
    assert manager.snapshot()["status"] == "cleanup_pending"
    assert manager.snapshot()["error"]
    with pytest.raises(SessionError):
        await manager.create(CLIENT_ID)
    await manager.close()
    provider.end_status = 200
    replacement = TavusSessionManager(
        lambda key: settings.get(key, ""),
        manager.state_path,
        request=provider,
        clock=lambda: now[0],
    )
    await replacement.start()
    await stop_reaper(replacement)
    assert replacement.join_info is None
    await replacement.maintain()
    assert replacement.snapshot()["status"] == "idle"
    assert provider.rooms[cid]["status"] == "ended"
    assert len(provider.posts()) == 1
    await replacement.close()


@pytest.mark.asyncio
async def test_shutdown_ends_owned_room_and_crash_restart_cleans_active_journal(
    fixture,
):
    manager, provider, now, settings = fixture
    cid = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    # Simulate process exit: release the process lock without cleanup, leaving the
    # active journal and provider room intact. No private token enters the journal.
    manager._file_lock.close()
    manager._file_lock = None
    replacement = TavusSessionManager(
        lambda key: settings.get(key, ""),
        manager.state_path,
        request=provider,
        clock=lambda: now[0],
    )
    await replacement.start()
    await stop_reaper(replacement)
    assert replacement.snapshot()["status"] == "cleanup_pending"
    await replacement.maintain()
    assert provider.rooms[cid]["status"] == "ended"
    second = (await replacement.create(OTHER_CLIENT_ID))["session"]["conversation_id"]
    await replacement.close()
    assert provider.rooms[second]["status"] == "ended"
    assert json.loads(replacement.state_path.read_text())["record"] is None


@pytest.mark.asyncio
async def test_lost_create_response_survives_restart_and_finds_later_page(fixture):
    manager, provider, now, settings = fixture
    for i in range(100):
        provider.rooms[f"c_other_{i}"] = {
            "conversation_id": f"c_other_{i}",
            "status": "active",
            "pal_id": "p_synthetic",
            "conversation_name": "Other room",
        }
    provider.lose_create_response = provider.list_fails = True
    with pytest.raises(SessionError):
        await manager.create(CLIENT_ID)
    assert manager.record["conversation_id"] is None
    await manager.close()
    provider.list_fails = False
    replacement = TavusSessionManager(
        lambda key: settings.get(key, ""),
        manager.state_path,
        request=provider,
        clock=lambda: now[0],
    )
    await replacement.start()
    await stop_reaper(replacement)
    await replacement.maintain()
    assert replacement.record is None
    assert sum(room["status"] == "ended" for room in provider.rooms.values()) == 1
    assert any("page=2" in path for _, path, _ in provider.calls)
    await replacement.close()


@pytest.mark.asyncio
async def test_mismatched_ownership_blocks_remote_end_even_with_recorded_id(fixture):
    manager, provider, _, _ = fixture
    cid = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    provider.rooms[cid]["conversation_name"] = "Unrelated room"
    with pytest.raises(SessionError, match="ownership did not match"):
        await manager.end(cid, CLIENT_ID)
    assert not any(path.endswith("/end") for _, path, _ in provider.calls)
    assert manager.record and manager.snapshot()["status"] == "cleanup_pending"


@pytest.mark.asyncio
async def test_timeout_and_provider_absent_end_are_observed_without_browser(fixture):
    manager, provider, now, _ = fixture
    first = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    # Tavus enforces the absent cap; no synthetic "joined" signal is invented.
    now[0] += 120
    provider.rooms[first]["status"] = "ended"
    await manager.maintain()
    assert manager.snapshot()["status"] == "idle"
    second = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    now[0] += 300
    await manager.maintain()
    assert provider.rooms[second]["status"] == "ended"
    assert manager.record is None


@pytest.mark.asyncio
async def test_second_studio_process_cannot_adopt_or_end_first_process_room(fixture):
    manager, provider, _, settings = fixture
    cid = (await manager.create(CLIENT_ID))["session"]["conversation_id"]
    other = TavusSessionManager(
        lambda key: settings.get(key, ""), manager.state_path, request=provider
    )
    await other.start()
    assert other.snapshot()["status"] == "unavailable"
    with pytest.raises(SessionError):
        await other.create(CLIENT_ID)
    await other.close()
    assert provider.rooms[cid]["status"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    ["[]", "not-json", '{"version":1,"record":{"conversation_id":"c_other"}}'],
)
async def test_corrupt_or_unowned_journal_disables_creation_and_cleanup(
    tmp_path, content
):
    path = tmp_path / "owned.json"
    path.write_text(content)
    provider = Provider()
    manager = TavusSessionManager(
        lambda key: SETTINGS.get(key, ""), path, request=provider
    )
    await manager.start()
    assert manager.snapshot()["status"] == "unavailable"
    with pytest.raises(SessionError):
        await manager.create(CLIENT_ID)
    await manager.close()
    assert provider.calls == [] and path.read_text() == content


def browser_request(method, path, headers=None, body=None, remote="127.0.0.1"):
    transport = Mock()
    transport.get_extra_info.side_effect = lambda name, default=None: (
        (remote, 12345) if name == "peername" else default
    )
    req = make_mocked_request(
        method,
        path,
        headers={"Host": "127.0.0.1:8899", **(headers or {})},
        transport=transport,
        payload=SimpleNamespace(at_eof=lambda: False),
    )
    if method == "POST":
        req._read_bytes = json.dumps({"client_id": CLIENT_ID, **(body or {})}).encode()
    return req


async def invoke(app, req):
    match = await app.router.resolve(req)
    return await match.handler(req)


@pytest.mark.asyncio
async def test_registered_routes_get_origin_metadata_and_mutation_auth(tmp_path):
    provider = Provider()
    app = web.Application()
    manager = register(
        app,
        setting=lambda key: SETTINGS.get(key, ""),
        state_path=tmp_path / "owned.json",
        request=provider,
    )
    await manager.start()
    await stop_reaper(manager)
    path, origin = "/api/joi/session", {"Origin": "http://127.0.0.1:8899"}
    metadata = {
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    try:
        for headers in (origin, metadata):
            result = await invoke(app, browser_request("GET", path, headers))
            assert (
                result.status == 200 and result.headers["Cache-Control"] == "no-store"
            )
        assert provider.calls == []
        for headers in (
            {},
            {"Origin": "https://evil.example"},
            {**metadata, "Sec-Fetch-Site": "same-site"},
        ):
            for method in ("GET", "POST"):
                with pytest.raises(web.HTTPForbidden):
                    await invoke(app, browser_request(method, path, headers))
        with pytest.raises(web.HTTPForbidden):
            await invoke(
                app, browser_request("GET", path, metadata, remote="192.168.1.10")
            )
        result = await invoke(app, browser_request("POST", path, origin))
        assert result.status == 200
        join = json.loads(result.body)["session"]
        assert join["meeting_token"] and "synthetic-brain-secret" not in result.text
        another = await invoke(
            app, browser_request("POST", path, origin, {"client_id": OTHER_CLIENT_ID})
        )
        assert another.status == 409 and "meeting_token" not in another.text
        forbidden_end = await invoke(
            app,
            browser_request(
                "POST",
                path + "/end",
                origin,
                {
                    "client_id": OTHER_CLIENT_ID,
                    "conversation_id": join["conversation_id"],
                },
            ),
        )
        assert forbidden_end.status == 403
        state = await invoke(app, browser_request("GET", path, origin))
        assert (
            "meeting_token" not in state.text and "conversation_url" not in state.text
        )
        ended = await invoke(
            app,
            browser_request(
                "POST",
                path + "/end",
                origin,
                {"conversation_id": join["conversation_id"]},
            ),
        )
        assert json.loads(ended.body)["status"] == "idle"
        bad = await invoke(
            app, browser_request("POST", path, origin, {"pal_id": "override"})
        )
        assert bad.status == 400
        invalid_client = await invoke(
            app, browser_request("POST", path, origin, {"client_id": None})
        )
        assert invalid_client.status == 400
    finally:
        await manager.close()
