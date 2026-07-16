"""Replanning policy: map a BehaviorDecision onto the live plans.

low      -> micro response only, plans untouched
medium   -> pause current action, insert interaction beat, patch params, resume
high     -> rewrite the current HourPlan (companion mode etc.)
critical -> rewrite the remaining DayPlan
"""

from __future__ import annotations

from engine.planner.llm_interface import BehaviorDecision
from engine.planner.models import (
    DayBlock,
    DayPlan,
    Event,
    HourPlan,
    ImpactLevel,
    MicroAction,
    Persona,
    PlanDelta,
    PlannedActivity,
)
from engine.planner.templates import resolve_template


class Replanner:
    def apply(
        self,
        decision: BehaviorDecision,
        event: Event,
        persona: Persona,
        day_plan: DayPlan,
        hour_plan: HourPlan,
        minute: float,
    ) -> PlanDelta:
        delta = self._apply(decision, event, persona, day_plan, hour_plan, minute)
        # every step born from this one decision shares a correlation id, so a
        # body can align speech, gaze and motion of the same beat
        import uuid

        # Perception/Gateway events carry an event_id. Reusing it as the action
        # correlation lets persistent bodies route unsolicited visual/audio
        # reactions to the correct turn. Untrusted/oversized values fall back
        # to a server-generated id.
        candidate = (
            event.payload.get("event_id") if isinstance(event.payload, dict) else None
        )
        correlation = (
            candidate
            if isinstance(candidate, str)
            and 1 <= len(candidate) <= 64
            and all(ch.isalnum() or ch in "-_" for ch in candidate)
            else uuid.uuid4().hex[:12]
        )
        for action in delta.micro_actions:
            action.correlation_id = correlation
        return delta

    def _apply(
        self,
        decision: BehaviorDecision,
        event: Event,
        persona: Persona,
        day_plan: DayPlan,
        hour_plan: HourPlan,
        minute: float,
    ) -> PlanDelta:
        if decision.impact == ImpactLevel.LOW:
            return self._micro(decision, event)
        if decision.impact == ImpactLevel.MEDIUM:
            return self._insert(decision, event, hour_plan, minute)
        if decision.impact == ImpactLevel.HIGH:
            return self._rewrite_hour(decision, event, persona, hour_plan, minute)
        return self._rewrite_day(decision, event, persona, day_plan, minute)

    # -- low ----------------------------------------------------------------
    def _micro(self, decision: BehaviorDecision, event: Event) -> PlanDelta:
        actions = [
            MicroAction(name="look_at_user", gaze_target=event.source, duration_s=1.2)
        ]
        actions += self._speak_actions(decision)
        actions.append(
            MicroAction(
                name="resume_activity",
                template_id=decision.template_to_call,
                duration_s=0.5,
            )
        )
        return PlanDelta(
            scope="micro",
            impact=decision.impact,
            reason=decision.reason,
            micro_actions=actions,
            memory_update=decision.memory_update,
        )

    # -- medium --------------------------------------------------------------
    def _insert(
        self,
        decision: BehaviorDecision,
        event: Event,
        hour_plan: HourPlan,
        minute: float,
    ) -> PlanDelta:
        current = hour_plan.activity_at(minute)
        template = resolve_template(current.template_id) if current else None
        actions = [
            MicroAction(
                name="pause_template",
                template_id=current.template_id if current else None,
                params={
                    "hold_clip": template.recovery if template else "idle_breathing"
                },
                duration_s=0.5,
            ),
            MicroAction(name="look_at_user", gaze_target=event.source, duration_s=1.0),
        ]
        actions += self._speak_actions(decision)
        actions.append(
            MicroAction(
                name="resume_template",
                template_id=current.template_id if current else None,
                params=dict(decision.template_params),
                duration_s=0.5,
            )
        )
        if current:
            # copy-on-write: never mutate a params dict that may be shared/aliased
            current.params = {**current.params, **decision.template_params}
        return PlanDelta(
            scope="insert",
            impact=decision.impact,
            reason=decision.reason,
            micro_actions=actions,
            param_updates=decision.template_params,
            memory_update=decision.memory_update,
        )

    # -- high ----------------------------------------------------------------
    def _rewrite_hour(
        self,
        decision: BehaviorDecision,
        event: Event,
        persona: Persona,
        hour_plan: HourPlan,
        minute: float,
    ) -> PlanDelta:
        start = int(minute)
        remaining = 60 - (start % 60)
        companion = HourPlan(
            agent_id=persona.agent_id,
            hour=hour_plan.hour,
            goal="陪伴模式：先照顾用户的情绪，再考虑原计划",
            activities=[
                PlannedActivity(
                    "chatting",
                    start,
                    max(10, remaining // 2),
                    params=dict(decision.template_params, tone="gentle"),
                    interruptible=True,
                    reason="用户情绪优先于原日程",
                ),
                PlannedActivity(
                    "rest",
                    start + max(10, remaining // 2),
                    max(5, remaining - remaining // 2),
                    params={"with_user": True},
                    interruptible=True,
                    reason="低强度共处，随用户状态调整",
                ),
            ],
            non_interruptible=[],
            expected_mood_delta=(0.25, -0.10),
        )
        actions = [
            MicroAction(name="stop_current_activity", duration_s=0.8),
            MicroAction(name="approach_user", gaze_target=event.source, duration_s=2.0),
        ]
        actions += self._speak_actions(decision)
        return PlanDelta(
            scope="hour",
            impact=decision.impact,
            reason=decision.reason,
            micro_actions=actions,
            hour_rewrite=companion,
            memory_update=decision.memory_update,
            relationship_delta={event.source: 0.03},
        )

    # -- critical --------------------------------------------------------------
    def _rewrite_day(
        self,
        decision: BehaviorDecision,
        event: Event,
        persona: Persona,
        day_plan: DayPlan,
        minute: float,
    ) -> PlanDelta:
        # day blocks live in day-local minutes; near midnight the emergency
        # window clamps at 24:00 instead of producing a reversed interval
        start_local = int(minute % (24 * 60))
        emergency_end = min(start_local + 60, 24 * 60)
        new_blocks = [b for b in day_plan.blocks if b.end_min <= start_local]
        new_blocks.append(
            DayBlock(
                start_local,
                emergency_end,
                "idle",
                f"处理紧急事件：{event.text or event.source}",
                persona.agent_id,
            )
        )
        if emergency_end < 24 * 60:
            new_blocks.append(
                DayBlock(
                    emergency_end,
                    24 * 60,
                    "rest",
                    "紧急事件后的恢复/低功耗",
                    persona.agent_id,
                )
            )
        # safe-stop flow: hold at a safe breakpoint, controlled stop, then abort —
        # a CRITICAL event must never translate into an instantaneous dangerous halt
        actions = [
            MicroAction(
                name="hold_safe_breakpoint",
                duration_s=0.5,
                params={"reason": "critical_event_incoming"},
            ),
            MicroAction(
                name="safe_stop",
                duration_s=1.2,
                params={"trigger": event.text or event.source},
            ),
            MicroAction(name="abort_all_templates", duration_s=0.3),
        ]
        actions += self._speak_actions(decision)
        return PlanDelta(
            scope="day",
            impact=decision.impact,
            reason=decision.reason,
            micro_actions=actions,
            day_rewrite=new_blocks,
            memory_update=decision.memory_update,
        )

    @staticmethod
    def _speak_actions(decision: BehaviorDecision) -> list[MicroAction]:
        return [
            MicroAction(
                name="speak_line",
                dialogue=line["text"],
                params={
                    "emotion": line.get("emotion", "neutral"),
                    "motion_style": decision.motion_style,
                },
                gaze_target="user",
                duration_s=2.8,
            )
            for line in decision.dialogue
        ]
