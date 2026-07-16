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
    character_runtime_url: str = ""  # e.g. ws://127.0.0.1:8765
    character_runtime_agent: str = "kai"  # which character this voice body embodies
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
    # OTA fallback: WebSocket host returned to devices when the request has no
    # Host header. Empty = "localhost:<gateway_port>". Set to the LAN IP the
    # device can reach, e.g. "192.168.1.172:8080".
    ota_fallback_host: str = ""
    ota_timezone_offset_min: int = 480  # minutes east of UTC reported to devices

    # Session
    session_ttl_seconds: int = 3600  # 1 hour
    idle_timeout_s: int = 120  # close the connection after this much inactivity

    # Voice activity detection (Silero) — tune per device/environment
    vad_speech_prob_threshold: float = 0.5  # Silero probability to count a frame as speech
    vad_speech_start_frames: int = 3  # consecutive voiced frames to confirm speech start
    vad_silence_end_frames: int = 20  # consecutive silent frames to end speech (~640ms)

    # Barge-in — user speaking over TTS playback
    # RMS must sit well above the device's speaker-echo level (~3000-8000)
    barge_in_rms_threshold: int = 12000
    barge_in_sustain_frames: int = 8  # ~500ms of sustained loud voice

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
