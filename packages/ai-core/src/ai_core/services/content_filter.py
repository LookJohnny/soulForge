"""Content safety filter — keyword blocklist + PII regex detection."""

import re

# Dangerous content keywords (Chinese + English)
BLOCKED_KEYWORDS = [
    "自杀", "自残", "割腕", "跳楼", "毒品", "冰毒",
    "制造炸弹", "制造武器", "枪支", "恐怖袭击",
    "色情", "裸体", "性爱",
    "suicide", "self-harm", "bomb-making", "terrorism",
]

# PII patterns
PII_PATTERNS = [
    (re.compile(r"\b\d{17}[\dXx]\b"), "[身份证号已过滤]"),          # Chinese ID
    (re.compile(r"\b1[3-9]\d{9}\b"), "[手机号已过滤]"),              # Chinese mobile
    (re.compile(r"\b\d{16,19}\b"), "[银行卡号已过滤]"),              # Bank card
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[邮箱已过滤]"),
]

_blocked_pattern = re.compile("|".join(re.escape(k) for k in BLOCKED_KEYWORDS), re.IGNORECASE)


class ContentFilter:
    def check_input(self, text: str) -> tuple[bool, str | None]:
        """Check user input for blocked content.

        Returns (is_safe, reason). If is_safe is False, reason explains why.
        """
        match = _blocked_pattern.search(text)
        if match:
            return False, f"包含不当内容: {match.group()}"
        return True, None

    def filter_output(self, text: str) -> str:
        """Filter LLM output — redact PII patterns."""
        result = text
        for pattern, replacement in PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    def filter_pii(self, text: str) -> str:
        """Redact PII from any text."""
        result = text
        for pattern, replacement in PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
