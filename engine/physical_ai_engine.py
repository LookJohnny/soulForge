"""High-level physical AI engine facade."""

from __future__ import annotations

from dataclasses import dataclass

from engine.action_units import ActionTemplate, DEFAULT_ACTION_TEMPLATES
from engine.daily_autonomy import DailyAutonomyPlanner, DailyPlan
from engine.dispatcher import Dispatcher
from engine.environment_events import EnvironmentAdapter, event_to_template
from engine.intent import Intent, Priority
from engine.llm_behavior_planner import BehaviorPlan, LLMBehaviorPlanner
from engine.physical_executor import ExecutionBackend, ExecutionResult, PhysicalExecutor


@dataclass
class AutonomyReport:
    duration_s: float
    units_played: int
    intents_submitted: int
    safety_status: str
    dispatch_events: int


class PhysicalAIEngine:
    """Composable physical AI engine.

    This class is the public entrypoint for demos and future gateway/hardware
    integration. It deliberately does not know about LLMs, ASR, or firmware
    protocols; it accepts Intents and produces safe actuator commands.
    """

    def __init__(
        self,
        manifest: dict,
        backend: ExecutionBackend,
        *,
        control_hz: int = 30,
        templates: dict[str, ActionTemplate] | None = None,
    ):
        self.templates = templates or DEFAULT_ACTION_TEMPLATES
        self.executor = PhysicalExecutor(
            manifest=manifest, backend=backend, fps=control_hz
        )
        self.dispatcher = Dispatcher(executor=self.executor, templates=self.templates)
        self.llm_planner = LLMBehaviorPlanner(self.templates)
        self._submitted = 0

    @property
    def elapsed_s(self) -> float:
        return self.executor.elapsed_s

    def submit_intent(
        self,
        source: str,
        action_template_id: str,
        *,
        payload: dict | None = None,
        priority: Priority | int | None = None,
        preemptible: bool | None = None,
        ttl_ms: int = 8000,
    ) -> Intent:
        intent = Intent.create(
            source=source,
            action_template_id=action_template_id,
            payload=payload,
            priority=priority,
            preemptible=preemptible,
            ttl_ms=ttl_ms,
            created_at=self.elapsed_s,
        )
        self.dispatcher.submit(intent, now=self.elapsed_s)
        self._submitted += 1
        return intent

    def plan_llm_response(
        self,
        response: object,
        *,
        context: dict | None = None,
    ) -> BehaviorPlan:
        return self.llm_planner.plan(response, context=context)

    def submit_llm_response(
        self,
        response: object,
        *,
        context: dict | None = None,
    ) -> Intent:
        plan = self.plan_llm_response(response, context=context)
        intent = plan.to_intent(
            payload={
                "llm_response": response
                if isinstance(response, dict)
                else str(response),
            }
        )
        intent.created_at = self.elapsed_s
        self.dispatcher.submit(intent, now=self.elapsed_s)
        self._submitted += 1
        return intent

    def step_unit(self) -> ExecutionResult | None:
        return self.dispatcher.step_unit()

    def run_until_idle(self, max_units: int = 100) -> list[ExecutionResult]:
        return self.dispatcher.run_until_idle(max_units=max_units)

    def run_autonomous(
        self,
        duration_s: float,
        *,
        idle_template_id: str = "idle_scan",
        plan_interval_s: float = 180.0,
        reactive_schedule: list[tuple[float, str]] | None = None,
        max_units: int = 500_000,
    ) -> AutonomyReport:
        """Run autonomous physical activity for a simulated duration.

        `reactive_schedule` contains `(time_s, template_id)` events. These are
        useful for acceptance tests that inject user-like interactions while
        the engine otherwise idles and self-initiates plan actions.
        """
        schedule = sorted(reactive_schedule or [], key=lambda item: item[0])
        schedule_idx = 0
        next_plan_s = min(plan_interval_s, duration_s + 1)
        plan_templates = (
            "greeting_wave",
            "daily_stretch",
            "happy_wiggle",
            "listening_nod",
        )
        plan_idx = 0
        units_played = 0

        while self.elapsed_s < duration_s and units_played < max_units:
            while (
                schedule_idx < len(schedule)
                and schedule[schedule_idx][0] <= self.elapsed_s
            ):
                _, template_id = schedule[schedule_idx]
                self.submit_intent(
                    "reactive",
                    template_id,
                    priority=Priority.REACTIVE,
                    preemptible=False,
                    ttl_ms=0,
                )
                schedule_idx += 1

            if self.elapsed_s >= next_plan_s:
                self.submit_intent(
                    "plan",
                    plan_templates[plan_idx % len(plan_templates)],
                    priority=Priority.PLAN,
                    preemptible=True,
                    ttl_ms=0,
                )
                plan_idx += 1
                next_plan_s += plan_interval_s

            if self.dispatcher.is_idle:
                self.submit_intent(
                    "idle",
                    idle_template_id,
                    priority=Priority.IDLE,
                    preemptible=True,
                    ttl_ms=0,
                )

            result = self.dispatcher.step_unit()
            if result is not None:
                units_played += 1
            else:
                break

        return AutonomyReport(
            duration_s=self.elapsed_s,
            units_played=units_played,
            intents_submitted=self._submitted,
            safety_status=self.executor.safety.get_safety_status()["overall_status"],
            dispatch_events=len(self.dispatcher.events),
        )

    def run_daily_autonomy(
        self,
        duration_s: float,
        *,
        planner: DailyAutonomyPlanner | None = None,
        daily_plan: DailyPlan | None = None,
        environment: EnvironmentAdapter | None = None,
        start_minute_of_day: int = 0,
        max_units: int = 500_000,
    ) -> AutonomyReport:
        """Run hierarchical daily autonomy.

        The engine follows a 24-hour plan, expands the active hour into
        minute-level actions, and fills gaps with low-priority idle motion.
        External environment events are converted to reactive intents.
        """
        planner = planner or DailyAutonomyPlanner()
        plan = daily_plan or planner.build_24h_plan()
        last_planned_minute: int | None = None
        last_event_poll_s = self.elapsed_s
        units_played = 0

        while self.elapsed_s < duration_s and units_played < max_units:
            if environment is not None:
                for event in environment.events_between(
                    last_event_poll_s + 1e-9, self.elapsed_s
                ):
                    self.submit_intent(
                        "reactive",
                        event_to_template(event),
                        payload={
                            "environment_event": event.payload,
                            "event_type": event.event_type,
                        },
                        priority=Priority.REACTIVE,
                        preemptible=False,
                        ttl_ms=0,
                    )
                last_event_poll_s = self.elapsed_s

            current_minute = int(self.elapsed_s // 60)
            if current_minute != last_planned_minute:
                minute_action = planner.action_for_elapsed(
                    plan,
                    self.elapsed_s,
                    start_minute_of_day=start_minute_of_day,
                )
                self.submit_intent(
                    minute_action.source,
                    minute_action.action_template_id,
                    payload={
                        "minute_action": {
                            "minute_of_day": minute_action.minute_of_day,
                            "activity_type": minute_action.activity_type,
                            "reason": minute_action.reason,
                            "metadata": minute_action.metadata,
                        }
                    },
                    priority=minute_action.priority,
                    preemptible=(minute_action.source != "reactive"),
                    ttl_ms=0,
                )
                last_planned_minute = current_minute

            if self.dispatcher.is_idle:
                self.submit_intent(
                    "idle", "idle_scan", priority=Priority.IDLE, ttl_ms=0
                )

            result = self.dispatcher.step_unit()
            if result is not None:
                units_played += 1
            else:
                break

        return AutonomyReport(
            duration_s=self.elapsed_s,
            units_played=units_played,
            intents_submitted=self._submitted,
            safety_status=self.executor.safety.get_safety_status()["overall_status"],
            dispatch_events=len(self.dispatcher.events),
        )

    def close(self) -> None:
        self.executor.close()
