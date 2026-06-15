"""Companion plan-reaction loop primitives.

This is the low-cost rules layer for Phase 3. It decides whether a device
event deserves an immediate companion reaction before any LLM call is made.
The output is intentionally close to the future ActionPlan DSL shape so the
Gateway can consume it or pass it to a richer planner later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_DEFAULT_VOCALIZATIONS = {
    "ack": "嗯嗯。",
    "comfort": "呜...嗯。",
    "boundary": "呀！呜...",
    "low_power": "呜...",
    "timer": "叮~",
}

_VERBAL_VARIANTS = {
    "battery_low": {
        "default": "我电量有点低啦，我先省点力气，安静陪你一会儿。",
        "cool": "电量有点低了，我先省点力气。",
        "bright": "我电量有点低啦，先安静省点力气！",
    },
    "battery_critical": {
        "default": "我快没电了，先进入省电模式，等充好电再继续陪你。",
        "cool": "快没电了，我先进入省电模式。",
        "bright": "我快没电啦，先省电，充好再继续陪你！",
    },
    "hardware_failure": {
        "default": "我今天动作小一点，但还在这里陪你。",
        "cool": "我今天动作小一点，还在。",
        "bright": "我今天动作小一点，不过还在这里陪你！",
    },
    "interrupt": {
        "default": "嗯，我听你说。",
        "cool": "我听。",
        "bright": "嗯嗯！你说。",
    },
    "hug": {
        "default": "收到这个抱抱啦，我在这里陪你。",
        "cool": "收到。我在。",
        "bright": "收到抱抱！我在这里！",
    },
    "hug_low": {
        "default": "嗯，我在。",
        "cool": "我在。",
        "bright": "嗯嗯，我在！",
    },
    "rough_touch": {
        "default": "慢一点，我会有点晕。我们轻轻来。",
        "cool": "轻一点。我会有点晕。",
        "bright": "慢一点点，我会有点晕，我们轻轻来！",
    },
    "gentle_touch": {
        "default": "嘿嘿。",
        "cool": "嗯。",
        "bright": "嘿嘿！",
    },
    "silence_low": {
        "default": "我先不打扰你，想说话的时候我在。",
        "cool": "我先不打扰。想说话时我在。",
        "bright": "我先不打扰你，想说话的时候我在！",
    },
    "silence": {
        "default": "我在旁边陪着，想继续聊的时候叫我就好。",
        "cool": "我在旁边。想继续聊时叫我。",
        "bright": "我在旁边陪着，想继续聊就叫我！",
    },
    "timer": {
        "default": "到我们约好的时间啦。",
        "cool": "到约好的时间了。",
        "bright": "到我们约好的时间啦！",
    },
}


@dataclass(frozen=True)
class CompanionReaction:
    should_react: bool
    reaction_type: str
    reason: str
    priority: int = 0
    speech: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    plan_patch: dict[str, Any] = field(default_factory=dict)
    safety_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_react": self.should_react,
            "reaction_type": self.reaction_type,
            "reason": self.reason,
            "priority": self.priority,
            "speech": self.speech,
            "actions": self.actions,
            "plan_patch": self.plan_patch,
            "safety_flags": self.safety_flags,
        }


class CompanionReactionPlanner:
    """Deterministic event-to-reaction planner for companion hardware."""

    def decide(
        self,
        event_type: str,
        event: dict[str, Any] | None = None,
        memory_pack: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> CompanionReaction:
        event = event or {}
        context = context or {}
        memory_pack = memory_pack or {}
        normalized = (event_type or "").lower()

        if normalized in {"battery_low", "low_battery"}:
            return self._battery_low(event, context)
        if normalized in {"hardware_failure", "device_error", "motor_error"}:
            return self._hardware_failure(event, context)
        if normalized in {"user_interrupt", "barge_in", "interrupt"}:
            return self._user_interrupt(event, context)
        if normalized in {"touch", "sensor_touch"}:
            return self._touch(event, memory_pack, context)
        if normalized in {"silence", "idle"}:
            return self._silence(event, memory_pack, context)
        if normalized in {"timer", "scheduled_intent"}:
            return self._timer(event, context)
        if normalized in {"reflection", "memory_reflection"}:
            return self._reflection(event)

        return CompanionReaction(
            should_react=False,
            reaction_type="ignore",
            reason="unknown_event_type",
        )

    def _battery_low(self, event: dict[str, Any], context: dict[str, Any]) -> CompanionReaction:
        level = event.get("battery_percent")
        text_key = "battery_low"
        if isinstance(level, (int, float)) and level <= 5:
            text_key = "battery_critical"
        return CompanionReaction(
            should_react=True,
            reaction_type="verbal_and_action",
            reason="battery_low_requires_safe_degradation",
            priority=95,
            speech=self._speech(
                context,
                text_key,
                style="soft",
                emotion_pad=[0.0, -0.4, -0.2],
                vocalization_kind="low_power",
            ),
            actions=[
                {
                    "channel": "led",
                    "pattern": "breathe",
                    "color": "warm_dim",
                    "dur_ms": 4000,
                    "fallback": "none",
                }
            ],
            plan_patch={"mode": "power_saving", "suspend_high_power_actions": True},
            safety_flags=["low_power"],
        )

    def _hardware_failure(
        self, event: dict[str, Any], context: dict[str, Any]
    ) -> CompanionReaction:
        channel = str(event.get("channel") or "motion")
        return CompanionReaction(
            should_react=True,
            reaction_type="fallback",
            reason="hardware_failure_fallback",
            priority=90,
            speech=self._speech(
                context,
                "hardware_failure",
                style="calm",
                emotion_pad=[0.1, -0.3, -0.1],
                vocalization_kind="comfort",
            ),
            actions=[
                {
                    "channel": "led",
                    "pattern": "soft_hold",
                    "color": "warm",
                    "dur_ms": 3000,
                    "fallback": "none",
                }
            ],
            plan_patch={"disabled_channel": channel, "use_fallback_actions": True},
            safety_flags=["hardware_degraded"],
        )

    def _user_interrupt(self, event: dict[str, Any], context: dict[str, Any]) -> CompanionReaction:
        return CompanionReaction(
            should_react=True,
            reaction_type="stop_and_listen",
            reason="user_interrupted_current_output",
            priority=100,
            speech=self._speech(
                context,
                "interrupt",
                style="brief",
                emotion_pad=[0.0, -0.2, 0.0],
                vocalization_kind="ack",
            ),
            actions=[
                {
                    "channel": "audio",
                    "command": "stop",
                    "fallback": "none",
                }
            ],
            plan_patch={"pause_current_intent": True, "resume_after_user_turn": True},
        )

    def _touch(
        self,
        event: dict[str, Any],
        memory_pack: dict[str, Any],
        context: dict[str, Any],
    ) -> CompanionReaction:
        gesture = str(event.get("gesture") or "none")
        low_disturbance = self._low_disturbance(memory_pack)
        if gesture in {"hug", "hold"}:
            text_key = "hug_low" if low_disturbance else "hug"
            return CompanionReaction(
                should_react=True,
                reaction_type="verbal_and_action",
                reason="comfort_touch",
                priority=70,
                speech=self._speech(
                    context,
                    text_key,
                    style="soft",
                    emotion_pad=[0.4, -0.2, -0.1],
                    vocalization_kind="comfort",
                ),
                actions=[
                    {
                        "channel": "led",
                        "pattern": "warm_breathe",
                        "dur_ms": 2500,
                        "fallback": "none",
                    }
                ],
            )
        if gesture in {"shake", "squeeze"}:
            return CompanionReaction(
                should_react=True,
                reaction_type="boundary",
                reason="rough_touch",
                priority=80,
                speech=self._speech(
                    context,
                    "rough_touch",
                    style="gentle_boundary",
                    emotion_pad=[-0.1, 0.2, -0.1],
                    vocalization_kind="boundary",
                ),
                actions=[
                    {
                        "channel": "led",
                        "pattern": "blink_slow",
                        "color": "amber",
                        "dur_ms": 1600,
                        "fallback": "none",
                    }
                ],
                safety_flags=["rough_touch"],
            )
        if gesture in {"pat", "stroke"}:
            return CompanionReaction(
                should_react=not low_disturbance,
                reaction_type="light_ack",
                reason="gentle_touch_acknowledgement",
                priority=35,
                speech=self._speech(
                    context,
                    "gentle_touch",
                    style="tiny",
                    emotion_pad=[0.3, 0.0, 0.0],
                    vocalization_kind="ack",
                ),
                actions=[
                    {
                        "channel": "led",
                        "pattern": "blink_slow",
                        "color": "warm",
                        "dur_ms": 1200,
                        "fallback": "none",
                    }
                ],
            )
        return CompanionReaction(
            should_react=False,
            reaction_type="store_context",
            reason="touch_context_only",
        )

    def _silence(
        self,
        event: dict[str, Any],
        memory_pack: dict[str, Any],
        context: dict[str, Any],
    ) -> CompanionReaction:
        idle_seconds = int(event.get("idle_seconds") or 0)
        local_hour = context.get("local_hour")
        is_night = isinstance(local_hour, int) and (local_hour >= 22 or local_hour < 7)
        low_disturbance = self._low_disturbance(memory_pack)

        if is_night:
            return CompanionReaction(
                should_react=False,
                reaction_type="quiet_mode",
                reason="night_silence_no_proactive_verbal",
                actions=[
                    {
                        "channel": "led",
                        "pattern": "dim_hold",
                        "color": "warm_low",
                        "dur_ms": 3000,
                        "fallback": "none",
                    }
                ],
                plan_patch={"quiet_until_user_speaks": True},
            )
        if idle_seconds < 20 * 60:
            return CompanionReaction(
                should_react=False,
                reaction_type="wait",
                reason="idle_threshold_not_met",
            )
        text_key = "silence_low" if low_disturbance else "silence"
        return CompanionReaction(
            should_react=True,
            reaction_type="low_disturbance_proactive",
            reason="long_silence_single_lightweight_checkin",
            priority=30,
            speech=self._speech(
                context,
                text_key,
                style="low_disturbance",
                emotion_pad=[0.1, -0.4, -0.2],
                vocalization_kind="comfort",
            ),
            actions=[
                {
                    "channel": "led",
                    "pattern": "warm_breathe",
                    "dur_ms": 3000,
                    "fallback": "none",
                }
            ],
            plan_patch={"do_not_repeat_for_seconds": 1800},
        )

    def _timer(self, event: dict[str, Any], context: dict[str, Any]) -> CompanionReaction:
        intent = str(event.get("intent") or "scheduled_checkin")
        if context.get("quiet_mode"):
            return CompanionReaction(
                should_react=False,
                reaction_type="defer",
                reason="quiet_mode_defers_timer",
                plan_patch={"defer_intent": intent},
            )
        text = str(event.get("text") or self._variant_text(context, "timer"))
        return CompanionReaction(
            should_react=True,
            reaction_type="scheduled_intent",
            reason="timer_due",
            priority=50,
            speech=self._speech(
                context,
                "timer",
                style="brief",
                emotion_pad=[0.2, 0.0, 0.0],
                text_override=text,
                vocalization_kind="timer",
            ),
            actions=[
                {
                    "channel": "led",
                    "pattern": "soft_ping",
                    "dur_ms": 1400,
                    "fallback": "none",
                }
            ],
            plan_patch={"intent": intent, "status": "triggered"},
        )

    def _reflection(self, event: dict[str, Any]) -> CompanionReaction:
        return CompanionReaction(
            should_react=False,
            reaction_type="plan_patch",
            reason="reflection_updates_future_behavior_only",
            plan_patch={
                "refresh_memory_pack": True,
                "new_reflection_ids": event.get("reflection_ids") or [],
            },
        )

    def _low_disturbance(self, memory_pack: dict[str, Any]) -> bool:
        hints = memory_pack.get("robot_behavior_hints") or {}
        if hints.get("speech_policy") == "low_disturbance":
            return True
        text = " ".join(
            str(item.get("content", ""))
            for key in ("implicit", "compiled_rules", "direct")
            for item in memory_pack.get(key, [])
            if isinstance(item, dict)
        )
        return any(k in text for k in ("低打扰", "安静", "疲惫", "焦虑"))

    def _speech(
        self,
        context: dict[str, Any],
        text_key: str,
        *,
        style: str,
        emotion_pad: list[float],
        text_override: str | None = None,
        vocalization_kind: str = "ack",
    ) -> dict[str, Any]:
        persona = self._persona(context)
        semantic_text = text_override or self._variant_text(context, text_key)
        language_mode = str(persona.get("language_mode") or "VERBAL").upper()
        if language_mode == "VOCALIZED":
            return {
                "text": self._vocalization(persona, vocalization_kind),
                "semantic_text": semantic_text,
                "style": f"vocalized_{style}",
                "emotion_pad": emotion_pad,
                "language_mode": "VOCALIZED",
            }
        return {
            "text": semantic_text,
            "style": style,
            "emotion_pad": emotion_pad,
            "language_mode": "VERBAL",
        }

    def _variant_text(self, context: dict[str, Any], key: str) -> str:
        variants = _VERBAL_VARIANTS[key]
        persona = self._persona(context)
        tone = self._tone(persona)
        return variants.get(tone) or variants["default"]

    def _persona(self, context: dict[str, Any]) -> dict[str, Any]:
        persona = context.get("persona") or context.get("character") or {}
        if not isinstance(persona, dict):
            persona = {}
        merged = dict(persona)
        for key in (
            "archetype",
            "species",
            "personality",
            "response_length",
            "responseLength",
            "language_mode",
            "languageMode",
            "vocalization_palette",
            "vocalizationPalette",
        ):
            if key in context and key not in merged:
                merged[key] = context[key]
        if "languageMode" in merged and "language_mode" not in merged:
            merged["language_mode"] = merged["languageMode"]
        if "vocalizationPalette" in merged and "vocalization_palette" not in merged:
            merged["vocalization_palette"] = merged["vocalizationPalette"]
        return merged

    def _tone(self, persona: dict[str, Any]) -> str:
        personality = (
            persona.get("personality") if isinstance(persona.get("personality"), dict) else {}
        )
        energy = int(personality.get("energy", 50) or 50)
        extrovert = int(personality.get("extrovert", 50) or 50)
        warmth = int(personality.get("warmth", 50) or 50)
        if energy >= 75 or extrovert >= 75:
            return "bright"
        if warmth <= 30 or extrovert <= 30:
            return "cool"
        return "default"

    def _vocalization(self, persona: dict[str, Any], kind: str) -> str:
        palette = persona.get("vocalization_palette")
        if isinstance(palette, list) and palette:
            first = str(palette[0]).strip()
            second = str(palette[1]).strip() if len(palette) > 1 else first
            if kind == "boundary":
                return f"{second}!"
            if kind == "timer":
                return f"{first}~"
            if kind == "low_power":
                return f"{first}..."
            if kind == "comfort":
                return f"{first}...{second}"
            return first
        return _DEFAULT_VOCALIZATIONS.get(kind, _DEFAULT_VOCALIZATIONS["ack"])
