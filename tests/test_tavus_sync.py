"""Existing PAL synchronization, using fake API responses only."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from scripts import tavus_setup


@pytest.fixture
def sync_config(tmp_path, monkeypatch):
    values = {
        "TAVUS_PAL_ID": "existing-pal",
        "TAVUS_PUBLIC_BASE_URL": "https://current.example",
        "GATEWAY_API_TOKEN": "private-gateway-token",
        "TAVUS_API_KEY": "private-tavus-token",
    }
    monkeypatch.setattr(tavus_setup, "setting", lambda key: values.get(key, ""))
    monkeypatch.setattr(tavus_setup, "STATE", tmp_path / "tavus.json")
    monkeypatch.setattr(
        tavus_setup, "call", Mock(side_effect=AssertionError("Unexpected API call"))
    )
    return values


@pytest.mark.parametrize("legacy_persona", [False, True])
def test_sync_patches_only_existing_llm_connection_and_reads_back(
    sync_config,
    monkeypatch,
    capsys,
    legacy_persona,
):
    # Existing saved state is an ID fallback, not a resource to replace or rewrite.
    tavus_setup.STATE.write_text(
        json.dumps({"pal_id": "cached-pal", "conversation_id": "kept"})
    )
    before = tavus_setup.STATE.read_bytes()
    current = {
        "system_prompt": "Preserve character identity",
        "default_face_id": "existing-face",
        "layers": {
            "tts": {"voice": "existing-voice"},
            "llm": {
                "model": "old-model",
                "base_url": "https://previous.example/v1",
                "api_key": "previous-private-key",
                "temperature": 0.6,
            },
        },
    }
    original = deepcopy(current)
    endpoint = (
        "/v2/personas/existing-pal" if legacy_persona else "/v2/pals/existing-pal"
    )
    calls = []

    def fake_api(method, path, body=None):
        calls.append((method, path, deepcopy(body)))
        if legacy_persona and path == "/v2/pals/existing-pal":
            return 404, {}
        assert path == endpoint
        if method == "GET":
            response = deepcopy(current)
            response["layers"]["llm"]["api_key"] = "[redacted-by-provider]"
            return 200, response
        assert method == "PATCH", "sync must never create a PAL or conversation"
        for operation in body:
            assert operation["op"] in {"add", "replace"}
            prefix = "/layers/llm/"
            assert operation["path"].startswith(prefix)
            key = operation["path"].removeprefix(prefix)
            current["layers"]["llm"][key] = operation["value"]
        return 204, {}

    monkeypatch.setattr(tavus_setup, "call", fake_api)
    tavus_setup.cmd_sync()
    assert current["system_prompt"] == original["system_prompt"]
    assert current["default_face_id"] == original["default_face_id"]
    assert current["layers"]["tts"] == original["layers"]["tts"]
    assert current["layers"]["llm"]["temperature"] == 0.6
    assert current["layers"]["llm"] == (
        original["layers"]["llm"] | tavus_setup.connection_config()
    )
    patch = next(body for method, _path, body in calls if method == "PATCH")
    assert {op["path"] for op in patch} == {
        "/layers/llm/model",
        "/layers/llm/base_url",
        "/layers/llm/api_key",
        "/layers/llm/speculative_inference",
    }
    assert (
        next(op for op in patch if op["path"].endswith("speculative_inference"))["op"]
        == "add"
    )
    assert (
        next(op for op in patch if op["path"].endswith("base_url"))["op"] == "replace"
    )
    assert [method for method, *_ in calls] == (["GET"] if legacy_persona else []) + [
        "GET",
        "PATCH",
        "GET",
    ]
    assert tavus_setup.STATE.read_bytes() == before
    output = capsys.readouterr().out
    assert "no conversation created" in output
    assert all(
        secret not in output
        for secret in (
            "private-gateway-token",
            "private-tavus-token",
            "previous-private-key",
        )
    )


@pytest.mark.parametrize("state_key", ["pal_id", "persona_id"])
def test_sync_can_use_existing_cached_id_without_creating_resources(
    sync_config, monkeypatch, state_key
):
    sync_config.pop("TAVUS_PAL_ID")
    tavus_setup.STATE.write_text(json.dumps({state_key: "cached-pal"}))
    wanted = tavus_setup.connection_config()
    call = Mock(
        side_effect=[
            (200, {"layers": {"llm": wanted}}),
            (200, {}),
            (200, {"layers": {"llm": wanted}}),
        ]
    )
    monkeypatch.setattr(tavus_setup, "call", call)
    tavus_setup.cmd_sync()
    assert all(args.args[1] == "/v2/pals/cached-pal" for args in call.call_args_list)
    assert all(args.args[0] in {"GET", "PATCH"} for args in call.call_args_list)


@pytest.mark.parametrize("pal_id", ["", "../other", "with?query=true"])
def test_sync_requires_a_valid_existing_pal_before_api_calls(sync_config, pal_id):
    sync_config["TAVUS_PAL_ID"] = pal_id
    with pytest.raises(SystemExit, match="existing TAVUS_PAL_ID"):
        tavus_setup.cmd_sync()
    tavus_setup.call.assert_not_called()


@pytest.mark.parametrize("status", [400, 401, 405, 409, 500])
def test_sync_rejected_patch_never_forces_overwrite_or_creates_conversation(
    sync_config,
    monkeypatch,
    capsys,
    status,
):
    call = Mock(
        side_effect=[
            (200, {"layers": {"llm": {"model": "existing"}}}),
            (status, {"detail": "private-gateway-token"}),
        ]
    )
    monkeypatch.setattr(tavus_setup, "call", call)
    with pytest.raises(SystemExit, match="no forced overwrite") as error:
        tavus_setup.cmd_sync()
    assert [args.args[0] for args in call.call_args_list] == ["GET", "PATCH"]
    assert not tavus_setup.STATE.exists()
    assert "private-gateway-token" not in str(error.value) + capsys.readouterr().out


def test_sync_refuses_pal_without_custom_llm_layer(sync_config, monkeypatch):
    call = Mock(return_value=(200, {"layers": {"tts": {"voice": "kept"}}}))
    monkeypatch.setattr(tavus_setup, "call", call)
    with pytest.raises(SystemExit, match="existing configuration left intact"):
        tavus_setup.cmd_sync()
    assert call.call_count == 1 and call.call_args.args[0] == "GET"


def test_sync_reports_mismatched_readback_without_retrying_write(
    sync_config, monkeypatch
):
    call = Mock(
        side_effect=[
            (200, {"layers": {"llm": {"model": "existing"}}}),
            (204, {}),
            (200, {"layers": {"llm": {"model": "unchanged"}}}),
        ]
    )
    monkeypatch.setattr(tavus_setup, "call", call)
    with pytest.raises(SystemExit, match="readback did not match"):
        tavus_setup.cmd_sync()
    assert [args.args[0] for args in call.call_args_list] == ["GET", "PATCH", "GET"]
