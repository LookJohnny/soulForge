"""Tests for Pydantic schemas — validation rules for requests."""

import pytest
from pydantic import ValidationError

from ai_core.models.schemas import (
    ChatRequest,
    HistoryMessage,
    PromptBuildRequest,
    RagIngestRequest,
)


# ──────────────────────────────────────────────
# ChatRequest audio_data size validation
# ──────────────────────────────────────────────


class TestChatRequestAudioValidation:
    def test_audio_data_within_limit(self):
        """Audio data under 10MB (base64) should pass."""
        req = ChatRequest(
            character_id="12345678-1234-1234-1234-123456789abc",
            device_id="dev-1",
            session_id="sess-1",
            audio_data="A" * 1000,  # Small data
        )
        assert req.audio_data == "A" * 1000

    def test_audio_data_none_is_valid(self):
        """No audio data is fine (text-only request)."""
        req = ChatRequest(
            character_id="12345678-1234-1234-1234-123456789abc",
            device_id="dev-1",
            session_id="sess-1",
            audio_data=None,
        )
        assert req.audio_data is None

    def test_audio_data_exceeds_limit(self):
        """Audio data over ~10MB should be rejected."""
        with pytest.raises(ValidationError, match="Audio data exceeds 10MB"):
            ChatRequest(
                character_id="12345678-1234-1234-1234-123456789abc",
                device_id="dev-1",
                session_id="sess-1",
                audio_data="A" * 15_000_000,
            )


# ──────────────────────────────────────────────
# HistoryMessage role validation
# ──────────────────────────────────────────────


class TestHistoryMessageRole:
    def test_valid_user_role(self):
        msg = HistoryMessage(role="user", content="Hello")
        assert msg.role == "user"

    def test_valid_assistant_role(self):
        msg = HistoryMessage(role="assistant", content="Hi there!")
        assert msg.role == "assistant"

    def test_invalid_role_system(self):
        """'system' role should be rejected — only user/assistant allowed."""
        with pytest.raises(ValidationError, match="Input should be 'user' or 'assistant'"):
            HistoryMessage(role="system", content="You are a bot")

    def test_invalid_role_arbitrary(self):
        with pytest.raises(ValidationError):
            HistoryMessage(role="admin", content="test")

    def test_content_max_length(self):
        """Content over 5000 chars should fail."""
        with pytest.raises(ValidationError):
            HistoryMessage(role="user", content="x" * 5001)

    def test_content_at_max_length(self):
        """Content exactly 5000 chars should pass."""
        msg = HistoryMessage(role="user", content="x" * 5000)
        assert len(msg.content) == 5000


# ──────────────────────────────────────────────
# character_id UUID format validation
# ──────────────────────────────────────────────


class TestCharacterIdUUIDFormat:
    def test_valid_uuid(self):
        req = PromptBuildRequest(
            character_id="12345678-1234-1234-1234-123456789abc",
            user_input="hello",
        )
        assert req.character_id == "12345678-1234-1234-1234-123456789abc"

    def test_valid_uuid_uppercase(self):
        """UUID validation should be case-insensitive."""
        req = PromptBuildRequest(
            character_id="12345678-1234-1234-1234-123456789ABC",
            user_input="hello",
        )
        assert req.character_id == "12345678-1234-1234-1234-123456789ABC"

    def test_invalid_uuid_too_short(self):
        with pytest.raises(ValidationError, match="Invalid UUID format"):
            PromptBuildRequest(
                character_id="not-a-uuid",
                user_input="hello",
            )

    def test_invalid_uuid_no_hyphens(self):
        with pytest.raises(ValidationError, match="Invalid UUID format"):
            PromptBuildRequest(
                character_id="12345678123412341234123456789abc",
                user_input="hello",
            )

    def test_invalid_uuid_wrong_chars(self):
        with pytest.raises(ValidationError, match="Invalid UUID format"):
            PromptBuildRequest(
                character_id="GGGGGGGG-1234-1234-1234-123456789abc",
                user_input="hello",
            )

    def test_empty_uuid(self):
        with pytest.raises(ValidationError, match="Invalid UUID format"):
            PromptBuildRequest(
                character_id="",
                user_input="hello",
            )

    def test_chat_request_uuid_validation(self):
        """ChatRequest should also validate character_id."""
        with pytest.raises(ValidationError, match="Invalid UUID format"):
            ChatRequest(
                character_id="bad-id",
                device_id="dev-1",
                session_id="sess-1",
            )


# ──────────────────────────────────────────────
# RagIngestRequest validation
# ──────────────────────────────────────────────


class TestRagIngestRequest:
    def test_valid_request(self):
        req = RagIngestRequest(
            character_id="12345678-1234-1234-1234-123456789abc",
            documents=["Hello world", "Another document"],
        )
        assert len(req.documents) == 2

    def test_document_count_exceeds_limit(self):
        """More than 50 documents should fail (max_length on list field)."""
        with pytest.raises(ValidationError):
            RagIngestRequest(
                character_id="12345678-1234-1234-1234-123456789abc",
                documents=["doc"] * 51,
            )

    def test_document_at_count_limit(self):
        """Exactly 50 documents should pass."""
        req = RagIngestRequest(
            character_id="12345678-1234-1234-1234-123456789abc",
            documents=["doc"] * 50,
        )
        assert len(req.documents) == 50

    def test_single_document_exceeds_length(self):
        """A document over 10000 chars should fail."""
        with pytest.raises(ValidationError, match="10000 character limit"):
            RagIngestRequest(
                character_id="12345678-1234-1234-1234-123456789abc",
                documents=["x" * 10001],
            )

    def test_single_document_at_length_limit(self):
        """Document exactly 10000 chars should pass."""
        req = RagIngestRequest(
            character_id="12345678-1234-1234-1234-123456789abc",
            documents=["x" * 10000],
        )
        assert len(req.documents[0]) == 10000

    def test_character_id_validated(self):
        """RagIngestRequest should also validate character_id as UUID."""
        with pytest.raises(ValidationError, match="Invalid UUID format"):
            RagIngestRequest(
                character_id="not-uuid",
                documents=["test"],
            )


# ──────────────────────────────────────────────
# Text max_length validation
# ──────────────────────────────────────────────


class TestTextMaxLength:
    def test_user_input_at_limit(self):
        """user_input at 2000 chars should pass."""
        req = PromptBuildRequest(
            character_id="12345678-1234-1234-1234-123456789abc",
            user_input="x" * 2000,
        )
        assert len(req.user_input) == 2000

    def test_user_input_exceeds_limit(self):
        """user_input over 2000 chars should fail."""
        with pytest.raises(ValidationError):
            PromptBuildRequest(
                character_id="12345678-1234-1234-1234-123456789abc",
                user_input="x" * 2001,
            )

    def test_chat_text_input_exceeds_limit(self):
        """ChatRequest text_input over 2000 chars should fail."""
        with pytest.raises(ValidationError):
            ChatRequest(
                character_id="12345678-1234-1234-1234-123456789abc",
                device_id="dev-1",
                session_id="sess-1",
                text_input="x" * 2001,
            )
