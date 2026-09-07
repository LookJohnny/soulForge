"""Companion runtime loop.

while running:
    observe user/environment/robot state -> update world_state
    collect events
    if events: evaluate interruption level -> plan_delta -> update plans
    select next minute_action -> resolve template -> dispatch to adapter
    emit voice/dialogue, log action + emotion + memory + plan changes
"""

from __future__ import annotations

import copy
import json
import math
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable

from soulforge_harness.runtime.day_planner import generate_day_plan
from soulforge_harness.runtime.hour_planner import expand_hour
from soulforge_harness.runtime.llm_interface import BehaviorDecision, build_llm
from soulforge_harness.runtime.minute_planner import plan_minute
from soulforge_harness.runtime.models import (
    EventKind,
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
from soulforge_harness.runtime.replanner import Replanner

Adapter = Callable[[str, MicroAction], None]


class _DeferredActionEvent(Event):
    """Internal scheduled work; wire payloads cannot construct this type."""


_MAX_DEFERRED_DECISIONS = 256

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
    from soulforge_harness.runtime.attestation import verify_hazard_claim

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


MIN_RELOCATION_MIN = 15  # shorter activities don't justify a walk across the room
PROP_BOUND_TEMPLATES = frozenset(
    {"cooking", "plant_care"}
)  # need the stove / the plants


class CompanionRuntime:
    def __init__(
        self,
        personas: list[Persona],
        world: WorldState | None = None,
        llm=None,
        adapter: Adapter | None = None,
        trace_limit: int = 20000,
        memory_store=None,
        social_policy=None,
    ):
        if not personas:
            raise ValueError("CompanionRuntime needs at least one persona")
        from soulforge_harness.runtime.memory_store import InMemoryMemoryStore

        self.personas = {p.agent_id: p for p in personas}
        self.world = world or WorldState()
        self.llm = llm or build_llm()
        self.replanner = Replanner()
        self.adapter = adapter or (lambda agent_id, action: None)
        self.event_queue: deque[Event] = deque(maxlen=1000)  # backpressure, drop-oldest
        # Keep the event itself alive with its decision: an integer id alone
        # could accidentally match a later object after Python reuses an id.
        self._deferred_decisions: OrderedDict[
            int, tuple[Event, BehaviorDecision]
        ] = OrderedDict()
        # character state is keyed by agent_id and lives in the store — bodies
        # come and go, the person persists. `memory` remains a per-run view.
        self.memory_store = memory_store or InMemoryMemoryStore()
        self.memory: dict[str, dict[str, Any]] = {p: {} for p in self.personas}
        for agent_id, persona in self.personas.items():
            stored = self.memory_store.get_relationships(agent_id)
            if stored:  # persisted relationships win over config defaults
                persona.relationships.update(stored)
            self.memory[agent_id] = self.memory_store.recall(agent_id, "episodic")
            snapshot = self.memory_store.recall(agent_id, "semantic").get("cognitive_state")
            if isinstance(snapshot, dict) and snapshot:
                self._apply_cognitive_state(persona, snapshot)
        # ring buffer so week-long runs cannot grow memory without bound
        self.trace: deque[TraceEntry] = deque(maxlen=trace_limit)
        self._trace_seq = 0
        # short conversational context per agent — shared across every body the
        # agent lives in, so "我们刚才聊到哪了" works after switching bodies
        self.recent_dialogue: dict[str, deque] = {
            p: deque(maxlen=8) for p in self.personas
        }

        # proactive presence ("Joi moment"): the companion notices a present but
        # silent user and comes over on her own. Thresholds are sim-minutes.
        self.proactive_after_min = 40.0
        self.proactive_cooldown_min = 240.0
        self.last_user_event_min = self.world.sim_minute
        self._last_proactive_min = -1e9

        self.day_plans: dict[str, DayPlan] = {
            agent_id: generate_day_plan(persona, self.world)
            for agent_id, persona in self.personas.items()
        }
        self.hour_plans: dict[str, HourPlan] = {}
        from soulforge_harness.runtime.conversation import ConversationManager

        self.conversations = ConversationManager(self, social_policy)
        # everyone starts somewhere (the sofa) so co-presence is well defined from tick 0
        from soulforge_harness.runtime.space import DEFAULT_PLACE

        for agent_id in self.personas:
            self.world.space.agent_place.setdefault(agent_id, DEFAULT_PLACE)

    @staticmethod
    def _apply_cognitive_state(persona: Persona, state: dict) -> None:
        persona.meta["cognitive_state"] = state
        pad = state.get("pad") or {}
        if isinstance(pad, dict):
            for key, field, low, high in (("p", "valence", -1.0, 1.0), ("a", "arousal", 0.0, 1.0)):
                value = pad.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    setattr(persona, field, max(low, min(high, (value + 1) / 2 if key == "a" else value)))
        rel = state.get("relationship") or {}
        energy = rel.get("energy") if isinstance(rel, dict) else None
        if isinstance(energy, (int, float)) and math.isfinite(energy):
            persona.energy = max(0.0, min(1.0, energy / 100))

    # -- live roster ----------------------------------------------------------
    def add_persona(self, persona: Persona) -> bool:
        """Install a new soul into the RUNNING world (no restart).

        The soul-swap demo drags a .soul in and a different person exists a
        second later — plans, memory view and a place to stand included."""
        if persona.agent_id in self.personas:
            return False
        self.personas[persona.agent_id] = persona
        stored = self.memory_store.get_relationships(persona.agent_id)
        if stored:
            persona.relationships.update(stored)
        self.memory[persona.agent_id] = self.memory_store.recall(
            persona.agent_id, "episodic"
        )
        self.day_plans[persona.agent_id] = generate_day_plan(persona, self.world)
        from soulforge_harness.runtime.space import DEFAULT_PLACE

        self.world.space.agent_place.setdefault(persona.agent_id, DEFAULT_PLACE)
        self._log(
            self.world.sim_minute,
            persona.agent_id,
            "plan_change",
            {"level": "roster", "installed": persona.name},
        )
        return True

    # -- conversations --------------------------------------------------------
    def start_conversation(
        self,
        initiator: str,
        partner: str,
        minute: float | None = None,
        topic: str = "",
        max_turns: int | None = None,
        force: bool = False,
    ):
        """Put two characters in a conversation; the opener speaks on the next event pass."""
        return self.conversations.start(
            initiator,
            partner,
            self.world.sim_minute if minute is None else minute,
            topic,
            max_turns,
            force=force,
        )

    # -- events -----------------------------------------------------------
    def push_event(self, event: Event) -> None:
        self.event_queue.append(event)

    def _maybe_proactive_presence(self, minute: float) -> None:
        """The Joi moment: a present but long-silent user gets noticed.

        The character closest to the user decides for herself what to do with
        the observation — the trigger only supplies it, the persona supplies
        the words."""
        if not self.world.user_present:
            return
        if minute - self.last_user_event_min < self.proactive_after_min:
            return
        if minute - self._last_proactive_min < self.proactive_cooldown_min:
            return
        self._last_proactive_min = minute
        closest = max(
            self.personas,
            key=lambda a: self.personas[a].relationships.get("user", 0.5),
        )
        self.push_event(
            Event(
                t_min=minute,
                kind=EventKind.USER_PRESENCE,
                source="user",
                text="用户一直在这里，但已经很久没有说话了——看起来有点孤单。",
                payload={"proactive": "loneliness"},
                target_agent=closest,
            )
        )

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
        self.conversations.maybe_auto_start(minute)
        self._maybe_proactive_presence(minute)

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
            self._move_if_needed(agent_id, minute_action.template_id, minute)
            self._dispatch(agent_id, minute_action)
            actions[agent_id] = minute_action
        return actions

    # -- space -----------------------------------------------------------------
    def where(self, agent_id: str) -> str:
        return self.world.space.where(agent_id)

    def _move_if_needed(
        self, agent_id: str, template_id: str | None, minute: float
    ) -> None:
        """Activities happen somewhere: walk there first. Anywhere-activities stay put."""
        from soulforge_harness.runtime.space import template_location

        target = template_location(template_id)
        if target is None or target == self.where(agent_id):
            return
        if self.conversations.active_for(agent_id) is not None:
            return  # you don't walk off mid-sentence; the activity waits for the conversation
        # short breaks (a 10-minute rest between two drawing stretches) are taken where
        # you already are — nobody paces sofa↔desk every few minutes
        plan = self.hour_plans.get(agent_id)
        activity = plan.activity_at(minute) if plan else None
        if (
            activity is not None
            and activity.duration_min < MIN_RELOCATION_MIN
            and template_id not in PROP_BOUND_TEMPLATES
        ):
            return
        self.move_to(agent_id, target, minute, reason=f"activity {template_id}")

    def move_to(
        self, agent_id: str, place: str, minute: float, reason: str = ""
    ) -> None:
        from soulforge_harness.runtime.space import walk_seconds

        space = self.world.space
        origin = self.where(agent_id)
        if origin == place:
            return
        space.move(agent_id, place)
        seconds = walk_seconds(origin, place)
        self._dispatch_micro(
            agent_id,
            MicroAction(
                name="walk_to",
                params={
                    "to": place,
                    "from": origin,
                    "label": space.label(place),
                    "x": space.places[place].x,
                    "z": space.places[place].z,
                },
                duration_s=seconds,
            ),
            minute,
        )
        self._log(
            minute, agent_id, "move", {"from": origin, "to": place, "reason": reason}
        )
        # whoever is already there notices the arrival (a low-key social event)
        for other in space.others_at(agent_id):
            self.push_event(
                Event(
                    t_min=minute + seconds / 60.0,
                    kind=EventKind.AGENT_STATE,
                    source=agent_id,
                    text=f"{self.personas[agent_id].name}来了{space.label(place)}",
                    payload={
                        "arrival": {
                            "agent_id": agent_id,
                            "name": self.personas[agent_id].name,
                            "place": place,
                            "label": space.label(place),
                        }
                    },
                    target_agent=other,
                )
            )

    # -- outcome feedback ------------------------------------------------------
    def record_action_outcome(
        self,
        agent_id: str,
        step: str,
        status: str,
        detail: str,
        minute: float,
    ) -> None:
        """Terminal action receipts flow back into episodic memory.

        Successes stay in the trace (remembering every `done` would drown the
        day). Failures can inform capability reflection; interruptions remain
        separate observations because barge-in or unconfirmed playback does
        not establish that the action failed."""
        if agent_id not in self.personas:
            return
        self._log(
            minute, agent_id, "action_outcome", {"step": step, "status": status}
        )
        if status not in ("failed", "interrupted"):
            return
        key = f"action_{status}_{step}"
        previous = self.memory[agent_id].get(key)
        count = (previous.get("count", 0) if isinstance(previous, dict) else 0) + 1
        value = {"status": status, "detail": str(detail)[:120], "count": count}
        self.memory[agent_id][key] = value
        self.memory_store.remember(agent_id, "episodic", key, value)

    # -- reflection --------------------------------------------------------------
    def reflect(self, agent_id: str, minute: float, day: int | None = None) -> list:
        """End-of-day reflection: memories → insights → tomorrow's goals/prompt."""
        from soulforge_harness.runtime.reflection import apply_reflections, reflect_day

        persona = self.personas[agent_id]
        names = {a: p.name for a, p in self.personas.items()}
        reflections = reflect_day(persona, self.memory.get(agent_id, {}), names)
        apply_reflections(persona, reflections)
        day = int(minute // (24 * 60)) if day is None else day
        for i, r in enumerate(reflections):
            key = f"reflection_d{day}_{i}"
            self.memory_store.remember(agent_id, "semantic", key, r.insight)
        if reflections:
            self._log(
                minute,
                agent_id,
                "reflection",
                {
                    "day": day,
                    "insights": [r.insight for r in reflections],
                    "goals": list(persona.daily_goals),
                },
            )
        return reflections

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
                # the day that just ended is reflected on before tomorrow is planned
                self.reflect(agent_id, minute, day=self.day_plans[agent_id].day)
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
        deferred_decision = None
        if isinstance(event, _DeferredActionEvent):
            cached = self._deferred_decisions.pop(id(event), None)
            if cached is None or cached[0] is not event:
                # Evicted/dropped scheduled work must never become a fresh
                # user turn and run cognition or persist that turn again.
                self._log(minute, event.target_agent or "*", "event_dropped",
                          {"reason": "deferred decision expired"})
                return
            deferred_decision = cached[1]
        self._log(
            minute,
            event.target_agent or "*",
            "event",
            {"kind": event.kind.value, "source": event.source, "text": event.text},
        )
        payload = event.payload if isinstance(event.payload, dict) else {}
        if deferred_decision is None and event.source == "user" and not payload.get("proactive"):
            self.last_user_event_min = minute  # genuine contact resets the silence clock
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
            if deferred_decision is None and not self.conversations.accepts(event, agent_id):
                self._log(
                    minute,
                    agent_id,
                    "event_dropped",
                    {"reason": "not this agent's turn"},
                )
                continue
            persona = self.personas[agent_id]
            hour_plan = self.hour_plans[agent_id]
            activity = hour_plan.activity_at(minute)
            current_template = activity.template_id if activity else "idle"
            history = self.recent_dialogue.setdefault(agent_id, deque(maxlen=8))
            if deferred_decision is None:
                if event.kind == EventKind.USER_UTTERANCE and event.text:
                    history.append(("用户", event.text[:120]))
                persona.meta["recent_dialogue"] = list(history)
                decision = self.llm.decide(
                    event,
                    persona,
                    self.world,
                    current_template,
                    activity.interruptible if activity else True,
                )

                if decision.cognitive_state:
                    state = decision.cognitive_state
                    self._apply_cognitive_state(persona, state)
                    self.memory_store.remember(agent_id, "semantic", "cognitive_state", state)
                if decision.provider_status.get("fallback"):
                    self._log(minute, agent_id, "provider_fallback", dict(decision.provider_status))
            else:
                decision = deferred_decision

            # -- deterministic action-catalog gate (never delegated to the LLM):
            # a requested body action executes only if a connected body offered
            # it. SafeDecisionLLM already filters; this is the choke point that
            # also covers hosts driving a bare decision model.
            allowed = set(self.world.body_actions.get(agent_id, ()))
            decision.body_actions = [
                a for a in decision.body_actions if a in allowed
            ][:2]
            # an explicit gesture request must never be lost to a model that
            # answered in prose: keyword-match it deterministically, still
            # behind the same catalog gate
            if (deferred_decision is None and not decision.body_actions
                    and event.kind == EventKind.USER_UTTERANCE):
                from soulforge_harness.runtime.llm_interface import MockBehaviorLLM

                requested = MockBehaviorLLM._match_performance(event.text.lower())
                if requested and requested in allowed:
                    decision.body_actions = [requested]
            # the Joi moment must include physically coming over, whatever the
            # model chose to say
            if (
                payload.get("proactive") == "loneliness"
                and "approach_user" in allowed
                and "approach_user" not in decision.body_actions
            ):
                decision.body_actions = (
                    ["approach_user"] + decision.body_actions
                )[:2]

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
            ):
                safe_at = activity.start_min + activity.duration_min + 0.01
                scheduled = _DeferredActionEvent(
                    t_min=safe_at,
                    kind=event.kind,
                    source=event.source,
                    text=event.text,
                    payload={**event.payload, "_deferred_from": minute},
                    target_agent=agent_id,
                )
                remaining = copy.deepcopy(decision)
                remaining.dialogue = []
                remaining.memory_update = {}
                remaining.cognitive_state = {}
                self._deferred_decisions[id(scheduled)] = (scheduled, remaining)
                while len(self._deferred_decisions) > _MAX_DEFERRED_DECISIONS:
                    self._deferred_decisions.popitem(last=False)
                self.push_event(scheduled)
                if deferred_decision is None:
                    # LOW replanning has no plan mutations. Retain only its
                    # speech so neither gaze nor pause/resume disturbs the
                    # current physical activity. Cognition/state happen once.
                    speech = replace(decision, impact=ImpactLevel.LOW,
                                     body_actions=[])
                    delta = self.replanner.apply(
                        speech, event, persona, self.day_plans[agent_id], hour_plan, minute
                    )
                    delta.micro_actions = [a for a in delta.micro_actions if a.name == "speak_line"]
                    for action in delta.micro_actions:
                        action.gaze_target = None
                    self._attach_decision_context(delta, decision, payload)
                    self._apply_delta(agent_id, delta, minute)
                    for spoken in decision.dialogue[:1]:
                        history.append((persona.name, str(spoken["text"])[:120]))
                    self.conversations.after_decision(agent_id, event, decision, minute)
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

            for spoken in decision.dialogue[:1]:
                text = spoken.get("text") if isinstance(spoken, dict) else None
                if text:
                    history.append((persona.name, str(text)[:120]))

            delta = self.replanner.apply(
                decision, event, persona, self.day_plans[agent_id], hour_plan, minute
            )
            self._attach_decision_context(delta, decision, payload)
            self._apply_delta(agent_id, delta, minute)
            if deferred_decision is None:
                self.conversations.after_decision(agent_id, event, decision, minute)
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
                    "body_actions": list(decision.body_actions),
                    "provider_status": dict(decision.provider_status),
                    "llm": getattr(
                        getattr(self.llm, "inner", self.llm), "last_model", None
                    ),
                },
            )

    @staticmethod
    def _attach_decision_context(delta: PlanDelta, decision: BehaviorDecision, payload: dict) -> None:
        for action in delta.micro_actions:
            action.params = {**action.params, "provider_status": decision.provider_status}
            if decision.cognitive_state:
                action.params["cognitive_state"] = decision.cognitive_state
            if payload.get("identity"):
                action.params["identity"] = payload["identity"]
            if payload.get("reply_body_id"):
                action.params["reply_body_id"] = payload["reply_body_id"]

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
            if other == "user" and persona.meta.get("cognitive_state"):
                continue  # AI Core owns user relationship updates in unified mode.
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
