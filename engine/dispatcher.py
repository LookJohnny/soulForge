"""Soft-interrupt dispatcher for the physical AI engine."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from engine.action_units import ActionTemplate, ActionUnit, compile_to_units
from engine.intent import Intent
from engine.physical_executor import ExecutionResult, PhysicalExecutor


@dataclass
class DispatchEvent:
    kind: str
    t: float
    intent_id: str
    detail: str = ""


@dataclass
class _PausedPlan:
    intent: Intent
    units: list[ActionUnit]
    cursor: int


@dataclass
class Dispatcher:
    executor: PhysicalExecutor
    templates: dict[str, ActionTemplate] | None = None
    current_intent: Intent | None = None
    unit_queue: list[ActionUnit] = field(default_factory=list)
    cursor: int = 0
    pending: Intent | None = None
    resume_stack: deque[_PausedPlan] = field(default_factory=deque)
    events: list[DispatchEvent] = field(default_factory=list)

    def submit(self, intent: Intent, now: float | None = None) -> bool:
        current_time = self.executor.elapsed_s if now is None else now
        if intent.is_expired(current_time):
            self.events.append(
                DispatchEvent("drop_expired", current_time, intent.intent_id)
            )
            return False

        if self.current_intent is None:
            self.load(intent)
            return True

        current = self.current_intent
        if intent.priority > current.priority and current.preemptible:
            self.pending = intent
            self.events.append(
                DispatchEvent(
                    "preempt_requested",
                    current_time,
                    intent.intent_id,
                    detail=f"over {current.intent_id}",
                )
            )
            return True

        if self.pending is None or intent.priority > self.pending.priority:
            self.pending = intent
            self.events.append(
                DispatchEvent("queued_pending", current_time, intent.intent_id)
            )
            return True

        self.events.append(
            DispatchEvent("drop_lower_priority", current_time, intent.intent_id)
        )
        return False

    def load(
        self, intent: Intent, units: list[ActionUnit] | None = None, cursor: int = 0
    ) -> None:
        self.current_intent = intent
        self.unit_queue = (
            units if units is not None else compile_to_units(intent, self.templates)
        )
        self.cursor = cursor
        self.events.append(
            DispatchEvent(
                "load", self.executor.elapsed_s, intent.intent_id, intent.source
            )
        )

    @property
    def is_idle(self) -> bool:
        return self.current_intent is None

    def step_unit(self) -> ExecutionResult | None:
        if self.current_intent is None:
            return None

        if self.pending is not None:
            self._switch_to_pending()

        if self.cursor >= len(self.unit_queue):
            self._finish_current()
            return None

        unit = self.unit_queue[self.cursor]
        result = self.executor.play(unit)
        self.cursor += 1

        if self.cursor >= len(self.unit_queue):
            self._finish_current()
        return result

    def run_until_idle(self, max_units: int = 100) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for _ in range(max_units):
            if self.current_intent is None:
                break
            result = self.step_unit()
            if result is not None:
                results.append(result)
        return results

    def _switch_to_pending(self) -> None:
        next_intent = self.pending
        if next_intent is None:
            return

        current = self.current_intent
        if current and current.resumable and self.cursor < len(self.unit_queue):
            self.resume_stack.append(_PausedPlan(current, self.unit_queue, self.cursor))
            self.events.append(
                DispatchEvent("pause_plan", self.executor.elapsed_s, current.intent_id)
            )
        elif current:
            self.events.append(
                DispatchEvent(
                    "drop_interrupted", self.executor.elapsed_s, current.intent_id
                )
            )

        self.pending = None
        self.load(next_intent)

    def _finish_current(self) -> None:
        finished = self.current_intent
        if finished is not None:
            self.events.append(
                DispatchEvent("finish", self.executor.elapsed_s, finished.intent_id)
            )

        self.current_intent = None
        self.unit_queue = []
        self.cursor = 0

        if self.pending is not None:
            pending = self.pending
            self.pending = None
            self.load(pending)
            return

        if self.resume_stack:
            paused = self.resume_stack.pop()
            self.load(paused.intent, units=paused.units, cursor=paused.cursor)
