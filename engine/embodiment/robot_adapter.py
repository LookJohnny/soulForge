"""Robot Embodiment Runtime: canonical Action IR -> PhysicalAIEngine.

Data path (the LLM/planner can never reach an actuator directly):

    Character Runtime -> ActionCommand (IR)
        -> RobotEmbodimentAdapter.execute()
        -> PhysicalAIEngine.submit_intent()   (old servo stack, unchanged)
        -> Dispatcher -> PhysicalExecutor -> SafetyManager -> Backend
        -> canonical Observation back to the brain

The adapter owns the robot-side authority: watchdog, deadline/TTL checks,
fault latching with a manual reset interface, and a commanded safe pose.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from engine.intent import Priority
from engine.physical_ai_engine import PhysicalAIEngine
from engine.server.protocol import ActionCommand, Observation

# planner micro-steps / animation clips -> servo-stack action templates.
# Anything not listed is REJECTED (fail closed) — never guessed.
STEP_TO_ROBOT_TEMPLATE: dict[str, str] = {
    "look_at_user": "look_at_user",
    "look_at_target": "look_at_user",
    "look_around": "curious_scan",
    "idle_breathing": "sleep_breathing",
    "listening_nod": "listening_nod",
    "micro_nod": "micro_nod",
    "scan_leaves": "curious_scan",
    "probe_soil": "thinking_idle",
    "water_plant": "daily_stretch",
    "speak_line": "listening_nod",
    "wave": "greeting_wave",
    "celebrate": "happy_wiggle",
    "wait": "idle_scan",
    "idle_scan": "idle_scan",
    "safe_stop": "sleep_breathing",
    "hold_safe_breakpoint": "idle_scan",
}

_PRIORITY_MAP = {90: Priority.REACTIVE, 50: Priority.PLAN, 10: Priority.IDLE}


@dataclass
class RobotEmbodimentAdapter:
    engine: PhysicalAIEngine
    body_id: str = "robot-0"
    step_map: dict[str, str] = field(default_factory=lambda: dict(STEP_TO_ROBOT_TEMPLATE))
    watchdog_wall_s: float = 5.0          # max wall time one command may execute
    sim_minute: Callable[[], float] = lambda: 0.0
    wall_clock: Callable[[], float] = time.monotonic

    fault_latched: bool = False
    fault_reason: str | None = None
    _executed: int = 0

    # ------------------------------------------------------------------ core
    def execute(self, command: ActionCommand,
                sensor_snapshot: dict[str, Any] | None = None) -> Observation:
        """Run one IR command to completion (or failure) and report honestly."""
        started = self.sim_minute()

        if self.fault_latched:
            return self._obs(command, "rejected", started,
                             error_code="E_FAULT_LATCHED",
                             detail=f"fault latched: {self.fault_reason}; manual reset required",
                             recoverable=False)

        if command.deadline is not None and self.sim_minute() > command.deadline:
            return self._obs(command, "rejected", started, error_code="E_EXPIRED",
                             detail="deadline passed before execution")

        template_id = self.step_map.get(command.name)
        if template_id is None or template_id not in self.engine.templates:
            return self._obs(command, "rejected", started, error_code="E_CAPABILITY",
                             detail=f"no robot mapping for step {command.name!r}")

        priority = _PRIORITY_MAP.get(command.priority, Priority.PLAN)
        wall_started = self.wall_clock()
        try:
            self.engine.submit_intent(
                source=f"ir:{command.agent_id}",
                action_template_id=template_id,
                payload={"command_id": command.command_id,
                         "params": command.params,
                         "trace": command.trace_context},
                priority=priority,
                preemptible=command.interruptible,
                ttl_ms=int(command.ttl_s * 1000),
            )
            results = []
            while True:
                result = self.engine.step_unit()
                if result is None:
                    break
                results.append(result)
                if self.wall_clock() - wall_started > self.watchdog_wall_s:
                    self._latch(f"watchdog: {command.name} exceeded {self.watchdog_wall_s}s wall time")
                    self._enter_safe_pose()
                    return self._obs(command, "failed", started, error_code="E_WATCHDOG",
                                     detail=self.fault_reason or "", recoverable=False)
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._latch(f"comm loss during {command.name}: {exc}")
            return self._obs(command, "failed", started, error_code="E_COMM_LOSS",
                             detail=str(exc), recoverable=False)
        except Exception as exc:
            return self._obs(command, "failed", started, error_code="E_EXEC",
                             detail=f"{type(exc).__name__}: {exc}")

        self._executed += 1
        if not results:
            return self._obs(command, "failed", started, error_code="E_NO_UNITS",
                             detail="dispatcher produced no executable units")

        # SafetyManager vocabulary: normal | warning | critical
        safety = results[-1].safety_status
        if safety == "critical":
            self._latch(f"safety status critical after {command.name}")
            self._enter_safe_pose()
            return self._obs(command, "failed", started, error_code="E_SAFETY",
                             detail="safety manager reported critical",
                             recoverable=False,
                             sensor_snapshot=self._sensors(sensor_snapshot))

        detail = f"{len(results)} units, safety={safety}"
        if safety == "warning":
            detail += " (degraded)"
        return self._obs(command, "done", started, detail=detail,
                         sensor_snapshot=self._sensors(sensor_snapshot))

    # --------------------------------------------------------------- faults
    def _latch(self, reason: str) -> None:
        self.fault_latched = True
        self.fault_reason = reason
        self._abort_dispatch()

    def _abort_dispatch(self) -> None:
        """Clear any half-executed plan from the servo scheduler — a faulted
        run must never resume mid-unit after reset."""
        dispatcher = self.engine.dispatcher
        dispatcher.current_intent = None
        dispatcher.unit_queue = []
        dispatcher.cursor = 0
        dispatcher.pending = None
        dispatcher.resume_stack.clear()

    def reset_faults(self, operator: str) -> bool:
        """Manual reset interface — a human explicitly clears the latch."""
        if not operator:
            return False
        self.fault_latched = False
        self.fault_reason = None
        self._abort_dispatch()
        return True

    def _enter_safe_pose(self) -> None:
        """Best-effort commanded safe posture after a fault."""
        try:
            self.engine.submit_intent("safety", "sleep_breathing",
                                      priority=Priority.REACTIVE,
                                      preemptible=False, ttl_ms=0)
            for _ in range(8):
                if self.engine.step_unit() is None:
                    break
        except Exception:
            pass  # backend may be gone; the latch already blocks further motion

    # ---------------------------------------------------------------- misc
    def _sensors(self, extra: dict[str, Any] | None) -> dict[str, Any]:
        readings = getattr(self.engine.executor.backend, "sensor_readings", None)
        snapshot = dict(readings()) if callable(readings) else {}
        if extra:
            snapshot.update(extra)
        return snapshot

    def _obs(self, command: ActionCommand, status: str, started: float, *,
             detail: str = "", error_code: str | None = None,
             recoverable: bool = True,
             sensor_snapshot: dict[str, Any] | None = None) -> Observation:
        return Observation(
            command_id=command.command_id,
            agent_id=command.agent_id,
            status=status,
            detail=detail,
            body_id=self.body_id,
            started_at=started,
            finished_at=self.sim_minute(),
            error_code=error_code,
            sensor_snapshot=sensor_snapshot or {},
            recoverable=recoverable,
        )


class FaultInjectionBackend:
    """Wraps any ExecutionBackend and injects failures on demand — the test
    rig for stalls, overheating, low battery, comm loss and illegal joints."""

    def __init__(self, inner):
        self.inner = inner
        self.active_fault: str | None = None
        self._sensor_overrides: dict[str, float] = {}
        self.sent_batches = 0

    # fault control -----------------------------------------------------
    def inject(self, fault: str, **kwargs: float) -> None:
        """fault: stall | overtemp | low_battery | comm_loss | illegal_joint | none"""
        self.active_fault = None if fault == "none" else fault
        if fault == "overtemp":
            self._sensor_overrides["servo_temp_head_yaw"] = kwargs.get("temp", 95.0)
        elif fault == "low_battery":
            # proxy manifest battery window is 4.5-5.5V; below-min triggers safety
            self._sensor_overrides["battery_voltage"] = kwargs.get("voltage", 3.9)
        elif fault == "none":
            self._sensor_overrides.clear()

    # ExecutionBackend --------------------------------------------------
    @property
    def elapsed_s(self) -> float:
        return self.inner.elapsed_s

    def send(self, commands: list[dict], dt: float) -> None:
        self.sent_batches += 1
        if self.active_fault == "comm_loss":
            raise ConnectionError("injected: serial link dropped")
        if self.active_fault == "stall":
            # joints stop responding: commands are swallowed, time still passes
            self.inner.send([], dt)
            return
        if self.active_fault == "illegal_joint":
            commands = [{**c, "value": 10_000.0} for c in commands]
        self.inner.send(commands, dt)

    def sensor_readings(self) -> dict[str, float]:
        # no fabricated defaults: only report what the inner backend knows
        # plus explicit injected overrides
        base = getattr(self.inner, "sensor_readings", None)
        readings = dict(base()) if callable(base) else {}
        readings.update(self._sensor_overrides)
        return readings

    def close(self) -> None:
        self.inner.close()
