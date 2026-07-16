"""Frame executor for physical ActionUnits.

The executor owns the actuator safety path:

ActionUnit -> pose samples -> MotionSmoother -> SafetyManager -> backend

Backends are deliberately small. They receive already filtered hardware command
dictionaries and can send them to MuJoCo, the digital twin, or real firmware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from engine.action_units import ActionUnit, sample_pose
from motion.smoother import MotionSmoother
from safety.safety_manager import SafetyManager
from simulator.toy_simulator import ToySimulator


class ExecutionBackend(Protocol):
    elapsed_s: float

    def send(self, commands: list[dict], dt: float) -> None:
        """Apply one frame of safe hardware commands."""

    def close(self) -> None:
        """Release backend resources."""


@dataclass
class ExecutionResult:
    unit: ActionUnit
    frames: int
    duration_s: float
    end_pose: dict[str, float]
    safety_status: str


class RecordingBackend:
    """In-memory backend for tests and offline command inspection."""

    def __init__(self):
        self.elapsed_s = 0.0
        self.frames: list[dict] = []

    def send(self, commands: list[dict], dt: float) -> None:
        self.elapsed_s += dt
        self.frames.append(
            {
                "t": round(self.elapsed_s, 6),
                "commands": [dict(command) for command in commands],
            }
        )

    def close(self) -> None:
        return None


class ToySimulatorBackend:
    """Backend that feeds safe commands into the existing ToySimulator."""

    def __init__(self, manifest: dict):
        self.elapsed_s = 0.0
        self.simulator = ToySimulator(manifest)
        self.states = []

    def send(self, commands: list[dict], dt: float) -> None:
        self.elapsed_s += dt
        self.states.append(self.simulator.step(commands, dt))

    def close(self) -> None:
        return None


@dataclass
class PhysicalExecutor:
    manifest: dict
    backend: ExecutionBackend
    fps: int = 30
    safety: SafetyManager = field(init=False)
    smoothers: dict[str, MotionSmoother] = field(init=False)
    last_pose: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.safety = SafetyManager(self.manifest)
        self.smoothers = {}
        for actuator in self.manifest.get("actuators", []):
            if actuator.get("type") != "servo":
                continue
            actuator_id = actuator["id"]
            self.smoothers[actuator_id] = MotionSmoother(
                policy_rate=self.fps,
                servo_rate=self.fps,
                cutoff_hz=10.0,
                max_velocity=float(actuator.get("max_speed", 120)),
                max_acceleration=float(actuator.get("max_acceleration", 500)),
            )

    @property
    def elapsed_s(self) -> float:
        return self.backend.elapsed_s

    def play(self, unit: ActionUnit) -> ExecutionResult:
        dt = 1.0 / self.fps
        frame_count = max(1, round(unit.duration_s * self.fps))

        for frame_idx in range(frame_count):
            elapsed = min(unit.duration_s, frame_idx * dt)
            target_pose = sample_pose(unit.keyframes, elapsed)
            safe_commands = self._filter_pose(target_pose, dt)
            self.backend.send(safe_commands, dt)

        final_commands = self._filter_pose(unit.end_pose, dt)
        self.backend.send(final_commands, dt)
        self.last_pose.update(
            {
                command["actuator_id"]: float(command["value"])
                for command in final_commands
                if isinstance(command.get("value"), (int, float))
            }
        )

        return ExecutionResult(
            unit=unit,
            frames=frame_count + 1,
            duration_s=(frame_count + 1) * dt,
            end_pose=dict(self.last_pose),
            safety_status=self.safety.get_safety_status()["overall_status"],
        )

    def _filter_pose(self, pose: dict[str, float], dt: float) -> list[dict]:
        commands = []
        for actuator_id, target in pose.items():
            smoother = self.smoothers.get(actuator_id)
            value = smoother.process(float(target))[-1] if smoother else float(target)
            commands.append(
                {
                    "actuator_id": actuator_id,
                    "command_type": "position",
                    "value": value,
                }
            )
        # feed live sensor readings (battery, servo temps ...) into the safety
        # layer when the backend exposes them — hardware closes this loop
        readings = getattr(self.backend, "sensor_readings", None)
        sensor_readings = readings() if callable(readings) else None
        return self.safety.filter(commands, sensor_readings=sensor_readings, dt=dt)

    def close(self) -> None:
        self.backend.close()
