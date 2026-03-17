from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://soulforge:soulforge_dev@localhost:5432/soulforge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AI Core service
    ai_core_url: str = "http://localhost:8100"

    # Gateway
    gateway_port: int = 8080

    # Session
    session_ttl_seconds: int = 3600  # 1 hour

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
