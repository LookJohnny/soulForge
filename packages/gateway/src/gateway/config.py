from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://soulforge:soulforge_dev@localhost:5432/soulforge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AI Core service
    ai_core_url: str = "http://localhost:8100"

    # Service token for ai-core authentication
    service_token: str = ""

    # Gateway
    gateway_port: int = 8080

    # Session
    session_ttl_seconds: int = 3600  # 1 hour

    # CORS
    allowed_origins: str = ""  # Comma-separated, e.g. "https://app.example.com"

    # Environment
    environment: str = "development"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def get_allowed_origins(self) -> list[str]:
        if not self.allowed_origins:
            if self.environment == "production":
                return []
            return ["http://localhost:3000", "http://localhost:5173"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
