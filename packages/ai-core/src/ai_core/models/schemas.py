from pydantic import BaseModel


class PersonalityTraits(BaseModel):
    extrovert: int = 50
    humor: int = 50
    warmth: int = 50
    curiosity: int = 50
    energy: int = 50


class PromptBuildRequest(BaseModel):
    character_id: str
    end_user_id: str | None = None
    user_input: str


class PromptBuildResponse(BaseModel):
    system_prompt: str
    voice_id: str | None = None
    voice_speed: float = 1.0


class ChatRequest(BaseModel):
    character_id: str
    end_user_id: str | None = None
    device_id: str
    session_id: str
    audio_data: str | None = None  # base64 PCM
    text_input: str | None = None


class ChatResponse(BaseModel):
    text: str
    audio_data: str | None = None  # base64 audio
    latency_ms: int


class RagIngestRequest(BaseModel):
    character_id: str
    documents: list[str]


class RagSearchRequest(BaseModel):
    character_id: str
    query: str
    top_k: int = 3


class RagSearchResponse(BaseModel):
    results: list[str]
    scores: list[float]
