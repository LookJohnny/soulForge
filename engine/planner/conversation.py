"""Agent ↔ agent conversation: the speaking floor, turn routing and aftermath.

Design
------
A conversation is a small state machine the runtime owns:

    start(a, b)  ──▶  a gets an *opening* event (source=b, role="open")
                       a decides → a's dialogue lines are recorded
                       b gets an AGENT_UTTERANCE event (source=a, text=a's line)
                       b decides → … alternate until end

The floor is strict: only the agent addressed by the last line may speak, one
line-group per turn, and each agent is in at most one conversation. Everything
the LLM needs ("who I'm talking to, our relationship, what was said") rides in
`event.payload["conversation"]`, so the `decide()` contract stays unchanged
and every existing safety guard in the runtime still runs on these events.

Ending: turn cap, an explicit `selected_intent == "end_conversation"`, a
closing line (再见/晚安…), or a silent reply. On end both sides get an
episodic memory and a relationship bump proportional to how long they talked —
this is the only place character↔character relationships move on their own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from engine.planner.models import Event, EventKind

if TYPE_CHECKING:  # pragma: no cover
    from engine.planner.llm_interface import BehaviorDecision
    from engine.planner.runtime import CompanionRuntime

CLOSING_MARKERS = (
    "再见",
    "晚安",
    "回头聊",
    "先忙",
    "下次聊",
    "拜拜",
    "bye",
    "good night",
)
# hands-busy activities nobody strikes up small talk during; everything else that
# is interruptible counts as "free" (non-interruptible activities never are)
BUSY_TEMPLATES = frozenset({"cooking", "repair"})


@dataclass
class ConversationLine:
    agent_id: str
    text: str
    emotion: str = "neutral"
    t_min: float = 0.0


@dataclass
class Conversation:
    id: str
    participants: tuple[str, str]
    topic: str
    started_at: float
    max_turns: int = 6
    lines: list[ConversationLine] = field(default_factory=list)
    next_speaker: str | None = None
    ended: bool = False
    end_reason: str = ""
    ended_at: float | None = None

    def partner_of(self, agent_id: str) -> str:
        a, b = self.participants
        return b if agent_id == a else a

    @property
    def turns(self) -> int:
        return len(self.lines)

    def transcript(self, limit: int = 8) -> list[dict[str, str]]:
        return [{"agent": ln.agent_id, "text": ln.text} for ln in self.lines[-limit:]]


@dataclass
class SocialPolicy:
    """When the household starts talking on its own. Off by default: hosts opt in."""

    auto_start: bool = False
    check_every_min: float = 15.0  # how often the runtime looks for a pair to pair up
    cooldown_min: float = 60.0  # per-agent quiet time after a conversation
    min_relationship: float = 0.5
    max_turns: int = 6
    turn_gap_min: float = 0.5  # sim minutes between one line and the reply


class ConversationManager:
    def __init__(self, runtime: CompanionRuntime, policy: SocialPolicy | None = None):
        self.runtime = runtime
        self.policy = policy or SocialPolicy()
        self.conversations: dict[str, Conversation] = {}
        self._by_agent: dict[str, str] = {}  # agent_id -> active conversation id
        self._cooldown_until: dict[str, float] = {}
        self._last_auto_check: float | None = None

    # -- queries ------------------------------------------------------------
    def active_for(self, agent_id: str) -> Conversation | None:
        cid = self._by_agent.get(agent_id)
        return self.conversations.get(cid) if cid else None

    def history(self) -> list[Conversation]:
        return list(self.conversations.values())

    # -- lifecycle ----------------------------------------------------------
    def start(
        self,
        initiator: str,
        partner: str,
        minute: float,
        topic: str = "",
        max_turns: int | None = None,
    ) -> Conversation:
        personas = self.runtime.personas
        if initiator == partner or initiator not in personas or partner not in personas:
            raise ValueError(
                f"cannot start conversation between {initiator!r} and {partner!r}"
            )
        for who in (initiator, partner):
            if who in self._by_agent:
                raise ValueError(f"{who} is already in a conversation")
        conv = Conversation(
            id=uuid.uuid4().hex[:10],
            participants=(initiator, partner),
            topic=topic or self._pick_topic(initiator, partner),
            started_at=minute,
            max_turns=max_turns or self.policy.max_turns,
            next_speaker=initiator,
        )
        self.conversations[conv.id] = conv
        self._by_agent[initiator] = conv.id
        self._by_agent[partner] = conv.id
        self.runtime.log(
            minute,
            initiator,
            "conversation_start",
            {
                "id": conv.id,
                "with": partner,
                "topic": conv.topic,
                "max_turns": conv.max_turns,
            },
        )
        # the opener hears nothing yet — the event only says "you are with X, about Y"
        self.runtime.push_event(
            Event(
                t_min=minute,
                kind=EventKind.AGENT_STATE,
                source=partner,
                text="",
                payload=self._payload(conv, initiator, role="open"),
                target_agent=initiator,
            )
        )
        return conv

    def accepts(self, event: Event, agent_id: str) -> bool:
        """Floor control: is this conversation event still valid for `agent_id`?"""
        meta = (
            event.payload.get("conversation")
            if isinstance(event.payload, dict)
            else None
        )
        if not meta:
            return True
        conv = self.conversations.get(meta.get("id", ""))
        if conv is None or conv.ended:
            return False
        return conv.next_speaker == agent_id

    def after_decision(
        self, agent_id: str, event: Event, decision: BehaviorDecision, minute: float
    ) -> None:
        """Record what `agent_id` said and hand the floor to the partner (or end)."""
        meta = (
            event.payload.get("conversation")
            if isinstance(event.payload, dict)
            else None
        )
        if not meta:
            return
        conv = self.conversations.get(meta.get("id", ""))
        if conv is None or conv.ended or conv.next_speaker != agent_id:
            return
        partner = conv.partner_of(agent_id)
        spoken = [
            ln
            for ln in decision.dialogue
            if ln.get("agent", agent_id) == agent_id and ln.get("text")
        ]
        text = " ".join(ln["text"].strip() for ln in spoken).strip()
        emotion = spoken[0].get("emotion", "neutral") if spoken else "neutral"
        if text:
            conv.lines.append(ConversationLine(agent_id, text, emotion, minute))
            self.runtime.log(
                minute,
                agent_id,
                "conversation_line",
                {
                    "id": conv.id,
                    "to": partner,
                    "text": text,
                    "emotion": emotion,
                    "turn": conv.turns,
                },
            )

        wants_end = decision.selected_intent == "end_conversation" or bool(
            decision.template_params.get("end_conversation")
        )
        # nobody hangs up before the other side has spoken at least once
        may_end = conv.turns >= 2
        if not text:
            self.end(conv, minute, "silence")
        elif may_end and (wants_end or _is_closing(text)):
            self.end(conv, minute, "closed")
        elif conv.turns >= conv.max_turns:
            self.end(conv, minute, "turn_cap")
        else:
            conv.next_speaker = partner
            self.runtime.push_event(
                Event(
                    t_min=minute + self.policy.turn_gap_min,
                    kind=EventKind.AGENT_UTTERANCE,
                    source=agent_id,
                    text=text,
                    payload=self._payload(conv, partner, role="reply"),
                    target_agent=partner,
                )
            )

    def end(self, conv: Conversation, minute: float, reason: str) -> None:
        if conv.ended:
            return
        conv.ended, conv.end_reason, conv.ended_at, conv.next_speaker = (
            True,
            reason,
            minute,
            None,
        )
        a, b = conv.participants
        for who in (a, b):
            self._by_agent.pop(who, None)
            self._cooldown_until[who] = minute + self.policy.cooldown_min
        if conv.turns:
            self._settle(conv, minute)
        self.runtime.log(
            minute,
            a,
            "conversation_end",
            {
                "id": conv.id,
                "with": b,
                "turns": conv.turns,
                "reason": reason,
                "topic": conv.topic,
            },
        )

    def maybe_auto_start(self, minute: float) -> Conversation | None:
        """Household small talk: pair two free, friendly, interruptible agents."""
        p = self.policy
        if not p.auto_start:
            return None
        if (
            self._last_auto_check is not None
            and minute - self._last_auto_check < p.check_every_min
        ):
            return None
        self._last_auto_check = minute
        free = [a for a in self.runtime.personas if self._is_free(a, minute)]
        best: tuple[float, str, str] | None = None
        for i, a in enumerate(free):
            for b in free[i + 1 :]:
                score = min(
                    self.runtime.personas[a].relationships.get(b, 0.5),
                    self.runtime.personas[b].relationships.get(a, 0.5),
                )
                if score >= p.min_relationship and (best is None or score > best[0]):
                    best = (score, a, b)
        if best is None:
            return None
        _, a, b = best
        # the more energetic one opens
        if self.runtime.personas[b].energy > self.runtime.personas[a].energy:
            a, b = b, a
        return self.start(a, b, minute)

    # -- internals ----------------------------------------------------------
    def _is_free(self, agent_id: str, minute: float) -> bool:
        if (
            agent_id in self._by_agent
            or self._cooldown_until.get(agent_id, -1) > minute
        ):
            return False
        plan = self.runtime.hour_plans.get(agent_id)
        activity = plan.activity_at(minute) if plan else None
        if activity is None:
            return True
        return activity.interruptible and activity.template_id not in BUSY_TEMPLATES

    def _pick_topic(self, initiator: str, partner: str) -> str:
        persona = self.runtime.personas[initiator]
        recent = self.runtime.memory.get(initiator, {})
        for key in ("user_mood", "last_user_request", "critical_event"):
            if recent.get(key):
                return f"{key}: {recent[key]}"[:60]
        if persona.daily_goals:
            return persona.daily_goals[0]
        return "今天过得怎么样"

    def _payload(self, conv: Conversation, listener: str, role: str) -> dict[str, Any]:
        partner = conv.partner_of(listener)
        me = self.runtime.personas[listener]
        other = self.runtime.personas[partner]
        return {
            "conversation": {
                "id": conv.id,
                "role": role,  # open | reply
                "topic": conv.topic,
                "partner_id": partner,
                "partner_name": other.name,
                "partner_traits": list(other.traits)[:4],
                "relationship": round(me.relationships.get(partner, 0.5), 2),
                "turn": conv.turns,
                "max_turns": conv.max_turns,
                "transcript": conv.transcript(),
            }
        }

    def _settle(self, conv: Conversation, minute: float) -> None:
        """Aftermath: shared memory + relationship movement for both sides."""
        rt = self.runtime
        bump = round(min(0.05, 0.01 * conv.turns), 3)
        a, b = conv.participants
        for me, other in ((a, b), (b, a)):
            persona = rt.personas[me]
            updated = min(1.0, persona.relationships.get(other, 0.5) + bump)
            persona.relationships[other] = updated
            rt.memory_store.set_relationship(me, other, updated)
            last = next(
                (ln.text for ln in reversed(conv.lines) if ln.agent_id == other), ""
            )
            key = f"talked_with_{other}"
            value = (
                f"{rt.world.clock()} 和{rt.personas[other].name}聊了「{conv.topic}」"
                + (f"，{rt.personas[other].name}说：{last[:40]}" if last else "")
            )
            rt.memory[me][key] = value
            rt.memory_store.remember(me, "episodic", key, value)


def _is_closing(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in CLOSING_MARKERS)
