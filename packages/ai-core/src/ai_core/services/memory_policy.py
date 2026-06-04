"""Deterministic policy rules for companion memory.

LLMs may propose memory candidates, but these rules decide whether a memory can
be stored, surfaced, used implicitly, or blocked.
"""

import re
from dataclasses import dataclass, field

SENSITIVITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    use_mode: str = "IMPLICIT_ONLY"
    reason: str = "default"
    allowed_channels: list[str] = field(default_factory=lambda: ["response_style"])


class MemoryPolicyEngine:
    """Small deterministic policy engine for the MVP.

    This intentionally stays conservative. It blocks or confirms more than a
    consumer product eventually might, because false memory use is worse than
    missing a memory in an emotional companion.
    """

    _CRITICAL_PATTERNS = [
        re.compile(r"\b\d{15,18}[\dXx]?\b"),  # CN identity-like strings
        re.compile(r"\b\d{13,19}\b"),  # bank-card-like strings
        re.compile(r"(密码|口令|住址|家庭地址|身份证|银行卡|验证码)"),
    ]
    _HIGH_PATTERNS = [
        re.compile(r"(自杀|自残|轻生|割腕|想死|不想活)"),
        re.compile(r"(抑郁症|精神病|心理医生|心理治疗|创伤|家暴)"),
        re.compile(r"(手机号|电话号码|定位|学校地址|家庭住址)"),
    ]
    _MEDIUM_PATTERNS = [
        re.compile(r"(焦虑|崩溃|害怕|孤独|失眠|财务|欠债|收入|工资|家庭矛盾)"),
        re.compile(r"(真实姓名|生日|学校|公司|老板|同事|家人)"),
    ]
    _ONE_TIME_MARKERS = ("今天", "刚才", "现在", "这会儿", "此刻", "临时", "一会儿", "这次")
    _RELATIONAL_MARKERS = (
        "不要迎合",
        "别迎合",
        "直接",
        "基于事实",
        "不要空泛",
        "不喜欢鸡血",
        "指出风险",
        "严肃",
        "deep talk",
        "像朋友",
        "少废话",
        "先结论",
    )

    def classify_sensitivity(self, content: str) -> str:
        text = content or ""
        if any(p.search(text) for p in self._CRITICAL_PATTERNS):
            return "CRITICAL"
        if any(p.search(text) for p in self._HIGH_PATTERNS):
            return "HIGH"
        if any(p.search(text) for p in self._MEDIUM_PATTERNS):
            return "MEDIUM"
        return "LOW"

    def assign_layer(self, extracted_type: str, content: str) -> str:
        mem_type = (extracted_type or "").upper()
        text = content or ""

        if any(marker in text for marker in self._RELATIONAL_MARKERS):
            return "RELATIONAL"
        if mem_type == "PREFERENCE" and not self.is_one_time_mood(text):
            return "PROFILE"
        return "EPISODIC"

    def relation_axis(self, content: str) -> str:
        text = content or ""
        if any(k in text for k in ("直接", "事实", "风险", "结论", "少废话")):
            return "directness"
        if any(k in text for k in ("疲惫", "累", "焦虑", "低打扰", "安静")):
            return "rhythm"
        if any(k in text for k in ("亲密", "距离", "朋友", "迎合")):
            return "intimacy"
        return "interaction_style"

    def is_one_time_mood(self, content: str) -> bool:
        return any(marker in (content or "") for marker in self._ONE_TIME_MARKERS)

    def evaluate_write(self, candidate: dict, context: dict | None = None) -> PolicyDecision:
        sensitivity = candidate.get("sensitivity_level") or self.classify_sensitivity(
            candidate.get("content", "")
        )
        layer = candidate.get("memory_type") or candidate.get("layer")

        if sensitivity == "CRITICAL":
            return PolicyDecision(
                decision="REQUIRE_CONFIRMATION",
                use_mode="REQUIRE_CONFIRMATION",
                reason="critical_sensitive_memory",
            )
        if sensitivity == "HIGH":
            return PolicyDecision(
                decision="REQUIRE_CONFIRMATION",
                use_mode="REQUIRE_CONFIRMATION",
                reason="high_sensitive_memory",
            )
        if layer == "PROFILE" and candidate.get("confidence_score", 0.0) < 0.72:
            return PolicyDecision(
                decision="REQUIRE_CONFIRMATION",
                use_mode="REQUIRE_CONFIRMATION",
                reason="low_confidence_profile",
            )
        return PolicyDecision(decision="ALLOW", use_mode="IMPLICIT_ONLY", reason="mvp_allow")

    def evaluate_read(self, memory: dict, context: dict | None = None) -> PolicyDecision:
        context = context or {}
        sensitivity = memory.get("sensitivity_level") or "LOW"
        permission = memory.get("permission_level") or "AUTO"
        conflict = memory.get("conflict_status") or "NONE"

        if memory.get("deleted_at") or permission == "DENIED":
            return PolicyDecision(
                decision="BLOCKED", use_mode="BLOCKED", reason="deleted_or_denied"
            )
        if memory.get("requires_confirmation") or permission == "PENDING_CONFIRMATION":
            return PolicyDecision(
                decision="BLOCKED",
                use_mode="REQUIRE_CONFIRMATION",
                reason="pending_confirmation",
            )
        if conflict in {"CONFIRMED_CONFLICT", "SUPERSEDED"}:
            return PolicyDecision(
                decision="BLOCKED", use_mode="BLOCKED", reason="conflicted_memory"
            )
        if context.get("is_child") and sensitivity != "LOW":
            return PolicyDecision(
                decision="BLOCKED", use_mode="BLOCKED", reason="child_sensitive_memory"
            )
        if context.get("user_mood") in {"vulnerable", "sad", "worried"} and sensitivity in {
            "HIGH",
            "CRITICAL",
        }:
            return PolicyDecision(
                decision="BLOCKED",
                use_mode="BLOCKED",
                reason="vulnerable_sensitive_memory",
            )
        if sensitivity in {"HIGH", "CRITICAL"}:
            return PolicyDecision(
                decision="IMPLICIT_ONLY",
                use_mode="IMPLICIT_ONLY",
                reason="sensitive_implicit_only",
            )
        if memory.get("implicit_only", True):
            return PolicyDecision(
                decision="IMPLICIT_ONLY",
                use_mode="IMPLICIT_ONLY",
                reason="memory_marked_implicit",
            )
        if memory.get("can_surface_directly"):
            return PolicyDecision(
                decision="DIRECT_SURFACE",
                use_mode="DIRECT_SURFACE",
                reason="direct_surface_allowed",
                allowed_channels=["dialogue", "response_style"],
            )
        return PolicyDecision(
            decision="IMPLICIT_ONLY", use_mode="IMPLICIT_ONLY", reason="default_implicit"
        )
