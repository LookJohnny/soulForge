"""Companion runtime loop.

while running:
    observe user/environment/robot state -> update world_state
    collect events
    if events: evaluate interruption level -> plan_delta -> update plans
    select next minute_action -> resolve template -> dispatch to adapter
    emit voice/dialogue, log action + emotion + memory + plan changes
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from engine.planner.day_planner import generate_day_plan
from engine.planner.hour_planner import expand_hour
from engine.planner.llm_interface import BehaviorDecision, build_llm
from engine.planner.minute_planner import plan_minute
from engine.planner.models import (
    DayPlan,
    Event,
    HourPlan,
    ImpactLevel,
    MicroAction,
    MinuteAction,
    Persona,
    PlanDelta,
    VISION_EVENT_KINDS,
    WorldState,
)
from engine.planner.replanner import Replanner

Adapter = Callable[[str, MicroAction], None]

_MEDIA_KEYS = {
    "media_ref",
    "image",
    "image_url",
    "audio",
    "audio_url",
    "video",
    "video_url",
    "frame",
    "raw",
    "frame_ref",
    "audio_ref",
    "video_ref",
    "screenshot",
    "pcm",
    "jpeg",
    "jpg",
    "png",
    "webp",
    "waveform",
    "blob",
    "attachment",
}
_MEDIA_KEY_PARTS = (
    "media",
    "image",
    "audio",
    "video",
    "frame",
    "screenshot",
    "waveform",
    "thumbnail",
    "pixel",
    "pcm",
    "jpeg",
    "webp",
    "blob",
)
_MEMORY_MAX_DEPTH = 6
_MEMORY_MAX_ITEMS = 64
_MEMORY_MAX_STRING = 512
_MEMORY_MAX_TOTAL_BYTES = 8192
_DROP_MEMORY_VALUE = object()


def _is_media_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _MEDIA_KEYS or any(
        part in normalized for part in _MEDIA_KEY_PARTS
    )


def _sanitize_memory_value(value: Any, *, depth: int = 0) -> Any:
    """Recursively keep small JSON-like summaries and reject media/blob payloads."""
    if depth > _MEMORY_MAX_DEPTH:
        return _DROP_MEMORY_VALUE
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP_MEMORY_VALUE
    if isinstance(value, str):
        if value.startswith("data:") or len(value) > _MEMORY_MAX_STRING:
            return _DROP_MEMORY_VALUE
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        return _DROP_MEMORY_VALUE
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, child in list(value.items())[:_MEMORY_MAX_ITEMS]:
            if not isinstance(key, str) or _is_media_key(key):
                continue
            sanitized = _sanitize_memory_value(child, depth=depth + 1)
            if sanitized is not _DROP_MEMORY_VALUE:
                clean[key] = sanitized
        return clean
    if isinstance(value, list | tuple):
        clean_list = []
        for child in list(value)[:_MEMORY_MAX_ITEMS]:
            sanitized = _sanitize_memory_value(child, depth=depth + 1)
            if sanitized is not _DROP_MEMORY_VALUE:
                clean_list.append(sanitized)
        return clean_list
    return _DROP_MEMORY_VALUE


def _sanitize_memory_update(update: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, recursively sanitized long-term-memory update."""
    clean: dict[str, Any] = {}
    used = 2  # account for the surrounding JSON object
    for key, value in list(update.items())[:_MEMORY_MAX_ITEMS]:
        if not isinstance(key, str) or _is_media_key(key):
            continue
        sanitized = _sanitize_memory_value(value)
        if sanitized is _DROP_MEMORY_VALUE:
            continue
        encoded = json.dumps(
            {key: sanitized}, ensure_ascii=False, separators=(",", ":")
        )
        size = len(encoded.encode("utf-8"))
        if used + size > _MEMORY_MAX_TOTAL_BYTES:
            continue
        clean[key] = sanitized
        used += size
    return clean


def _trusted_confirmed_hazard(event: Event) -> bool:
    """Critical sensor claims require both policy evidence and an HMAC."""
    if event.kind not in VISION_EVENT_KINDS:
        return False
    payload = event.payload if isinstance(event.payload, dict) else {}
    try:
        confidence = float(payload.get("confidence", 0))
        hits = int(payload.get("hazard_confirmation_hits", 0))
        required = int(payload.get("hazard_confirmation_required_hits", 3))
    except (TypeError, ValueError):
        return False
    if (
        payload.get("severity") != "critical"
        or confidence < 0.75
        or required < 3
        or hits < required
    ):
        return False
    from engine.perception.attestation import verify_hazard_claim

    return verify_hazard_claim(payload, event.source, event.target_agent)


def _confirmed_hazard_decision(event: Event, persona: Persona) -> BehaviorDecision:
    """Deterministic safety decision: a remote LLM cannot weaken or improvise it."""
    label = str(event.payload.get("hazard_confirmed", "hazard"))[:80]
    return BehaviorDecision(
        selected_intent="respond_to_confirmed_hazard",
        emotional_read="urgent",
        plan_delta="day",
        impact=ImpactLevel.CRITICAL,
        template_to_call="idle",
        dialogue=[
            {
                "agent": persona.agent_id,
                "text": "我检测到已确认的异常情况，先进入安全状态。",
                "emotion": "focused",
            }
        ],
        motion_style="brisk",
        interrupt_policy="reschedule",
        memory_update={"hazard": label},
        reason="attested multi-frame hazard: deterministic safe-stop",
    )


@dataclass
class TraceEntry:
    t_min: float
    agent_id: str
    kind: str  # tick | event | decision | dispatch | dialogue | plan_change
    detail: dict[str, Any] = field(default_factory=dict)
    seq: int = 0  # monotonic id — survives ring-buffer eviction


class CompanionRuntime:
    def __init__(
        self,
        personas: list[Persona],
        world: WorldState | None = None,
        llm=None,
        adapter: Adapter | None = None,
        trace_limit: int = 20000,
        memory_store=None,
    ):
        if not personas:
            raise ValueError("CompanionRuntime needs at least one persona")
        from engine.planner.memory_store import InMemoryMemoryStore

        self.personas = {p.agent_id: p for p in personas}
        self.world = world or WorldState()
        self.llm = llm or build_llm()
        self.replanner = Replanner()
        self.adapter = adapter or (lambda agent_id, action: None)
        self.event_queue: deque[Event] = deque(maxlen=1000)  # backpressure, drop-oldest
        # character state is keyed by agent_id and lives in the store — bodies
        # come and go, the person persists. `memory` remains a per-run view.
        self.memory_store = memory_store or InMemoryMemoryStore()
        self.memory: dict[str, dict[str, Any]] = {p: {} for p in self.personas}
        for agent_id, persona in self.personas.items():
            stored = self.memory_store.get_relationships(agent_id)
            if stored:  # persisted relationships win over config defaults
                persona.relationships.update(stored)
            self.memory[agent_id] = self.memory_store.recall(agent_id, "episodic")
        # ring buffer so week-long runs cannot grow memory without bound
        self.trace: deque[TraceEntry] = deque(maxlen=trace_limit)
        self._trace_seq = 0

        self.day_plans: dict[str, DayPlan] = {
            agent_id: generate_day_plan(persona, self.world)
            for agent_id, persona in self.personas.items()
        }
        self.hour_plans: dict[str, HourPlan] = {}

    # -- events -----------------------------------------------------------
    def push_event(self, event: Event) -> None:
        self.event_queue.append(event)

    # -- main loop ----------------------------------------------------------
    def tick(
        self, minute: float, consume_events: bool = True
    ) -> dict[str, MinuteAction]:
        """One planner step at `minute`: consume due events, plan and dispatch.

        This is the unit a real-time server drives; `run()` batches it for
        offline simulation and tests. A host that processes events on its own
        worker (to keep LLM latency out of the tick) passes consume_events=False.
        """
        self.world.sim_minute = minute
        self._ensure_hour_plans(minute)

        due = (
            [e for e in list(self.event_queue) if e.t_min <= minute]
            if consume_events
            else []
        )
        for event in due:
            self.event_queue.remove(event)
            self._handle_event(event, minute)

        actions: dict[str, MinuteAction] = {}
        for agent_id, persona in self.personas.items():
            minute_action = plan_minute(persona, self.hour_plans[agent_id], minute)
            self._dispatch(agent_id, minute_action)
            actions[agent_id] = minute_action
        return actions

    def run(
        self, start_min: float, duration_min: float, step_min: float = 1.0
    ) -> list[TraceEntry]:
        minute = start_min
        while minute < start_min + duration_min:
            self.tick(minute)
            minute += step_min
        return self.trace

    # -- internals ------------------------------------------------------------
    def _ensure_hour_plans(self, minute: float) -> None:
        day = int(minute // (24 * 60))
        hour = int(minute // 60)  # TOTAL hour index: survives midnights
        for agent_id, persona in self.personas.items():
            if self.day_plans[agent_id].day != day:
                # a new simulated day gets a fresh day plan — never degrade to idle
                self.day_plans[agent_id] = generate_day_plan(
                    persona, self.world, day=day
                )
                self._log(
                    minute,
                    agent_id,
                    "plan_change",
                    {
                        "level": "day",
                        "new_day": day,
                        "rationale": self.day_plans[agent_id].rationale,
                    },
                )
            plan = self.hour_plans.get(agent_id)
            if plan is None or plan.hour != hour:
                self.hour_plans[agent_id] = expand_hour(
                    persona, self.day_plans[agent_id], hour, self.world
                )
                self._log(
                    minute,
                    agent_id,
                    "plan_change",
                    {
                        "level": "hour",
                        "goal": self.hour_plans[agent_id].goal,
                        "activities": [
                            a.template_id for a in self.hour_plans[agent_id].activities
                        ],
                    },
                )

    def handle_event_now(self, event: Event, minute: float) -> None:
        """Public synchronous event handling — hosts run this off the tick path
        (worker thread) so LLM latency never stalls the action loop."""
        self._handle_event(event, minute)

    def _handle_event(self, event: Event, minute: float) -> None:
        self._log(
            minute,
            event.target_agent or "*",
            "event",
            {"kind": event.kind.value, "source": event.source, "text": event.text},
        )
        if event.target_agent is not None and event.target_agent not in self.personas:
            self._log(
                minute,
                event.target_agent,
                "event_dropped",
                {"reason": "unknown target agent"},
            )
            return
        targets = [event.target_agent] if event.target_agent else list(self.personas)
        for agent_id in targets:
            persona = self.personas[agent_id]
            hour_plan = self.hour_plans[agent_id]
            activity = hour_plan.activity_at(minute)
            current_template = activity.template_id if activity else "idle"
            decision = self.llm.decide(
                event,
                persona,
                self.world,
                current_template,
                activity.interruptible if activity else True,
            )

            # Vision/sound labels, OCR and provider text are untrusted sensor
            # data.  An LLM can never promote them into a physical emergency.
            # A signed, multi-frame confirmation instead selects a fixed
            # deterministic safe-stop decision, independent of the LLM output.
            if event.kind in VISION_EVENT_KINDS:
                if _trusted_confirmed_hazard(event):
                    decision = _confirmed_hazard_decision(event, persona)
                elif decision.impact > ImpactLevel.LOW:
                    self._log(
                        minute,
                        agent_id,
                        "decision",
                        {
                            "impact": "LOW",
                            "scope": "clamped",
                            "reason": (
                                "unattested perception cannot exceed LOW; "
                                f"impact {decision.impact.name} rejected"
                            ),
                            "intent": "ignore_unconfirmed_sensor_escalation",
                            "emotional_read": decision.emotional_read,
                            "interrupt_policy": "resume",
                        },
                    )
                    continue

            # -- deterministic perception guard: low-confidence sensor events can
            # never escalate past LOW, regardless of what any LLM decided
            confidence = event.payload.get("confidence")
            if (
                event.payload.get("perception")
                and confidence is not None
                and float(confidence) < 0.6
                and decision.impact > ImpactLevel.LOW
            ):
                self._log(
                    minute,
                    agent_id,
                    "decision",
                    {
                        "impact": "LOW",
                        "scope": "clamped",
                        "reason": (
                            f"perception confidence {confidence} below threshold: "
                            f"impact {decision.impact.name} clamped, no physical escalation"
                        ),
                        "intent": decision.selected_intent,
                        "emotional_read": decision.emotional_read,
                        "interrupt_policy": "resume",
                    },
                )
                continue

            # -- deterministic interruption enforcement (never delegated to the LLM).
            # Must run BEFORE replanner.apply: applying a delta has side effects.
            if (
                activity is not None
                and not activity.interruptible
                and decision.impact < ImpactLevel.CRITICAL
                and not event.payload.get("_deferred_from")
            ):
                safe_at = activity.start_min + activity.duration_min + 0.01
                self.push_event(
                    Event(
                        t_min=safe_at,
                        kind=event.kind,
                        source=event.source,
                        text=event.text,
                        payload={**event.payload, "_deferred_from": minute},
                        target_agent=agent_id,
                    )
                )
                self._log(
                    minute,
                    agent_id,
                    "decision",
                    {
                        "impact": decision.impact.name,
                        "scope": "deferred",
                        "reason": (
                            f"activity {activity.template_id} is non-interruptible; "
                            f"event deferred to safe breakpoint at {safe_at:.0f}"
                        ),
                        "intent": "hold_until_safe_breakpoint",
                        "emotional_read": decision.emotional_read,
                        "interrupt_policy": "defer",
                    },
                )
                continue

            delta = self.replanner.apply(
                decision, event, persona, self.day_plans[agent_id], hour_plan, minute
            )
            self._apply_delta(agent_id, delta, minute)
            self._log(
                minute,
                agent_id,
                "decision",
                {
                    "impact": delta.impact.name,
                    "scope": delta.scope,
                    "reason": delta.reason,
                    "intent": decision.selected_intent,
                    "emotional_read": decision.emotional_read,
                    "interrupt_policy": decision.interrupt_policy,
                },
            )

    def _apply_delta(self, agent_id: str, delta: PlanDelta, minute: float) -> None:
        persona = self.personas[agent_id]
        if delta.hour_rewrite is not None:
            self.hour_plans[agent_id] = delta.hour_rewrite
            self._log(
                minute,
                agent_id,
                "plan_change",
                {"level": "hour", "rewritten": True, "goal": delta.hour_rewrite.goal},
            )
        if delta.day_rewrite:
            self.day_plans[agent_id].blocks = delta.day_rewrite
            # the current hour must follow the rewritten day immediately
            self.hour_plans[agent_id] = expand_hour(
                self.personas[agent_id],
                self.day_plans[agent_id],
                int(minute // 60),
                self.world,
            )
            self._log(
                minute,
                agent_id,
                "plan_change",
                {
                    "level": "day",
                    "rewritten": True,
                    "hour_refreshed": self.hour_plans[agent_id].goal,
                },
            )
        for key, value in _sanitize_memory_update(delta.memory_update).items():
            self.memory[agent_id][key] = value
            self.memory_store.remember(agent_id, "episodic", key, value)
        for other, bump in delta.relationship_delta.items():
            updated = min(1.0, persona.relationships.get(other, 0.5) + bump)
            persona.relationships[other] = updated
            self.memory_store.set_relationship(agent_id, other, updated)
        for action in delta.micro_actions:
            self._dispatch_micro(agent_id, action, minute)

    def _dispatch(self, agent_id: str, minute_action: MinuteAction) -> None:
        for step in minute_action.steps:
            self.adapter(agent_id, step)
        self._log(
            minute_action.minute,
            agent_id,
            "dispatch",
            {
                "template": minute_action.template_id,
                "steps": [s.name for s in minute_action.steps],
                "reason": minute_action.reason,
            },
        )

    def _dispatch_micro(
        self, agent_id: str, action: MicroAction, minute: float
    ) -> None:
        self.adapter(agent_id, action)
        kind = "dialogue" if action.dialogue else "dispatch"
        self._log(
            minute,
            agent_id,
            kind,
            {
                "step": action.name,
                "dialogue": action.dialogue,
                "gaze": action.gaze_target,
                "params": action.params,
            },
        )

    def log(
        self, t_min: float, agent_id: str, kind: str, detail: dict[str, Any]
    ) -> None:
        """Public trace hook for hosts (runtime server, adapters, test harnesses)."""
        self._trace_seq += 1
        self.trace.append(
            TraceEntry(
                t_min=t_min,
                agent_id=agent_id,
                kind=kind,
                detail=detail,
                seq=self._trace_seq,
            )
        )

    def trace_since(self, seq: int) -> list[TraceEntry]:
        """Entries newer than `seq` (ring-buffer safe)."""
        fresh: list[TraceEntry] = []
        for entry in reversed(self.trace):
            if entry.seq <= seq:
                break
            fresh.append(entry)
        fresh.reverse()
        return fresh

    # backwards-compatible private alias
    _log = log

    # -- introspection --------------------------------------------------------
    def explain_last_decision(self) -> str:
        for entry in reversed(self.trace):
            if entry.kind == "decision":
                d = entry.detail
                return f"[{d['impact']}] scope={d['scope']} intent={d['intent']} :: {d['reason']}"
        return "no decision yet"

    def dump_trace_json(self) -> str:
        return json.dumps([asdict(t) for t in self.trace], ensure_ascii=False, indent=2)
