"""Tests for idle-mode inputs and request schema."""

from ai_core.models.schemas import ChatRequest
from ai_core.services.persona_context import _IDLE_INPUTS, idle_input

VALID_UUID = "12345678-1234-1234-1234-123456789abc"


class TestIdleInput:
    def test_known_states(self):
        assert idle_input("bored") == _IDLE_INPUTS["bored"]
        assert idle_input("sleepy") == _IDLE_INPUTS["sleepy"]

    def test_unknown_state_falls_back_to_bored(self):
        assert idle_input("dancing") == _IDLE_INPUTS["bored"]

    def test_inputs_are_inner_instructions(self):
        # Wrapped in （） like touch_silent_input, so the template treats
        # them as situation context rather than user speech
        for text in _IDLE_INPUTS.values():
            assert text.startswith("（") and text.endswith("）")
            assert "一句话" in text or "一句" in text  # keeps musings short


class TestChatRequestIdleMode:
    def test_defaults_off(self):
        req = ChatRequest(character_id=VALID_UUID, device_id="d1", session_id="s1", text_input="hi")
        assert req.idle_mode is False
        assert req.idle_state == "bored"

    def test_idle_request_without_input_is_valid(self):
        # idle_mode requests carry no text or audio — the pipeline
        # synthesizes the musing input itself
        req = ChatRequest(
            character_id=VALID_UUID,
            device_id="d1",
            session_id="s1",
            idle_mode=True,
            idle_state="sleepy",
        )
        assert req.text_input is None
        assert req.audio_data is None
        assert req.idle_mode is True
        assert req.idle_state == "sleepy"
