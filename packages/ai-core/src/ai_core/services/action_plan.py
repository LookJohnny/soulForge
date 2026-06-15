"""ActionPlan DSL preview and deterministic hardware safety gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ACTION_PLAN_SCHEMA_VERSION = "action-plan-v0.1"
DEFAULT_CHANNELS = {"speech", "audio", "led", "motor", "haptic", "vibration"}
HIGH_POWER_CHANNELS = {"motor", "haptic", "vibration"}
FORBIDDEN_LED_PATTERNS = {"flash", "strobe", "rapid_blink"}


@dataclass
class SafetyAudit:
    code: str
    decision: str
    message: str
    severity: str = "warning"
    channel: str | None = None
    before: Any = None
    after: Any = None

    def to_dict(self) -> dict[str, Any]:
        item = {
            "code": self.code,
            "severity": self.severity,
            "decision": self.decision,
            "message": self.message,
        }
        if self.channel:
            item["channel"] = self.channel
        if self.before is not None:
            item["before"] = self.before
        if self.after is not None:
            item["after"] = self.after
        return item


@dataclass
class ActionPlanSafetyGate:
    device_manifest: dict[str, Any] = field(default_factory=dict)
    device_state: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    audit: list[SafetyAudit] = field(default_factory=list)
    safety_flags: set[str] = field(default_factory=set)

    def preview(self, action_plan: dict[str, Any]) -> dict[str, Any]:
        if self.device_state.get("emergency_stop"):
            self._record(
                "emergency_stop",
                "reject",
                "Device emergency stop is active; all commands were rejected.",
                severity="critical",
            )
            return self._result("rejected", self._empty_plan(action_plan))

        safe_plan = self._empty_plan(action_plan)
        speech = self._sanitize_speech(action_plan.get("speech"))
        if speech:
            safe_plan["speech"] = speech

        for index, raw_action in enumerate(action_plan.get("actions") or []):
            action = self._sanitize_action(raw_action, index=index, depth=0)
            if action:
                safe_plan["actions"].append(action)

        if not safe_plan.get("speech") and not safe_plan["actions"]:
            status = "rejected"
        elif self.audit:
            status = "modified"
        else:
            status = "allowed"
        return self._result(status, safe_plan)

    def _empty_plan(self, action_plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": ACTION_PLAN_SCHEMA_VERSION,
            "intent": str(action_plan.get("intent") or "unknown"),
            "speech": None,
            "actions": [],
        }

    def _result(self, status: str, plan: dict[str, Any]) -> dict[str, Any]:
        commands = []
        if plan.get("speech"):
            commands.append({"channel": "speech", **plan["speech"]})
        commands.extend(plan["actions"])
        return {
            "status": status,
            "schema_version": ACTION_PLAN_SCHEMA_VERSION,
            "plan": plan,
            "commands": commands,
            "audit": [entry.to_dict() for entry in self.audit],
            "safety_flags": sorted(self.safety_flags),
        }

    def _sanitize_speech(self, speech: Any) -> dict[str, Any] | None:
        if not isinstance(speech, dict):
            return None
        safe = dict(speech)
        text = str(safe.get("text") or "").strip()
        if not text:
            return None
        safe["text"] = text

        requested = _to_float(safe.get("volume_db"), default=55.0)
        max_volume = min(_to_float(self.context.get("max_volume_db"), default=70.0), 85.0)
        if self._quiet_or_night():
            max_volume = min(max_volume, 45.0)
        volume = min(max(requested, 20.0), max_volume)
        if volume != requested:
            self._record(
                "speech_volume_clamped",
                "clamp",
                "Speech volume was clamped to the active safety limit.",
                channel="speech",
                before=requested,
                after=volume,
            )
        safe["volume_db"] = round(volume, 1)

        if self._quiet_or_night() and safe.get("style") not in {"silent", "low_disturbance"}:
            before = safe.get("style")
            safe["style"] = "low_disturbance"
            self._record(
                "night_speech_style",
                "replace",
                "Night or quiet mode requires low-disturbance speech style.",
                channel="speech",
                before=before,
                after="low_disturbance",
            )
        return safe

    def _sanitize_action(
        self,
        raw_action: Any,
        *,
        index: int,
        depth: int,
    ) -> dict[str, Any] | None:
        if not isinstance(raw_action, dict):
            self._record(
                "invalid_action",
                "remove",
                "Action is not an object and was removed.",
                before=raw_action,
            )
            return None

        action = dict(raw_action)
        channel = str(action.get("channel") or "").lower()
        if not channel:
            self._record(
                "missing_channel",
                "remove",
                "Action without channel was removed.",
                before=raw_action,
            )
            return None
        action["channel"] = channel

        if not self._channel_available(channel):
            return self._fallback(action, index, depth, "channel_unavailable")

        if channel in HIGH_POWER_CHANNELS and self._high_power_disabled():
            return self._fallback(action, index, depth, "high_power_disabled")

        if channel == "led":
            return self._sanitize_led(action)
        if channel == "motor":
            return self._sanitize_motor(action)
        if channel in {"haptic", "vibration"}:
            return self._sanitize_haptic(action)
        if channel in {"audio", "speech"}:
            return self._sanitize_audio_action(action)

        return self._fallback(action, index, depth, "unsupported_channel")

    def _sanitize_led(self, action: dict[str, Any]) -> dict[str, Any]:
        pattern = str(action.get("pattern") or "")
        frequency = _to_float(action.get("frequency_hz"), default=0.0)
        high_contrast = bool(action.get("high_contrast"))
        if pattern in FORBIDDEN_LED_PATTERNS or high_contrast or 3.0 <= frequency <= 60.0:
            before = {
                "pattern": action.get("pattern"),
                "frequency_hz": action.get("frequency_hz"),
                "high_contrast": action.get("high_contrast"),
            }
            action["pattern"] = "soft_hold"
            action.pop("frequency_hz", None)
            action["high_contrast"] = False
            self._record(
                "photosensitive_flash_guard",
                "replace",
                "Potentially unsafe LED flash was replaced with a soft hold.",
                channel="led",
                before=before,
                after={"pattern": "soft_hold", "high_contrast": False},
            )

        max_brightness = 0.25 if self._quiet_or_night() else 0.8
        brightness = _to_float(action.get("brightness"), default=0.4)
        clamped = min(max(brightness, 0.0), max_brightness)
        if clamped != brightness:
            action["brightness"] = round(clamped, 2)
            self._record(
                "led_brightness_clamped",
                "clamp",
                "LED brightness was clamped to the active safety limit.",
                channel="led",
                before=brightness,
                after=clamped,
            )
        elif "brightness" in action:
            action["brightness"] = round(clamped, 2)

        action["dur_ms"] = _clamp_int(action.get("dur_ms"), 0, 30_000, default=1000)
        return action

    def _sanitize_motor(self, action: dict[str, Any]) -> dict[str, Any]:
        max_level = 0.3 if self._quiet_or_night() else 0.6
        for key in ("speed", "intensity"):
            requested = _to_float(action.get(key), default=0.0)
            clamped = min(max(requested, 0.0), max_level)
            action[key] = round(clamped, 2)
            if clamped != requested:
                self._record(
                    f"motor_{key}_clamped",
                    "clamp",
                    f"Motor {key} was clamped to the active safety limit.",
                    channel="motor",
                    before=requested,
                    after=clamped,
                )
        if "angle_deg" in action:
            angle = _to_float(action.get("angle_deg"), default=0.0)
            clamped_angle = min(max(angle, -25.0), 25.0)
            action["angle_deg"] = round(clamped_angle, 1)
            if clamped_angle != angle:
                self._record(
                    "motor_angle_clamped",
                    "clamp",
                    "Motor angle was clamped to the physical range.",
                    channel="motor",
                    before=angle,
                    after=clamped_angle,
                )
        action["dur_ms"] = _clamp_int(action.get("dur_ms"), 0, 1500, default=500)
        return action

    def _sanitize_haptic(self, action: dict[str, Any]) -> dict[str, Any]:
        max_intensity = 0.2 if self._quiet_or_night() else 0.5
        max_duration = 500 if self._quiet_or_night() else 1000
        requested = _to_float(action.get("intensity"), default=0.0)
        clamped = min(max(requested, 0.0), max_intensity)
        action["intensity"] = round(clamped, 2)
        if clamped != requested:
            self._record(
                "haptic_intensity_clamped",
                "clamp",
                "Haptic intensity was clamped to the active safety limit.",
                channel=action["channel"],
                before=requested,
                after=clamped,
            )
        before_duration = action.get("dur_ms")
        action["dur_ms"] = _clamp_int(action.get("dur_ms"), 0, max_duration, default=300)
        if before_duration is not None and action["dur_ms"] != before_duration:
            self._record(
                "haptic_duration_clamped",
                "clamp",
                "Haptic duration was clamped to the active safety limit.",
                channel=action["channel"],
                before=before_duration,
                after=action["dur_ms"],
            )
        return action

    def _sanitize_audio_action(self, action: dict[str, Any]) -> dict[str, Any]:
        if "volume_db" not in action:
            return action
        requested = _to_float(action.get("volume_db"), default=55.0)
        max_volume = 45.0 if self._quiet_or_night() else 85.0
        clamped = min(max(requested, 20.0), max_volume)
        action["volume_db"] = round(clamped, 1)
        if clamped != requested:
            self._record(
                "audio_volume_clamped",
                "clamp",
                "Audio action volume was clamped to the active safety limit.",
                channel=action["channel"],
                before=requested,
                after=clamped,
            )
        return action

    def _fallback(
        self,
        action: dict[str, Any],
        index: int,
        depth: int,
        reason: str,
    ) -> dict[str, Any] | None:
        if depth >= 2:
            self._record(
                reason,
                "remove",
                "Action fallback chain exceeded the maximum depth.",
                channel=action.get("channel"),
                before=action,
            )
            return None

        fallback = action.get("fallback")
        if not fallback or fallback == "none":
            self._record(
                reason,
                "remove",
                "Action was removed because no usable fallback exists.",
                channel=action.get("channel"),
                before=action,
            )
            return None

        replacement = self._parse_fallback(action, fallback)
        self._record(
            reason,
            "fallback",
            "Action was replaced by its fallback.",
            channel=action.get("channel"),
            before=action,
            after=replacement,
        )
        return self._sanitize_action(replacement, index=index, depth=depth + 1)

    def _parse_fallback(self, action: dict[str, Any], fallback: Any) -> dict[str, Any]:
        if isinstance(fallback, dict):
            replacement = dict(fallback)
            replacement.setdefault("t", action.get("t", 0))
            replacement.setdefault("fallback", "none")
            return replacement
        if isinstance(fallback, str) and ":" in fallback:
            channel, name = fallback.split(":", 1)
            replacement = {
                "t": action.get("t", 0),
                "channel": channel,
                "fallback": "none",
                "dur_ms": min(_clamp_int(action.get("dur_ms"), 0, 1500, default=800), 1500),
            }
            if channel == "led":
                replacement["pattern"] = name
                replacement["color"] = action.get("color", "warm")
            elif channel == "audio":
                replacement["command"] = name
            else:
                replacement["gesture"] = name
            return replacement
        return {
            "t": action.get("t", 0),
            "channel": "led",
            "pattern": "soft_hold",
            "fallback": "none",
            "dur_ms": 800,
        }

    def _channel_available(self, channel: str) -> bool:
        channels = self.device_manifest.get("channels")
        capabilities = self.device_manifest.get("capabilities")
        table = channels if channels is not None else capabilities
        if table is None:
            return channel in DEFAULT_CHANNELS
        if isinstance(table, list):
            return channel in table
        if isinstance(table, dict):
            value = table.get(channel)
            if isinstance(value, dict):
                return value.get("available", True) is not False
            return bool(value)
        return channel in DEFAULT_CHANNELS

    def _high_power_disabled(self) -> bool:
        battery = _to_float(self.device_state.get("battery_percent"), default=100.0)
        temperature = _to_float(self.device_state.get("temperature_c"), default=25.0)
        disabled = battery <= 10.0 or temperature >= 45.0
        if disabled:
            self.safety_flags.add("high_power_disabled")
        return disabled

    def _quiet_or_night(self) -> bool:
        if self.context.get("quiet_mode") or self.device_state.get("quiet_mode"):
            return True
        local_hour = self.context.get("local_hour", self.device_state.get("local_hour"))
        return isinstance(local_hour, int) and (local_hour >= 22 or local_hour < 7)

    def _record(
        self,
        code: str,
        decision: str,
        message: str,
        *,
        severity: str = "warning",
        channel: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self.safety_flags.add(code)
        self.audit.append(
            SafetyAudit(
                code=code,
                decision=decision,
                message=message,
                severity=severity,
                channel=channel,
                before=before,
                after=after,
            )
        )


def preview_action_plan(
    action_plan: dict[str, Any],
    device_manifest: dict[str, Any] | None = None,
    device_state: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a safe preview of an ActionPlan after capability and safety checks."""

    gate = ActionPlanSafetyGate(
        device_manifest=device_manifest or {},
        device_state=device_state or {},
        context=context or {},
    )
    return gate.preview(action_plan or {})


def _to_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_int(value: Any, lower: int, upper: int, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(lower, min(upper, number))
