"""DashScope voice ids are versioned with the model.

A v1 voice name against cosyvoice-v2 does not raise — DashScope returns empty
audio with engine code 418, which surfaced only as "synthesis failed". The pair
is therefore pinned here rather than left to whoever edits one of the two.
"""

from ai_core.services.tts.dashscope_tts import DEFAULT_VOICE, PRESET_VOICES, VOICE_MODEL


def test_voice_ids_match_the_model_version():
    assert VOICE_MODEL == "cosyvoice-v2"
    for voice in PRESET_VOICES:
        assert voice.endswith("_v2"), f"{voice} 不是 cosyvoice-v2 的音色名"


def test_default_voice_is_a_preset():
    assert DEFAULT_VOICE in PRESET_VOICES


def test_every_preset_has_a_label():
    assert all(label.strip() for label in PRESET_VOICES.values())


def test_v1_names_from_the_database_are_retagged():
    """voice_profiles rows and the Prisma seed still carry bare v1 names."""
    from ai_core.services.tts.dashscope_tts import normalize_voice

    assert normalize_voice("longxiaochun") == "longxiaochun_v2"
    assert normalize_voice("longyue") == "longyue_v2"


def test_v3_names_from_voice_matcher_are_retagged():
    """voice_matcher scores against _v3 ids; they must still reach a real voice."""
    from ai_core.services.tts.dashscope_tts import normalize_voice

    assert normalize_voice("longcheng_v3") == "longcheng_v2"


def test_already_correct_names_are_left_alone():
    from ai_core.services.tts.dashscope_tts import normalize_voice

    assert normalize_voice("longshu_v2") == "longshu_v2"


def test_unknown_ids_pass_through_untouched():
    """A cloned voice id is not a preset and must not be rewritten."""
    from ai_core.services.tts.dashscope_tts import normalize_voice

    assert normalize_voice("my-cloned-voice-abc123") == "my-cloned-voice-abc123"
    assert normalize_voice("zh-CN-XiaoyiNeural") == "zh-CN-XiaoyiNeural"
    assert normalize_voice("") == ""


def test_every_preset_survives_normalization():
    from ai_core.services.tts.dashscope_tts import PRESET_VOICES, normalize_voice

    for voice in PRESET_VOICES:
        assert normalize_voice(voice) in PRESET_VOICES
