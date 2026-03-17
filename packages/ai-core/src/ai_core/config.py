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
    llm_max_tokens: int = 256

    # ─── TTS Provider ───────────────────────────
    tts_provider: str = "dashscope"
    tts_model: str = "cosyvoice-v1"

    # ─── ASR Provider ───────────────────────────
    asr_provider: str = "dashscope"
    asr_model: str = "paraformer-realtime-v2"

    # RAG
    rag_top_k: int = 3
    rag_score_threshold: float = 0.7
    rag_embedding_model: str = "text-embedding-v3"
    rag_embedding_dim: int = 1024

    # ─── Encryption (Sprint 3) ──────────────────
    master_secret: str = "change-me-in-production"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
