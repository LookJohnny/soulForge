"""Tests for the Vidu S2 external-memory callback.

The behaviour that matters most here is the disclosure boundary. SoulForge marks
some memories as implicit-only; Vidu's protocol has no such concept and its model
is free to read any tool result aloud. A live session proved that marking the
text and instructing the model to keep quiet does not hold — asked "我最近在吃
什么药吗？", the character recited the implicit memory verbatim. So the contract
these tests lock down is stronger: implicit content never leaves the process.
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
    prefix, _payload, signature = token.split(".")
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


SENSITIVE = "用户最近在服用抗焦虑药物舍曲林"


def _pack():
    return {
        "direct": [
            {
                "id": "m1",
                "memory_layer": "EPISODIC",
                "content": "用户下午三点有一场很重要的期末考试",
                "prompt_text": "[可自然提及] 用户下午三点有一场很重要的期末考试",
                "confidence_score": 0.9,
                "retrieval_score": 2.075,
            }
        ],
        "implicit": [
            {
                "id": "m2",
                "memory_layer": "PROFILE",
                "content": SENSITIVE,
                "prompt_text": f"[隐性长期画像，不要直说来源] {SENSITIVE}",
                "confidence_score": 0.85,
                "retrieval_score": 0.79,
            }
        ],
        "compiled_rules": [
            {
                "id": "r1",
                "memory_layer": "SEMANTIC",
                "content": "回应要短，留白",
                "prompt_text": "[编译行为规则] 回应要短，留白",
                "confidence_score": 0.5,
            }
        ],
        "robot_behavior_hints": {"speech_policy": "low_disturbance"},
        "blocked_count": 1,
    }


def _post(api, body, user="u_1", character_id=None):
    return api.post(
        "/vidu/memory/retrieve",
        json=body,
        headers={"Authorization": f"Bearer {mint_session_token(user, character_id)}"},
    )


def test_missing_token_is_rejected(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    assert api.post("/vidu/memory/retrieve", json={"live_id": "l1"}).status_code == 401


def test_forged_token_is_rejected(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = api.post(
        "/vidu/memory/retrieve",
        json={"live_id": "l1", "query": "考试"},
        headers={"Authorization": "Bearer v1.zzz.zzz"},
    )
    assert resp.status_code == 401


def test_implicit_memory_content_never_leaves_the_process(client):
    """The load-bearing test: a live model recited this when we merely marked it."""
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "我最近在吃什么药", "max_results": 10})
    assert resp.status_code == 200

    body = resp.text
    assert SENSITIVE not in body
    assert "舍曲林" not in body
    assert "m2" not in [m["id"] for m in resp.json()["memories"]]


def test_implicit_memory_becomes_a_directive_that_does_not_name_its_cause(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "x", "max_results": 10})
    directives = [m for m in resp.json()["memories"] if m["source"] == "soulforge_behaviour_hint"]
    assert len(directives) == 1
    assert directives[0]["type"] == "style"
    assert "语气放轻" in directives[0]["summary"]
    assert "舍曲林" not in directives[0]["summary"]


def test_no_hint_means_no_directive(client):
    api, install = client
    pack = _pack()
    pack["robot_behavior_hints"] = {}
    install(_FakeMemoryService(pack))
    resp = _post(api, {"live_id": "l1", "query": "x", "max_results": 10})
    assert all(m["source"] != "soulforge_behaviour_hint" for m in resp.json()["memories"])


def test_direct_memories_are_passed_through(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "下午", "max_results": 10})
    m1 = next(m for m in resp.json()["memories"] if m["id"] == "m1")
    assert "期末考试" in m1["summary"]
    assert m1["type"] == "history"


def test_compiled_rules_are_passed_through_as_style(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "x", "max_results": 10})
    r1 = next(m for m in resp.json()["memories"] if m["id"] == "r1")
    assert r1["type"] == "style"


def test_requested_memory_types_filter_the_result(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "x", "memory_types": ["history"]})
    assert [m["id"] for m in resp.json()["memories"]] == ["m1"]


def test_asking_for_profile_no_longer_yields_the_implicit_profile(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "x", "memory_types": ["profile"]})
    assert resp.json()["memories"] == []
    assert "舍曲林" not in resp.text


def test_max_results_is_honoured(client):
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "x", "max_results": 1})
    assert len(resp.json()["memories"]) == 1


def test_token_identity_decides_whose_memory_is_read(client):
    api, install = client
    service = _FakeMemoryService(_pack())
    install(service)
    _post(api, {"live_id": "l1", "query": "考试"}, user="u_42", character_id="c_7")
    assert service.calls[0]["end_user_id"] == "u_42"
    assert service.calls[0]["character_id"] == "c_7"


def test_retrieval_failure_returns_empty_list_not_an_error_status(client):
    """A 5xx becomes an error tool result and makes the character stumble."""
    api, install = client
    install(_FakeMemoryService(raises=True))
    resp = _post(api, {"live_id": "l1", "query": "x"})
    assert resp.status_code == 200
    assert resp.json()["memories"] == []
    assert resp.json()["error"] == "retrieval_unavailable"


def test_empty_pack_returns_an_empty_array(client):
    api, install = client
    install(_FakeMemoryService({"direct": [], "implicit": [], "compiled_rules": []}))
    resp = _post(api, {"live_id": "l1", "query": "x"})
    assert resp.json() == {"memories": []}


def test_confidence_is_trustworthiness_not_unbounded_relevance(client):
    """retrieval_score is unbounded and routinely > 1; Vidu's confidence is 0..1."""
    api, install = client
    install(_FakeMemoryService(_pack()))
    resp = _post(api, {"live_id": "l1", "query": "x", "max_results": 10})
    m1 = next(m for m in resp.json()["memories"] if m["id"] == "m1")
    assert m1["confidence"] == 0.9


def test_out_of_range_confidence_is_clamped(client):
    api, install = client
    pack = _pack()
    pack["direct"][0]["confidence_score"] = 4.2
    install(_FakeMemoryService(pack))
    resp = _post(api, {"live_id": "l1", "query": "x", "max_results": 10})
    m1 = next(m for m in resp.json()["memories"] if m["id"] == "m1")
    assert m1["confidence"] == 1.0


def test_missing_confidence_is_omitted_not_faked(client):
    api, install = client
    pack = _pack()
    pack["direct"][0].pop("confidence_score", None)
    install(_FakeMemoryService(pack))
    resp = _post(api, {"live_id": "l1", "query": "x", "max_results": 10})
    m1 = next(m for m in resp.json()["memories"] if m["id"] == "m1")
    assert m1["confidence"] is None


def test_tool_instruction_does_not_rely_on_the_model_policing_disclosure():
    """Nothing private is entrusted to these words — the live model ignored them."""
    text = vidu_retrieval.MEMORY_TOOL_INSTRUCTION
    for self_policing in ("不要直说来源", "不要承认", "绝不能复述"):
        assert self_policing not in text
    # It should still discourage the failure the transcript showed on turn one.
    assert "不要编造" in text
