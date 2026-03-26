from pydantic import field_validator
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
    llm_base_url: str = ""   # Override; empty = use well-known config
    llm_api_key: str = ""    # Override; empty = use dashscope_api_key
    llm_model: str = "qwen2.5-7b-instruct"
    llm_temperature: float = 0.8
    llm_top_p: float = 0.9
    llm_max_tokens: int = 512
    llm_timeout: int = 30  # seconds

    # ─── TTS Provider ───────────────────────────
    tts_provider: str = "dashscope"   # dashscope | fish | edge
    tts_model: str = "cosyvoice-v3-flash"
    tts_timeout: int = 15  # seconds

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
    allowed_origins: str = ""  # Comma-separated list, e.g. "https://app.example.com,http://localhost:3000"

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

    @field_validator("master_secret")
    @classmethod
    def master_secret_not_default(cls, v: str, info) -> str:
        if v == "change-me-in-production":
            env = info.data.get("environment", "development")
            if env == "production":
                raise ValueError(
                    "MASTER_SECRET must not be 'change-me-in-production' in production"
                )
        return v

    @field_validator("auth_secret")
    @classmethod
    def auth_secret_required_in_prod(cls, v: str, info) -> str:
        if not v:
            env = info.data.get("environment", "development")
            if env == "production":
                raise ValueError("AUTH_SECRET is required in production")
        return v

    @field_validator("service_token")
    @classmethod
    def service_token_required_in_prod(cls, v: str, info) -> str:
        if not v:
            env = info.data.get("environment", "development")
            if env == "production":
                raise ValueError("SERVICE_TOKEN is required in production")
        return v

    def get_allowed_origins(self) -> list[str]:
        """Parse allowed_origins into a list."""
        if not self.allowed_origins:
            if self.environment == "production":
                return []  # No origins allowed if not configured in prod
            return ["http://localhost:3000", "http://localhost:5173"]  # Dev defaults
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
