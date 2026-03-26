"""Emotion State Machine — tracks both character AND user emotions.

Character emotion: detected from LLM output, drives TTS + next turn prompt.
User emotion: detected from user input, lets character "sense" user's mood.
Both persist per session in Redis.

PAD integration: internally uses continuous PAD (Pleasure-Arousal-Dominance)
space for smooth transitions, while exposing discrete emotion labels for
backward compatibility with prompts, TTS, and API responses.
"""

import re
import structlog

from ai_core.services.cache import CacheService
from ai_core.services.pad_model import (
    PADEngine, PADState,
    pad_to_emotion, emotion_to_pad,
    pad_to_tts_offsets, pad_to_prompt_description,
    TOUCH_PAD_IMPULSE,
)

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

# Legacy mood responses (kept for backward compat; prefer PersonaContext.mood_response())
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

# Weighted keywords for detecting character emotion from LLM output.
# Format: (keyword, weight). Higher weight = stronger signal.
# Keywords are exclusive to one emotion to eliminate cross-contamination.
_EMOTION_KEYWORDS_WEIGHTED: dict[str, list[tuple[str, float]]] = {
    "happy": [
        ("好开心", 3), ("太棒了", 3), ("好耶", 3), ("超开心", 3), ("万岁", 2),
        ("开心", 2), ("高兴", 2), ("快乐", 2), ("真棒", 2), ("好极了", 2),
        ("太好了", 2), ("哈哈", 1.5), ("耶", 1.5), ("超棒", 1.5), ("真好", 1),
    ],
    "sad": [
        ("好难过", 3), ("好伤心", 3), ("呜呜呜", 3),
        ("难过", 2), ("伤心", 2), ("不开心", 2), ("失落", 2), ("沮丧", 2), ("哭", 2),
        ("好可惜", 1.5), ("叹气", 1.5), ("呜呜", 1.5), ("唉", 1.5), ("心疼", 1.5), ("呜", 1),
    ],
    "shy": [
        ("好害羞", 3), ("脸红了", 3), ("扭扭捏捏", 3),
        ("害羞", 2), ("不好意思", 2), ("捂脸", 2),
        ("人家", 1.5), ("讨厌啦", 1.5), ("哎呀", 1),
    ],
    "angry": [
        ("气死了", 3), ("烦死了", 3), ("可恶", 3),
        ("生气", 2), ("不理你", 2), ("好气", 2),
        ("哼", 1), ("讨厌", 1),
    ],
    "playful": [
        ("逗你玩", 3), ("骗你的", 3), ("才怪", 3),
        ("猜猜看", 2), ("调皮", 2), ("捣蛋", 2), ("偷笑", 2), ("坏笑", 2),
        ("嘻嘻", 1.5), ("嘿嘿", 1.5), ("猜猜", 1.5), ("才不", 1),
    ],
    "curious": [
        ("好好奇", 3), ("想知道", 3), ("详细说说", 3),
        ("好奇", 2), ("真的吗", 2), ("然后呢", 2), ("后来呢", 2),
        ("是什么", 1.5), ("什么意思", 1.5), ("讲讲", 1),
    ],
    "worried": [
        ("好担心", 3), ("没事吧", 3), ("还好吗", 3), ("别哭", 3), ("别难过", 3),
        ("担心", 2), ("不要紧", 2), ("保重", 2), ("当心", 2),
        ("小心", 1.5), ("注意", 1),
    ],
    "calm": [],
}

# Negation prefixes that flip the emotion of the following keyword.
# e.g. "别难过" → the speaker is comforting, not sad → maps to "worried"
# e.g. "不开心" is already a keyword for "sad" so it's handled directly
_NEGATION_PREFIXES = ("别", "不要", "不用", "不必", "别再", "不会")

# When a negative context is detected around a keyword, remap to this emotion
_NEGATION_REMAP: dict[str, str] = {
    "sad": "worried",      # "别难过" → character is comforting (worried about user)
    "angry": "worried",    # "别生气" → character is calming
    "scared": "worried",   # "别害怕" → character is reassuring
}

# Legacy flat keyword list (for backward compat with existing tests)
_EMOTION_KEYWORDS: dict[str, list[str]] = {
    emotion: [kw for kw, _ in pairs]
    for emotion, pairs in _EMOTION_KEYWORDS_WEIGHTED.items()
}

_EMOTION_TTL = 1800  # 30 min

# Regex to extract inline emotion tag from LLM output: [emotion:happy]
_INLINE_EMOTION_RE = re.compile(r"\[emotion:\s*(happy|sad|shy|angry|playful|curious|worried|calm)\s*\]", re.IGNORECASE)


def extract_inline_emotion(text: str) -> tuple[str, str | None]:
    """Extract [emotion:xxx] tag from LLM output.

    Returns:
        (cleaned_text, emotion_or_none)
        cleaned_text has the tag stripped; emotion is the detected label or None.
    """
    match = _INLINE_EMOTION_RE.search(text)
    if match:
        emotion = match.group(1).lower()
        cleaned = text[:match.start()].rstrip() + text[match.end():]
        return cleaned.strip(), emotion
    return text, None


class EmotionEngine:
    """Track and manage both character and user emotion state.

    Supports two modes:
    - Legacy: discrete emotion labels (get_emotion/set_emotion/detect_emotion)
    - PAD:    continuous 3D space with smooth transitions (update_with_pad)

    PAD mode is opt-in per call. All legacy methods remain unchanged,
    so existing code works without modification.
    """

    def __init__(self, cache: CacheService):
        self.cache = cache
        self.pad = PADEngine(cache)

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

    def detect_emotion(
        self,
        text: str,
        previous: str = DEFAULT_EMOTION,
        user_mood: str | None = None,
    ) -> str:
        """Detect character emotion from LLM response.

        Improvements over naive keyword matching:
        1. Weighted keywords — strong signals (好开心) score 3x vs weak ones (耶) 1x
        2. Negation awareness — "别难过" maps to worried (comforting), not sad
        3. User mood empathy — if user is sad and no strong signal detected,
           the character should lean toward worried (empathy)
        4. No keyword overlap — each keyword belongs to exactly one emotion
        """
        scores: dict[str, float] = {}

        for emotion, kw_pairs in _EMOTION_KEYWORDS_WEIGHTED.items():
            for kw, weight in kw_pairs:
                pos = text.find(kw)
                if pos == -1:
                    continue

                # Check for negation prefix before the keyword
                actual_emotion = emotion
                prefix_region = text[max(0, pos - 4):pos]
                if any(prefix_region.endswith(neg) for neg in _NEGATION_PREFIXES):
                    actual_emotion = _NEGATION_REMAP.get(emotion, emotion)

                scores[actual_emotion] = scores.get(actual_emotion, 0) + weight

        if not scores:
            # No keywords matched — use user mood empathy as fallback
            if user_mood and user_mood != "neutral":
                empathy_map = {
                    "happy": "happy", "excited": "happy",
                    "sad": "worried", "lonely": "worried",
                    "angry": "worried", "worried": "worried",
                    "tired": "calm",
                }
                return empathy_map.get(user_mood, previous)
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

    # ── Touch-based emotion influence ──

    def apply_touch_influence(self, current_emotion: str, touch_emotion_hint: str) -> str:
        """Blend current emotion with touch-suggested emotion.

        Touch is a strong signal — if current emotion is calm/neutral,
        touch hint takes priority. Otherwise, certain touch emotions
        can override (e.g., hug when character is playful → worried).
        """
        if not touch_emotion_hint or touch_emotion_hint not in EMOTIONS:
            return current_emotion

        # If current emotion is neutral, adopt touch hint
        if current_emotion in ("calm",):
            return touch_emotion_hint

        # Touch "worried" (from hug/squeeze) overrides light emotions
        if touch_emotion_hint == "worried" and current_emotion in ("playful", "curious", "happy"):
            return "worried"

        # Touch "playful" (from poke/shake) overrides calm/worried
        if touch_emotion_hint == "playful" and current_emotion in ("calm", "worried"):
            return "playful"

        # Otherwise keep current emotion
        return current_emotion

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

    # ── LLM-assisted emotion detection ──

    async def detect_emotion_llm(
        self,
        ai_text: str,
        user_text: str,
        previous: str = DEFAULT_EMOTION,
    ) -> str:
        """Use LLM to classify emotion — more accurate than keyword matching.

        Sends a lightweight classification prompt to the LLM.
        Falls back to keyword detection if LLM call fails.
        """
        from ai_core.dependencies import get_llm_client

        prompt = (
            "你是一个情绪分析器。根据对话判断AI角色当前的情绪状态。\n"
            "只能返回以下8个情绪之一，不要返回其他内容：\n"
            "happy, sad, shy, angry, playful, curious, worried, calm\n\n"
            f"用户说：{user_text}\n"
            f"角色回复：{ai_text}\n\n"
            "角色当前的情绪是："
        )

        try:
            llm = await get_llm_client()
            result = await llm.chat(
                system_prompt="你是情绪分类器，只输出一个英文情绪词。",
                user_input=prompt,
            )
            # Extract the emotion label from LLM response
            result = result.strip().lower().rstrip("。.，, ")
            # Handle cases like "happy。" or "角色当前的情绪是happy"
            for emotion in EMOTIONS:
                if emotion in result:
                    return emotion
            # LLM returned something unexpected, fall back
            logger.warning("emotion_llm.unexpected", result=result[:50])
        except Exception as e:
            logger.warning("emotion_llm.failed", error=str(e))

        # Fallback to keyword detection
        return self.detect_emotion(ai_text, previous=previous, user_mood=None)

    # ── PAD-based methods (smooth continuous transitions) ──

    async def update_with_pad(
        self,
        session_id: str,
        text_emotion: str | None = None,
        touch_gesture: str | None = None,
        user_mood: str | None = None,
        personality: dict | None = None,
        relationship_stage: str | None = None,
    ) -> tuple[PADState, str]:
        """Update emotion via PAD model with personality-aware multi-modal fusion.

        Args:
            session_id: Session ID.
            text_emotion: Discrete emotion from LLM text detection.
            touch_gesture: Touch gesture name (e.g. "hug").
            user_mood: Detected user mood (e.g. "sad").
            personality: Character's 5-trait dict (for baseline computation).
            relationship_stage: STRANGER→BESTFRIEND (scales touch/empathy weights).

        Returns:
            (pad_state, discrete_emotion_label)
        """
        pad_state, discrete = await self.pad.update(
            session_id=session_id,
            text_emotion=text_emotion,
            touch_gesture=touch_gesture,
            user_mood=user_mood,
            personality=personality,
            relationship_stage=relationship_stage,
        )
        # Keep discrete emotion cache in sync for backward compatibility
        await self.set_emotion(session_id, discrete)
        return pad_state, discrete

    async def get_pad_state(self, session_id: str) -> PADState:
        """Get current PAD state for a session."""
        return await self.pad.get_pad(session_id)

    def apply_tts_offsets_pad(
        self, pad_state: PADState, ssml_pitch: float, ssml_rate: float
    ) -> tuple[float, float]:
        """Apply TTS offsets computed from PAD state (more nuanced than discrete)."""
        offsets = pad_to_tts_offsets(pad_state)
        pitch = max(0.5, min(2.0, ssml_pitch + offsets["pitch_offset"]))
        rate = max(0.5, min(2.0, ssml_rate + offsets["rate_offset"]))
        return pitch, rate

    def get_prompt_text_pad(self, pad_state: PADState) -> str:
        """Generate emotion description from PAD state (more nuanced than discrete)."""
        return pad_to_prompt_description(pad_state)
