from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://soulforge:soulforge_dev@localhost:5432/soulforge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AI Core service
    ai_core_url: str = "http://localhost:8100"

    # SoulForge Character Runtime (Protocol 0.2). When set, user utterances are
    # decided by the ONE Character Runtime — the legacy ai-core /pipeline/chat
    # dialogue path is bypassed so no utterance is ever processed by two LLMs.
    character_runtime_url: str = ""            # e.g. ws://127.0.0.1:8765
    character_runtime_agent: str = "kai"       # which character this voice body embodies
    # Production DB character ids are UUIDs, while Runtime agent ids are names
    # such as "kai". Pin unsolicited perception speech to its physical device.
    character_runtime_voice_device_id: str = ""
    character_runtime_timeout_s: float = 12.0

    # Service token for ai-core authentication
    service_token: str = ""

    # DashScope (for streaming ASR in gateway)
    dashscope_api_key: str = ""

    # Gateway
    gateway_port: int = 8080
    output_audio_gain: float = 1.0

    # Session
    session_ttl_seconds: int = 3600  # 1 hour

    # Life loop — spontaneous idle behavior that makes the toy feel alive
    life_loop_enabled: bool = True
    life_bored_after_s: int = 90  # idle time before soft sounds start
    life_sleepy_after_s: int = 600  # idle time before yawns/drowsy mumbles
    life_asleep_after_s: int = 1200  # idle time before sleeping (soft snores)
    life_night_start_hour: int = 22  # night hours halve the sleepy thresholds
    life_night_end_hour: int = 7
    life_llm_thought_prob: float = 0.25  # chance a bored sound becomes an LLM musing

    # Thinking filler — instant "嗯？" while the LLM thinks, masks latency
    thinking_filler_enabled: bool = True
    thinking_filler_prob: float = 0.6

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
