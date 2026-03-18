"""Emotion State Machine — tracks both character AND user emotions.

Character emotion: detected from LLM output, drives TTS + next turn prompt.
User emotion: detected from user input, lets character "sense" user's mood.
Both persist per session in Redis.
"""

import structlog

from ai_core.services.cache import CacheService

logger = structlog.get_logger()

# ──────────────────────────────────────────────
# Emotion definitions
# ──────────────────────────────────────────────

EMOTIONS = ("happy", "sad", "shy", "angry", "playful", "curious", "worried", "calm")
DEFAULT_EMOTION = "calm"

# Chinese descriptions for character emotion (injected into system prompt)
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

# How character should respond to user's detected mood
USER_MOOD_RESPONSES: dict[str, str] = {
    "happy": "主人现在心情很好，你可以跟着一起开心，分享快乐",
    "sad": "主人似乎有点难过，要温柔地关心主人，安慰但不追问原因",
    "angry": "主人好像有点烦躁，耐心一点，不要火上浇油",
    "worried": "主人好像在担心什么，轻声安慰，告诉主人会没事的",
    "excited": "主人很兴奋！跟着一起激动，多问问是什么好事",
    "tired": "主人好像累了，说话温柔简短一点，不要太闹腾",
    "lonely": "主人可能有点孤单，多陪陪主人，让主人感到温暖",
    "neutral": "",  # no special instruction
}

# Keywords for detecting user's mood from their input
_USER_MOOD_KEYWORDS: dict[str, list[str]] = {
    "happy": [
        "太好了", "好开心", "高兴", "开心", "哈哈", "耶", "棒", "考了100",
        "赢了", "成功", "好消息", "终于", "太棒了", "超开心",
    ],
    "sad": [
        "难过", "伤心", "哭", "不开心", "失败", "没考好", "输了", "被骂",
        "不想", "好烦", "好累", "唉", "呜呜", "委屈", "被欺负",
    ],
    "angry": [
        "生气", "气死了", "烦死了", "讨厌", "可恶", "不公平", "凭什么",
        "受不了", "太过分",
    ],
    "worried": [
        "害怕", "担心", "紧张", "怎么办", "考试", "不敢", "万一",
        "来不及", "完蛋了", "糟糕",
    ],
    "excited": [
        "好期待", "等不及", "终于要", "明天就", "马上就", "兴奋",
        "太期待了", "迫不及待",
    ],
    "tired": [
        "好累", "好困", "好无聊", "没意思", "不想动", "累死了",
        "困死了", "打哈欠",
    ],
    "lonely": [
        "没人陪", "一个人", "孤单", "寂寞", "想你", "没朋友",
        "好无聊", "都不理我",
    ],
    "neutral": [],
}

# TTS modulation offsets per character emotion
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

# Keywords for detecting character emotion from LLM output
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
    "calm": [],
}

_EMOTION_TTL = 1800  # 30 min


class EmotionEngine:
    """Track and manage both character and user emotion state."""

    def __init__(self, cache: CacheService):
        self.cache = cache

    # ── Character emotion (from LLM output) ──

    async def get_emotion(self, session_id: str) -> str:
        if not session_id:
            return DEFAULT_EMOTION
        val = await self.cache.get(f"emotion:{session_id}")
        if val and val in EMOTIONS:
            return val
        return DEFAULT_EMOTION

    async def set_emotion(self, session_id: str, emotion: str) -> None:
        if not session_id or emotion not in EMOTIONS:
            return
        await self.cache.set(f"emotion:{session_id}", emotion, ttl=_EMOTION_TTL)

    def detect_emotion(self, text: str, previous: str = DEFAULT_EMOTION) -> str:
        """Detect character emotion from LLM response."""
        scores: dict[str, int] = {}
        for emotion, keywords in _EMOTION_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[emotion] = score
        if not scores:
            return previous
        return max(scores, key=scores.get)

    # ── User mood (from user input) ──

    async def get_user_mood(self, session_id: str) -> str:
        if not session_id:
            return "neutral"
        val = await self.cache.get(f"user_mood:{session_id}")
        return val if val else "neutral"

    async def set_user_mood(self, session_id: str, mood: str) -> None:
        if not session_id:
            return
        await self.cache.set(f"user_mood:{session_id}", mood, ttl=_EMOTION_TTL)

    def detect_user_mood(self, text: str) -> str:
        """Detect user's mood from their input text."""
        scores: dict[str, int] = {}
        for mood, keywords in _USER_MOOD_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[mood] = score
        if not scores:
            return "neutral"
        return max(scores, key=scores.get)

    def get_user_mood_prompt(self, mood: str) -> str:
        """Get instruction for how character should respond to user's mood."""
        return USER_MOOD_RESPONSES.get(mood, "")

    # ── Prompt + TTS helpers ──

    def get_prompt_text(self, emotion: str) -> str:
        return EMOTION_DESCRIPTIONS.get(emotion, EMOTION_DESCRIPTIONS[DEFAULT_EMOTION])

    def get_tts_offsets(self, emotion: str) -> dict[str, float]:
        return EMOTION_TTS_OFFSETS.get(emotion, EMOTION_TTS_OFFSETS[DEFAULT_EMOTION])

    def apply_tts_offsets(
        self, emotion: str, ssml_pitch: float, ssml_rate: float
    ) -> tuple[float, float]:
        offsets = self.get_tts_offsets(emotion)
        pitch = max(0.5, min(2.0, ssml_pitch + offsets["pitch_offset"]))
        rate = max(0.5, min(2.0, ssml_rate + offsets["rate_offset"]))
        return pitch, rate
