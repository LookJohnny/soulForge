"""LLM-to-physical behavior planner.

The LLM is allowed to choose high-level behavior templates, not raw servo
angles. This keeps physical planning expressive while preserving deterministic
safety and scheduling downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.action_units import DEFAULT_ACTION_TEMPLATES
from engine.intent import Intent, Priority


PHYSICAL_PLANNER_PROMPT = """\
You may plan physical behavior only by selecting one of these safe templates:
- idle_scan: quiet autonomous scanning and breathing-like motion.
- look_at_user: turn attention toward the user.
- listening_nod: small nod while listening.
- happy_wiggle: short delighted body/head wiggle.
- greeting_wave: friendly wave/greeting gesture.
- daily_stretch: slow self-initiated stretch.

Return physical planning metadata inside the structured JSON response:
"physical": {
  "action_template_id": "look_at_user",
  "source": "reactive",
  "priority": "REACTIVE",
  "preemptible": false,
  "reason": "user interrupted while the character was idling"
}

Never output servo angles, PWM values, raw motor speeds, or unbounded movement.
"""


TEMPLATE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("look_at_user", ("看向", "望向", "转头", "look at", "turn to", "face user", "attention")),
    ("listening_nod", ("点头", "nod", "listening", "倾听", "嗯嗯", "回应")),
    ("greeting_wave", ("挥手", "招手", "wave", "hello", "greet", "打招呼")),
    ("daily_stretch", ("伸懒腰", "stretch", "打哈欠", "yawn", "舒展")),
    ("happy_wiggle", ("摇晃", "wiggle", "waddle", "bounce", "开心地晃", "雀跃")),
)


@dataclass
class BehaviorPlan:
    action_template_id: str
    source: str
    priority: Priority
    preemptible: bool
    reason: str = ""
    confidence: float = 0.5
    llm_explicit: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_intent(self, payload: dict[str, Any] | None = None) -> Intent:
        merged_payload = dict(payload or {})
        merged_payload["behavior_plan"] = {
            "action_template_id": self.action_template_id,
            "source": self.source,
            "priority": self.priority.name,
            "preemptible": self.preemptible,
            "reason": self.reason,
            "confidence": self.confidence,
            "llm_explicit": self.llm_explicit,
        }
        return Intent.create(
            source=self.source,
            action_template_id=self.action_template_id,
            payload=merged_payload,
            priority=self.priority,
            preemptible=self.preemptible,
            ttl_ms=0,
        )


class LLMBehaviorPlanner:
    """Translate structured LLM output into a safe physical Intent."""

    def __init__(self, templates: dict | None = None):
        self.templates = templates or DEFAULT_ACTION_TEMPLATES

    def prompt_contract(self) -> str:
        return PHYSICAL_PLANNER_PROMPT

    def plan(self, response: Any, context: dict[str, Any] | None = None) -> BehaviorPlan:
        data = self._normalize_response(response)
        ctx = context or {}

        explicit = self._explicit_physical(data)
        if explicit is not None:
            return explicit

        action_text = " ".join(
            str(data.get(key) or "")
            for key in ("action", "dialogue", "thought", "stance")
        ).lower()
        source = self._infer_source(data, ctx)
        priority = self._priority_for_source(source)
        template_id = self._infer_template(action_text, data, ctx)

        return BehaviorPlan(
            action_template_id=template_id,
            source=source,
            priority=priority,
            preemptible=(source != "reactive"),
            reason="deterministic_fallback_from_structured_response",
            confidence=0.62,
            llm_explicit=False,
            raw=data,
        )

    def to_intent(self, response: Any, context: dict[str, Any] | None = None) -> Intent:
        plan = self.plan(response, context=context)
        return plan.to_intent(payload=self._normalize_response(response))

    def _explicit_physical(self, data: dict[str, Any]) -> BehaviorPlan | None:
        raw = data.get("physical") or data.get("behavior_plan") or data.get("motion_plan")
        if not isinstance(raw, dict):
            return None

        template_id = str(raw.get("action_template_id") or raw.get("template") or "").strip()
        if template_id not in self.templates:
            return None

        source = str(raw.get("source") or "plan").lower()
        priority = self._parse_priority(raw.get("priority"), self._priority_for_source(source))
        preemptible = bool(raw.get("preemptible", source != "reactive"))
        confidence = _float(raw.get("confidence"), default=0.85, lo=0.0, hi=1.0)

        return BehaviorPlan(
            action_template_id=template_id,
            source=source,
            priority=priority,
            preemptible=preemptible,
            reason=str(raw.get("reason") or "llm_explicit_physical_plan"),
            confidence=confidence,
            llm_explicit=True,
            raw=raw,
        )

    def _infer_template(self, action_text: str, data: dict[str, Any], context: dict[str, Any]) -> str:
        for template_id, keywords in TEMPLATE_KEYWORDS:
            if any(keyword in action_text for keyword in keywords):
                return template_id

        pad = _pad_dict(data.get("pad"))
        p, a, d = pad.get("p", 0.0), pad.get("a", 0.0), pad.get("d", 0.0)
        event_type = str(context.get("event_type") or data.get("event_type") or "").lower()

        if event_type in {"user_interrupt", "voice", "touch", "proximity"}:
            return "look_at_user"
        if p > 0.35 and a > 0.35:
            return "happy_wiggle"
        if a < -0.25:
            return "idle_scan"
        if d < -0.35:
            return "listening_nod"
        return "idle_scan"

    def _infer_source(self, data: dict[str, Any], context: dict[str, Any]) -> str:
        explicit = str(data.get("source") or context.get("source") or "").lower()
        if explicit in {"idle", "plan", "reactive"}:
            return explicit

        event_type = str(context.get("event_type") or data.get("event_type") or "").lower()
        if event_type in {"user_interrupt", "voice", "touch", "proximity", "barge_in"}:
            return "reactive"
        if event_type in {"timer", "reflection", "scheduled", "proactive"}:
            return "plan"
        return "plan" if (data.get("dialogue") or data.get("action")) else "idle"

    def _priority_for_source(self, source: str) -> Priority:
        if source == "reactive":
            return Priority.REACTIVE
        if source == "idle":
            return Priority.IDLE
        return Priority.PLAN

    def _parse_priority(self, value: Any, default: Priority) -> Priority:
        if isinstance(value, Priority):
            return value
        if isinstance(value, int):
            try:
                return Priority(value)
            except ValueError:
                return default
        text = str(value or "").upper()
        return Priority.__members__.get(text, default)

    def _normalize_response(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return dict(response)
        data = {}
        for key in ("dialogue", "action", "thought", "stance", "pad", "voice"):
            if hasattr(response, key):
                value = getattr(response, key)
                if key == "pad":
                    value = _pad_dict(value)
                data[key] = value
        return data


def _pad_dict(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        return {
            "p": _float(value.get("p"), default=0.0, lo=-1.0, hi=1.0),
            "a": _float(value.get("a"), default=0.0, lo=-1.0, hi=1.0),
            "d": _float(value.get("d"), default=0.0, lo=-1.0, hi=1.0),
        }
    return {
        "p": _float(getattr(value, "p", 0.0), default=0.0, lo=-1.0, hi=1.0),
        "a": _float(getattr(value, "a", 0.0), default=0.0, lo=-1.0, hi=1.0),
        "d": _float(getattr(value, "d", 0.0), default=0.0, lo=-1.0, hi=1.0),
    }


def _float(value: Any, *, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lo, min(hi, parsed))
