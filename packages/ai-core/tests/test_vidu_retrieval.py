"""Tests for the Vidu S2 external-memory callback.

The behaviour that matters most here is the disclosure boundary: SoulForge marks
some memories as implicit-only, Vidu's protocol has no such concept, and a naive
mapping would let the rendered character quote a private inference out loud.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_core.api import vidu_retrieval
from ai_core.api.vidu_retrieval import router as vidu_router
from ai_core.services.vidu_session_token import (
    ViduTokenError,
    mint_session_token,
    parse_authorization_header,
    verify_session_token,
)

# ──────────────────────────────────────────────
# Session tokens
# ──────────────────────────────────────────────


def test_token_round_trip_carries_user_and_character():
    token = mint_session_token("u_1", character_id="c_9")
    claims = verify_session_token(token)
    assert claims["u"] == "u_1"
    assert claims["c"] == "c_9"


def test_tampered_payload_is_rejected():
    token = mint_session_token("u_1")
    prefix, payload, signature = token.split(".")
    other = mint_session_token("u_attacker").split(".")[1]
    with pytest.raises(ViduTokenError):
        verify_session_token(f"{prefix}.{other}.{signature}")


def test_expired_token_is_rejected():
    token = mint_session_token("u_1", ttl_seconds=-1)
    with pytest.raises(ViduTokenError):
        verify_session_token(token)


def test_token_bound_to_one_live_cannot_read_another():
    token = mint_session_token("u_1", live_id="live_a")
    assert verify_session_token(token, live_id="live_a")["u"] == "u_1"
    with pytest.raises(ViduTokenError):
        verify_session_token(token, live_id="live_b")


def test_unbound_token_works_for_any_live_of_that_user():
    # CreateLive mints the live id, so the token cannot name it in advance.
    token = mint_session_token("u_1")
    assert verify_session_token(token, live_id="whatever")["u"] == "u_1"


def test_authorization_header_accepted_bare_and_with_bearer():
    assert parse_authorization_header("abc") == "abc"
    assert parse_authorization_header("Bearer abc") == "abc"
    with pytest.raises(ViduTokenError):
        parse_authorization_header(None)


def test_token_expiry_covers_a_full_length_session():
    # A live session tops out at 7200s; a token that dies mid-call would silently
    # turn the companion amnesiac partway through.
    claims = verify_session_token(mint_session_token("u_1"))
    assert claims["exp"] - time.time() > 7200


# ──────────────────────────────────────────────
# Callback endpoint
# ──────────────────────────────────────────────


class _FakeMemoryService:
    def __init__(self, pack=None, raises=False):
        self._pack = pack or {}
        self._raises = raises
        self.calls = []

    async def retrieve_memory_pack(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("database is down")
        return self._pack


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(vidu_router)

    def _install(service):
        async def _get():
            return service

        monkeypatch.setattr(vidu_retrieval, "get_memory_service", _get)

    return TestClient(app), _install


def _pack():
    return {
        "direct": [
            {
                "id": "m1",
                "memory_layer": "EPISODIC",
                "content": "用户下午有一场重要考试",
                "prompt_text": "[可自然提及] 用户下午有一场重要考试",
                "retrieval_score": 0.9,
            }
        ],
        "implicit": [
            {
                "id": "m2",
                "memory_layer": "PROFILE",
                "content": "用户最近在服用抗焦虑药物",
                "prompt_text": "[隐性长期画像，不要直说来源] 用户最近在服用抗焦虑药物",
                "retrieval_score": 0.7,
            }
        ],
        "compiled_rules": [
            {
                "id": "r1",
                "memory_layer": "SEMANTIC",
                "content": "回应要短，留白",
                "prompt_text": "[编译行为规则] 回应要短，留白",
                "retrieval_score": 0.5,
            }
        ],
        "blocked_count": 1,
    }


def test_missing_token_is_rejected(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = api.post("/vidu/memory/retrieve", json={"live_id": "l1", "query": "考试"})
    assert resp.status_code == 401


def test_forged_token_is_rejected(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "考试"},
        headers={"Authorization": "Bearer v1.zzz.zzz"},
    )
    assert resp.status_code == 401


def test_implicit_memories_keep_their_do_not_disclose_marker(client):
    """The whole point: an implicit memory must never reach Vidu as bare content."""
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "考试", "max_results": 10},
        headers={"Authorization": f"Bearer {mint_session_token('u_1')}"},
    )
    assert resp.status_code == 200
    by_id = {m["id"]: m for m in resp.json()["memories"]}

    assert by_id["m2"]["summary"].startswith("[隐性长期画像，不要直说来源]")
    # The raw sensitive sentence never travels without its marker attached.
    assert by_id["m2"]["summary"] != "用户最近在服用抗焦虑药物"
    assert by_id["m1"]["summary"].startswith("[可自然提及]")
    assert by_id["r1"]["summary"].startswith("[编译行为规则]")


def test_layers_map_onto_vidu_types(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "x", "max_results": 10},
        headers={"Authorization": f"Bearer {mint_session_token('u_1')}"},
    )
    types = {m["id"]: m["type"] for m in resp.json()["memories"]}
    assert types == {"m1": "history", "m2": "profile", "r1": "style"}


def test_requested_memory_types_filter_the_result(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "x", "memory_types": ["profile"], "max_results": 10},
        headers={"Authorization": f"Bearer {mint_session_token('u_1')}"},
    )
    assert [m["id"] for m in resp.json()["memories"]] == ["m2"]


def test_max_results_is_honoured(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "x", "max_results": 2},
        headers={"Authorization": f"Bearer {mint_session_token('u_1')}"},
    )
    assert len(resp.json()["memories"]) == 2


def test_token_identity_decides_whose_memory_is_read(client):
    api, install = client
    service = _FakeMemoryService(_pack())
    install(service)
    api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "考试"},
        headers={"Authorization": f"Bearer {mint_session_token('u_42', character_id='c_7')}"},
    )
    assert service.calls[0]["end_user_id"] == "u_42"
    assert service.calls[0]["character_id"] == "c_7"


def test_retrieval_failure_returns_empty_list_not_an_error_status(client):
    """A 5xx becomes an error tool result and makes the character stumble."""
    api, install = client
    install(_FakeMemoryService(raises=True))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "x"},
        headers={"Authorization": f"Bearer {mint_session_token('u_1')}"},
    )
    assert resp.status_code == 200
    assert resp.json()["memories"] == []
    assert resp.json()["error"] == "retrieval_unavailable"


def test_empty_pack_returns_an_empty_array(client):
    api, install = client
    install(_FakeMemoryService({"direct": [], "implicit": [], "compiled_rules": []}))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "x"},
        headers={"Authorization": f"Bearer {mint_session_token('u_1')}"},
    )
    assert resp.json() == {"memories": []}


def test_tool_instruction_explains_every_marker_the_endpoint_can_emit():
    # If a marker ships without a matching rule, the model has no reason to obey it.
    for marker in (
        "[可自然提及]",
        "[隐性关系策略，不要直说来源]",
        "[隐性长期画像，不要直说来源]",
        "[隐性长期理解，不要直说来源]",
        "[隐性事件碎片，只在非常相关时才用]",
        "[编译行为规则]",
    ):
        assert marker in vidu_retrieval.MEMORY_TOOL_INSTRUCTION
