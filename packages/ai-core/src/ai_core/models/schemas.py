import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _validate_uuid_format(v: str) -> str:
    if not _UUID_PATTERN.match(v):
        raise ValueError("Invalid UUID format")
    return v


class PersonalityTraits(BaseModel):
    extrovert: int = 50
    humor: int = 50
    warmth: int = 50
    curiosity: int = 50
    energy: int = 50


class PromptBuildRequest(BaseModel):
    character_id: str
    end_user_id: str | None = None
    user_input: str = Field(max_length=2000)

    @field_validator("character_id")
    @classmethod
    def validate_character_id(cls, v: str) -> str:
        return _validate_uuid_format(v)


class PromptBuildResponse(BaseModel):
    system_prompt: str
    voice_id: str | None = None
    voice_speed: float = 1.0


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=5000)


class TouchEventRequest(BaseModel):
    character_id: str
    end_user_id: str | None = None
    device_id: str
    session_id: str
    gesture: str = "none"
    zone: str | None = None
    pressure: float | None = Field(default=None, ge=0.0, le=1.0)
    duration_ms: int | None = Field(default=None, ge=0)

    @field_validator("character_id")
    @classmethod
    def validate_character_id(cls, v: str) -> str:
        return _validate_uuid_format(v)


class TouchEventResponse(BaseModel):
    text: str | None = None
    audio_data: str | None = None
    gesture: str
    intent: str
    emotion_hint: str
    affinity_bonus: int


class ChatRequest(BaseModel):
    character_id: str
    end_user_id: str | None = None
    device_id: str
    session_id: str
    audio_data: str | None = None  # base64 audio
    audio_format: str = "pcm"  # pcm or opus
    text_input: str | None = Field(default=None, max_length=2000)
    history: list[HistoryMessage] | None = None  # conversation history for multi-turn
    # Idle mode: character is alone and speaks spontaneously. No memory
    # writes, no relationship points, no touch consumption.
    idle_mode: bool = False
    idle_state: str = "bored"  # bored | sleepy
    # Caller can decode chunked audio (audio_chunk/audio_end SSE events) for
    # lower time-to-first-audio. Defaults off so non-streaming consumers keep
    # receiving whole-clip-per-sentence audio.
    audio_streaming: bool = False
    # Optional camera frame (base64 JPEG/PNG) captured for this turn. When
    # present it is described by a VLM and injected as visual context; the
    # character may only talk about what the description actually contains.
    image_data: str | None = None

    @field_validator("character_id")
    @classmethod
    def validate_character_id(cls, v: str) -> str:
        return _validate_uuid_format(v)

    @field_validator("audio_data")
    @classmethod
    def validate_audio_size(cls, v: str | None) -> str | None:
        if v is not None:
            # base64 is ~4/3 of raw size; 10MB raw ≈ 13.3MB base64
            max_b64_len = 14_000_000
            if len(v) > max_b64_len:
                raise ValueError("Audio data exceeds 10MB limit")
        return v


class PADStateSchema(BaseModel):
    p: float = 0.0  # Pleasure: -1 (unhappy) → +1 (happy)
    a: float = 0.0  # Arousal: -1 (calm) → +1 (excited)
    d: float = 0.0  # Dominance: -1 (submissive) → +1 (dominant)


class RelationshipAxesSchema(BaseModel):
    affection: int = 0  # 0-1000
    trust: int = 0
    intimacy: int = 0
    comfort: int = 0
    respect: int = 0
    energy: int = 100


class RelationshipStateSchema(BaseModel):
    """Wire shape shared by SSE `relationship`, ChatResponse and GET /relationship."""

    type: str = "relationship"
    stage: str = "STRANGER"
    app_mode: str = "dating_sim"
    axes: RelationshipAxesSchema = Field(default_factory=RelationshipAxesSchema)
    deltas: dict[str, int] = Field(default_factory=dict)
    stage_changed: bool = False
    from_stage: str | None = None
    near_stage: dict | None = None
    days_known: int = 0
    total_interactions: int = 0
    streak_days: int = 0
    behavior: dict | None = None


class ChatResponse(BaseModel):
    text: str
    audio_data: str | None = None  # base64 audio
    emotion: str | None = None  # character's detected emotion state
    pad: PADStateSchema | None = None  # continuous PAD emotional state
    relationship_stage: str | None = None  # STRANGER → SOULMATE (or COMPANION)
    affinity: int | None = None  # 0-1000 (= affection axis)
    relationship: RelationshipStateSchema | None = None
    latency_ms: int
    stages: dict[str, int] | None = None  # per-stage latency breakdown (ms)


class RagDocument(BaseModel):
    text: str = Field(max_length=10000)


class RagIngestRequest(BaseModel):
    character_id: str
    documents: list[str] = Field(max_length=50)

    @field_validator("character_id")
    @classmethod
    def validate_character_id(cls, v: str) -> str:
        return _validate_uuid_format(v)

    @field_validator("documents")
    @classmethod
    def validate_document_lengths(cls, v: list[str]) -> list[str]:
        for i, doc in enumerate(v):
            if len(doc) > 10000:
                raise ValueError(f"Document {i} exceeds 10000 character limit")
        return v


class RagSearchRequest(BaseModel):
    character_id: str
    query: str = Field(max_length=2000)
    top_k: int = Field(default=3, ge=1, le=20)

    @field_validator("character_id")
    @classmethod
    def validate_character_id(cls, v: str) -> str:
        return _validate_uuid_format(v)


class RagSearchResponse(BaseModel):
    results: list[str]
    scores: list[float]
