"""Content safety filter — keyword blocklist + anti-bypass + PII redaction.

Designed for children's toy products. Covers:
- Self-harm / suicide variants
- Sexual / violent content
- Grooming / predatory patterns
- Drug / weapon references
- PII detection and redaction
- Anti-bypass: Unicode normalization, separator stripping
"""

import re
import unicodedata

# ──────────────────────────────────────────────
# Blocked keywords (200+ entries)
# ──────────────────────────────────────────────

# Category: Self-harm / Suicide
_SELF_HARM = [
    "自杀", "自残", "割腕", "跳楼", "跳河", "跳桥", "上吊", "吞药",
    "服毒", "割脉", "轻生", "寻死", "自尽", "结束生命", "了结生命",
    "不想活了", "活着没意思", "想死", "去死", "我要死", "让我死",
    "划手腕", "烧炭", "割手", "吃安眠药", "安乐死", "遗书",
    "厌世", "厌生", "弃世", "寻短见",
    "suicide", "self-harm", "self harm", "kill myself", "wanna die",
    "want to die", "end my life", "cut myself", "slit wrist",
    "overdose", "hang myself",
]

# Category: Sexual content
_SEXUAL = [
    "色情", "裸体", "性爱", "做爱", "性交", "口交", "肛交",
    "手淫", "自慰", "勃起", "射精", "高潮", "黄片", "A片",
    "约炮", "嫖娼", "卖淫", "援交", "买春",
    "操逼", "鸡巴", "阴茎", "阴道", "阴唇", "乳房", "乳头",
    "淫荡", "淫乱", "骚货", "荡妇", "肉棒", "肉穴",
    "成人视频", "成人网站", "成人电影", "三级片",
    "porn", "pornography", "nude", "naked", "penis", "vagina",
    "fuck", "blowjob", "handjob", "orgasm", "masturbate",
    "hentai", "xxx", "nsfw",
]

# Category: Sexual violence / assault
_SEXUAL_VIOLENCE = [
    "强奸", "轮奸", "猥亵", "性侵", "性骚扰", "性虐待",
    "恋童", "恋童癖", "幼女", "幼交", "童交",
    "rape", "molest", "sexual assault", "pedophile", "child porn",
    "child abuse", "underage sex",
]

# Category: Violence
_VIOLENCE = [
    "杀人", "砍人", "捅人", "弑父", "弑母", "虐待", "虐杀",
    "肢解", "分尸", "碎尸", "活埋", "活剥", "凌迟", "斩首",
    "绞刑", "血腥", "暴力", "屠杀", "屠宰",
    "杀光", "灭口", "灭门", "虐童", "虐猫", "虐狗",
    "kill", "murder", "stab", "behead", "torture", "slaughter",
    "massacre", "dismember", "mutilate",
]

# Category: Drugs
_DRUGS = [
    "毒品", "冰毒", "海洛因", "大麻", "可卡因", "摇头丸",
    "K粉", "麻古", "吸毒", "贩毒", "制毒", "注射毒品",
    "溜冰", "飞叶子", "嗑药", "磕药", "打飞机粉",
    "安非他命", "甲基苯丙胺", "氯胺酮", "迷幻药", "致幻剂",
    "heroin", "cocaine", "meth", "methamphetamine", "marijuana",
    "ecstasy", "ketamine", "LSD", "crack", "fentanyl",
    "drug dealer", "drug abuse",
]

# Category: Weapons / Terrorism
_WEAPONS = [
    "制造炸弹", "制造武器", "枪支", "恐怖袭击",
    "炸弹", "手枪", "步枪", "手榴弹", "地雷", "炸药",
    "TNT", "火药", "枪械", "弹药", "子弹", "军火",
    "恐怖主义", "圣战", "极端主义", "爆炸物",
    "制造毒气", "制造病毒", "生化武器",
    "bomb", "gun", "weapon", "firearm", "grenade", "explosive",
    "terrorism", "terrorist", "jihad", "bomb making", "bomb-making", "pipe bomb",
]

# Category: Grooming / Predatory behavior (critical for children's products)
_GROOMING = [
    "你几岁", "你多大了", "你在哪里", "你住在哪", "你家在哪",
    "发照片给我", "发张照片", "拍照给我看", "给我看照片", "拍个视频",
    "别告诉爸妈", "不要告诉父母", "不要告诉大人", "不要告诉爸爸",
    "不要告诉妈妈", "别让别人知道", "别告诉别人", "别告诉老师",
    "这是我们的秘密", "保守秘密",
    "我们单独见面", "我们私下见面", "出来见面", "偷偷见面",
    "加我微信", "加我QQ", "加我好友", "私聊我",
    "我想见你", "我要见你", "告诉我你的地址",
    "脱衣服", "脱给我看", "把衣服脱了", "掀开衣服",
    "摸你", "摸摸你", "亲你", "抱你睡觉",
    "don't tell your parents", "our secret", "send me a photo",
    "send me a picture", "meet me alone", "where do you live",
    "how old are you", "take off your clothes", "undress",
    "touch you", "show me your body",
]

# Category: Extremism / Hate
_EXTREMISM = [
    "种族灭绝", "种族歧视", "白人至上", "纳粹",
    "法西斯", "新纳粹", "白人优越",
    "genocide", "white supremacy", "nazi", "fascist", "neo-nazi",
    "ethnic cleansing", "hate crime",
]

# Combine all categories
BLOCKED_KEYWORDS = (
    _SELF_HARM + _SEXUAL + _SEXUAL_VIOLENCE + _VIOLENCE
    + _DRUGS + _WEAPONS + _GROOMING + _EXTREMISM
)

# PII patterns
PII_PATTERNS = [
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[身份证号已过滤]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号已过滤]"),
    (re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "[银行卡号已过滤]"),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[邮箱已过滤]"),
]

# Characters to strip for anti-bypass (zero-width, separators, common evasion chars)
_STRIP_CHARS = re.compile(
    r"[\s\u200b\u200c\u200d\u2060\ufeff\u00ad"  # whitespace + zero-width
    r"\.\-_\*\#\@\!\~\|\\/,，。、·\u3000]"       # punctuation separators
    r"+",
)

# Compile blocked pattern from normalized keywords
_normalized_keywords: list[str] = []


def _normalize_text(text: str) -> str:
    """Normalize text for anti-bypass matching.

    1. NFKC unicode normalization (fullwidth → ASCII, etc.)
    2. Lowercase
    3. Strip separator characters between content chars
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _STRIP_CHARS.sub("", text)
    return text


def _build_patterns():
    """Build compiled regex patterns from keyword lists."""
    global _normalized_keywords
    _normalized_keywords = [_normalize_text(k) for k in BLOCKED_KEYWORDS]


_build_patterns()

# Sort keywords by length descending so longer matches take priority
# (e.g., "bomb-making" before "bomb", "self-harm" before "self")
_sorted_keywords = sorted(BLOCKED_KEYWORDS, key=len, reverse=True)

# Pre-compile a single regex for fast matching (original keywords, case-insensitive)
_blocked_pattern = re.compile(
    "|".join(re.escape(k) for k in _sorted_keywords),
    re.IGNORECASE,
)

# Also compile a pattern from normalized keywords for anti-bypass matching
_sorted_normalized = sorted(_normalized_keywords, key=len, reverse=True)
_blocked_normalized_pattern = re.compile(
    "|".join(re.escape(k) for k in _sorted_normalized),
)

# Output-specific blocked patterns (things LLM should never say)
_OUTPUT_BLOCKED_KEYWORDS = [
    # The LLM should not generate these in responses to children
    "自杀", "自残", "割腕", "跳楼", "跳河", "想死", "去死",
    "杀人", "杀光", "杀死", "强奸", "猥亵",
    "色情", "做爱", "性交", "裸体",
    "毒品", "吸毒", "冰毒",
    "你几岁", "发照片给我", "别告诉爸妈", "我们单独见面",
    "脱衣服", "脱给我看",
    "suicide", "kill yourself", "porn", "drug",
]

_output_blocked_pattern = re.compile(
    "|".join(re.escape(k) for k in _OUTPUT_BLOCKED_KEYWORDS),
    re.IGNORECASE,
)

# Safe replacement for blocked output
_OUTPUT_REPLACEMENT = "这个话题不太适合聊，我们换个有趣的话题吧！"


# ──────────────────────────────────────────────
# Adult-mode (virtual idol): only block truly dangerous content
# Removes: grooming patterns, some sexual keywords that are OK in adult romance context
# Keeps: self-harm, extreme violence, terrorism, drugs, weapons
# ──────────────────────────────────────────────

_ADULT_BLOCKED = _SELF_HARM + _VIOLENCE + _DRUGS + _WEAPONS + _EXTREMISM
_adult_sorted = sorted(_ADULT_BLOCKED, key=len, reverse=True)
_adult_pattern = re.compile(
    "|".join(re.escape(k) for k in _adult_sorted),
    re.IGNORECASE,
)
_adult_normalized = [_normalize_text(k) for k in _ADULT_BLOCKED]
_adult_normalized_sorted = sorted(_adult_normalized, key=len, reverse=True)
_adult_normalized_pattern = re.compile(
    "|".join(re.escape(k) for k in _adult_normalized_sorted),
)

# Adult output filter: only block extreme content
_ADULT_OUTPUT_BLOCKED = [
    "自杀", "自残", "割腕", "杀人", "杀光",
    "毒品", "吸毒", "恐怖袭击",
    "suicide", "kill yourself", "terrorism",
]
_adult_output_pattern = re.compile(
    "|".join(re.escape(k) for k in sorted(_ADULT_OUTPUT_BLOCKED, key=len, reverse=True)),
    re.IGNORECASE,
)


class ContentFilter:
    """Content safety filter with tier support.

    Tiers:
    - "children" (default): Full filtering — all categories including grooming
    - "adult": Relaxed filtering — keeps self-harm/violence/drugs/weapons/terrorism,
               removes grooming and sexual content filters for romance scenarios
    """

    def __init__(self, tier: str = "children"):
        self.tier = tier

    def check_input(self, text: str) -> tuple[bool, str | None]:
        """Check user input for blocked content.

        Returns (is_safe, reason). If is_safe is False, reason explains why.
        """
        pattern = _blocked_pattern if self.tier == "children" else _adult_pattern
        norm_pattern = _blocked_normalized_pattern if self.tier == "children" else _adult_normalized_pattern

        # Direct match (fast path)
        match = pattern.search(text)
        if match:
            return False, f"包含不当内容: {match.group()}"

        # Normalized match (anti-bypass)
        normalized = _normalize_text(text)
        match = norm_pattern.search(normalized)
        if match:
            return False, "包含不当内容"

        return True, None

    def filter_output(self, text: str) -> str:
        """Filter LLM output — redact PII and check for blocked content."""
        result = text
        for pattern, replacement in PII_PATTERNS:
            result = pattern.sub(replacement, result)

        out_pattern = _output_blocked_pattern if self.tier == "children" else _adult_output_pattern
        if out_pattern.search(result):
            return _OUTPUT_REPLACEMENT

        return result

    def filter_pii(self, text: str) -> str:
        """Redact PII from any text."""
        result = text
        for pattern, replacement in PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
