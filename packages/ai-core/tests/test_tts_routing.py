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


def test_clone_id_routes_to_fish():
    """Voice cloning lives in Fish, so a clone id must reach it whatever the
    configured provider is."""
    c = _client()
    primary, fallback = c._route("ac202cdab88e4879b6be98902b236f0e")
    assert primary.name == "fish"
    assert fallback.name == "edge"


def test_cosyvoice_preset_routes_to_the_configured_provider():
    """prompt_builder yields ``fish_audio_id or dashscope_voice_id``, so a name
    like "longshuo" means the profile has no Fish clone — it is a DashScope
    voice. Routing it to Fish (the old "anything not Neural is Fish's" rule)
    sent every CosyVoice request to the wrong provider."""
    c = _client()
    for voice in ("longshuo", "longxiaochun_v2", "longcheng_v3"):
        assert c._route(voice)[0].name == "edge", voice


def test_without_fish_provider_stays_on_primary():
    c = _client()
    c._fish = None
    assert c._route("longshuo")[0].name == "edge"
