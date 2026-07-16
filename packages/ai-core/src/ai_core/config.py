from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://soulforge:soulforge_dev@localhost:5432/soulforge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_use_ssl: bool = False

    # DashScope (legacy, used as fallback API key)
    dashscope_api_key: str = ""

    # ─── LLM Provider ───────────────────────────
    llm_provider: str = "dashscope"
    llm_base_url: str = ""  # Override; empty = use well-known config
    llm_api_key: str = ""  # Override; empty = use dashscope_api_key
    llm_model: str = "qwen2.5-7b-instruct"
    llm_temperature: float = 0.8
    llm_top_p: float = 0.9
    llm_max_tokens: int = 512
    llm_timeout: int = 30  # seconds

    # ─── TTS Provider ───────────────────────────
    tts_provider: str = "dashscope"  # dashscope | fish | edge
    tts_model: str = "cosyvoice-v3-flash"
    tts_timeout: int = 15  # seconds
    # Stream TTS audio chunk-by-chunk to the device (lower time-to-first-audio).
    # Only applies when the provider supports streaming AND the caller opts in
    # (ChatRequest.audio_streaming). Kill-switch: set false to force the
    # legacy whole-clip-per-sentence behaviour.
    tts_streaming: bool = True

    # ─── Fish Audio ────────────────────────────
    fish_audio_api_key: str = ""
    fish_audio_model: str = "s1"  # s1 | s2-pro

    # ─── ASR Provider ───────────────────────────
    asr_provider: str = "dashscope"
    asr_model: str = "paraformer-realtime-v2"
    asr_timeout: int = 10  # seconds

    # RAG
    rag_top_k: int = 3
    rag_score_threshold: float = 0.7
    rag_embedding_model: str = "text-embedding-v3"
    rag_embedding_dim: int = 1024

    # ─── Encryption (Sprint 3) ──────────────────
    master_secret: str = "change-me-in-production"

    # ─── Auth ───────────────────────────────────
    auth_secret: str = ""  # NextAuth AUTH_SECRET (shared with admin-web)
    service_token: str = ""  # Internal service-to-service token (gateway → ai-core)

    # ─── CORS ───────────────────────────────────
    allowed_origins: str = (
        ""  # Comma-separated list, e.g. "https://app.example.com,http://localhost:3000"
    )

    # ─── Rate Limiting ──────────────────────────
    rate_limit_chat: str = "30/minute"
    rate_limit_tts: str = "20/minute"
    rate_limit_default: str = "60/minute"

    # ─── Environment ────────────────────────────
    environment: str = "development"  # "development" | "production"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("dashscope_api_key")
    @classmethod
    def dashscope_key_not_empty(cls, v: str, info) -> str:
        # Allow empty in development, but warn
        if not v:
            import warnings

            warnings.warn("DASHSCOPE_API_KEY is empty — LLM/TTS/ASR calls will fail", stacklevel=2)
        return v

    @model_validator(mode="after")
    def production_secrets_must_be_set(self) -> "Settings":
        """Refuse to boot production with default/dev credentials.

        NOTE: must be a model_validator — the old per-field validators read
        ``info.data["environment"]`` before that field was validated (it is
        declared later in the class), so they silently never fired.
        """
        if self.environment != "production":
            return self

        problems: list[str] = []
        if self.master_secret == "change-me-in-production":
            problems.append("MASTER_SECRET must not be the default value")
        if not self.auth_secret:
            problems.append("AUTH_SECRET is required")
        if not self.service_token:
            problems.append("SERVICE_TOKEN is required")
        if self.minio_access_key == "minioadmin" or self.minio_secret_key == "minioadmin":
            problems.append("MINIO_ACCESS_KEY/MINIO_SECRET_KEY must not be the default")
        if "soulforge:soulforge_dev@" in self.database_url:
            problems.append("DATABASE_URL must not use the dev credentials")
        if problems:
            raise ValueError("production config: " + "; ".join(problems))
        return self

    def get_allowed_origins(self) -> list[str]:
        """Parse allowed_origins into a list."""
        if not self.allowed_origins:
            if self.environment == "production":
                return []  # No origins allowed if not configured in prod
            return ["http://localhost:3000", "http://localhost:5173"]  # Dev defaults
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
