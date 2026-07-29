"""Voice-aware TTS routing: Edge voices take the fast path, Fish voices
(preset nicknames / clone ids) go to the fish provider where cloning lives."""

from types import SimpleNamespace

from ai_core.services.tts_client import TTSClient


def _client():
    c = TTSClient.__new__(TTSClient)
    c._provider = SimpleNamespace(name="edge")
    c._fallback = None
    c._fish = SimpleNamespace(name="fish")
    return c


def test_edge_voice_routes_to_edge():
    c = _client()
    primary, _ = c._route("zh-CN-YunxiNeural")
    assert primary.name == "edge"


def test_empty_voice_routes_to_primary():
    c = _client()
    assert c._route(None)[0].name == "edge"
    assert c._route("")[0].name == "edge"


def test_fish_nickname_and_clone_id_route_to_fish():
    c = _client()
    primary, fallback = c._route("longshuo")
    assert primary.name == "fish"
    assert fallback.name == "edge"
    assert c._route("ac202cdab88e4879b6be98902b236f0e")[0].name == "fish"


def test_without_fish_provider_stays_on_primary():
    c = _client()
    c._fish = None
    assert c._route("longshuo")[0].name == "edge"
