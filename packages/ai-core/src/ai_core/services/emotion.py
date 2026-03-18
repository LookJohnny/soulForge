"""Emotion State Machine — tracks character emotion across conversation turns.

Emotions persist per session in Redis. Each LLM response is analyzed with
a lightweight keyword classifier (no extra LLM call). Detected emotion
influences the next turn's system prompt and TTS voice parameters.
"""

import structlog

from ai_core.services.cache import CacheService

logger = structlog.get_logger()

# ──────────────────────────────────────────────
# Emotion definitions
# ──────────────────────────────────────────────

EMOTIONS = ("happy", "sad", "shy", "angry", "playful", "curious", "worried", "calm")
DEFAULT_EMOTION = "calm"

# Chinese descriptions injected into the system prompt
EMOTION_DESCRIPTIONS: dict[str, str] = {
    "happy": "你现在心情很好，语气轻快愉悦",
    "sad": "你现在有点难过，语气低落柔软",
    "shy": "你现在有点害羞，说话吞吞吐吐，声音小小的",
    "angry": "你现在有点生气，语气强硬但不攻击人",
    "playful": "你现在很调皮，喜欢逗人玩",
    "curious": "你现在充满好奇，会追问细节",
    "worried": "你现在有点担心，语气温柔关切",
    "calm": "你现在很平静，语气沉稳温和",
}

# TTS modulation offsets per emotion (applied to ssml_pitch and ssml_rate)
EMOTION_TTS_OFFSETS: dict[str, dict[str, float]] = {
    "happy": {"pitch_offset": 0.08, "rate_offset": 0.05},
    "sad": {"pitch_offset": -0.08, "rate_offset": -0.08},
    "shy": {"pitch_offset": -0.03, "rate_offset": -0.05},
    "angry": {"pitch_offset": 0.05, "rate_offset": 0.03},
    "playful": {"pitch_offset": 0.06, "rate_offset": 0.06},
    "curious": {"pitch_offset": 0.04, "rate_offset": 0.0},
    "worried": {"pitch_offset": -0.02, "rate_offset": -0.03},
    "calm": {"pitch_offset": 0.0, "rate_offset": 0.0},
}

# Keyword sets for rule-based emotion detection (Chinese)
_EMOTION_KEYWORDS: dict[str, list[str]] = {
    "happy": [
        "开心", "太好了", "哈哈", "真棒", "耶", "好开心", "高兴", "快乐",
        "嘻嘻", "太棒了", "好耶", "超棒", "真好", "好极了", "万岁",
    ],
    "sad": [
        "难过", "伤心", "呜呜", "不开心", "好可惜", "唉", "可怜", "心疼",
        "好难过", "失落", "沮丧", "叹气", "呜",
    ],
    "shy": [
        "害羞", "不好意思", "嘿嘿", "人家", "讨厌啦", "哎呀", "羞",
        "脸红", "扭扭捏捏", "捂脸",
    ],
    "angry": [
        "生气", "哼", "讨厌", "不理你", "气死", "好气", "烦死了",
        "可恶", "哼哼",
    ],
    "playful": [
        "嘿嘿", "猜猜", "逗你", "骗你的", "才不", "哼哼", "捣蛋",
        "嘻嘻", "偷笑", "坏笑", "调皮", "才怪",
    ],
    "curious": [
        "为什么", "怎么", "真的吗", "好奇", "想知道", "是什么", "讲讲",
        "然后呢", "后来呢", "什么意思", "详细说说",
    ],
    "worried": [
        "担心", "小心", "注意", "别", "没事吧", "还好吗", "不要紧",
        "会不会", "万一", "保重", "当心",
    ],
    "calm": [],  # default fallback
}

# Session TTL for emotion state (30 minutes)
_EMOTION_TTL = 1800


class EmotionEngine:
    """Track and manage character emotion state across conversation turns."""

    def __init__(self, cache: CacheService):
        self.cache = cache

    async def get_emotion(self, session_id: str) -> str:
        """Get current emotion state from Redis. Defaults to 'calm'."""
        if not session_id:
            return DEFAULT_EMOTION
        val = await self.cache.get(f"emotion:{session_id}")
        if val and val in EMOTIONS:
            return val
        return DEFAULT_EMOTION

    async def set_emotion(self, session_id: str, emotion: str) -> None:
        """Store emotion state in Redis with session TTL."""
        if not session_id or emotion not in EMOTIONS:
            return
        await self.cache.set(f"emotion:{session_id}", emotion, ttl=_EMOTION_TTL)

    def detect_emotion(self, text: str, previous: str = DEFAULT_EMOTION) -> str:
        """Detect emotion from LLM response text using keyword scoring.

        If no keywords match, retains the previous emotion (inertia).
        """
        scores: dict[str, int] = {}
        for emotion, keywords in _EMOTION_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[emotion] = score

        if not scores:
            return previous  # emotional inertia

        return max(scores, key=scores.get)

    def get_prompt_text(self, emotion: str) -> str:
        """Get the Chinese description for system prompt injection."""
        return EMOTION_DESCRIPTIONS.get(emotion, EMOTION_DESCRIPTIONS[DEFAULT_EMOTION])

    def get_tts_offsets(self, emotion: str) -> dict[str, float]:
        """Get TTS pitch/rate offsets for the given emotion."""
        return EMOTION_TTS_OFFSETS.get(emotion, EMOTION_TTS_OFFSETS[DEFAULT_EMOTION])

    def apply_tts_offsets(
        self, emotion: str, ssml_pitch: float, ssml_rate: float
    ) -> tuple[float, float]:
        """Apply emotion-based offsets to TTS parameters, clamped to valid range."""
        offsets = self.get_tts_offsets(emotion)
        pitch = max(0.5, min(2.0, ssml_pitch + offsets["pitch_offset"]))
        rate = max(0.5, min(2.0, ssml_rate + offsets["rate_offset"]))
        return pitch, rate
