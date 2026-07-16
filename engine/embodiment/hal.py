"""Hardware Abstraction Layer contract for real actuators.

This module defines the boundary a real CAN / serial / PWM driver must
implement. There is deliberately NO fake "working" driver here — writing one
that pretends to talk to hardware would be worse than none. Implementations
live next to their transport (e.g. hardware/firmware bridges) and are
validated on the bench, not in unit tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ActuatorHAL(Protocol):
    """Minimal contract a physical driver must satisfy."""

    def write_position(self, actuator_id: str, value: float, dt: float) -> None:
        """Command one actuator to a (already safety-filtered) position."""

    def read_sensors(self) -> dict[str, float]:
        """Return live readings: battery_voltage, servo_temp_<id>, load_<id> ..."""

    def emergency_stop(self) -> None:
        """Cut torque / enter the transport's safe state immediately."""

    def close(self) -> None:
        """Release the transport."""


class HALBackend:
    """Adapts an ActuatorHAL to the ExecutionBackend protocol used by
    PhysicalExecutor. Real hardware plugs in here; everything above this line
    (safety, smoothing, dispatch, planning) is transport-agnostic."""

    def __init__(self, hal: ActuatorHAL):
        self.hal = hal
        self.elapsed_s = 0.0

    def send(self, commands: list[dict], dt: float) -> None:
        self.elapsed_s += dt
        for command in commands:
            value = command.get("value")
            if isinstance(value, (int, float)):
                self.hal.write_position(command["actuator_id"], float(value), dt)

    def sensor_readings(self) -> dict[str, float]:
        return self.hal.read_sensors()

    def emergency_stop(self) -> None:
        self.hal.emergency_stop()

    def close(self) -> None:
        self.hal.close()
