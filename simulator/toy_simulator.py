"""Digital Twin Toy Simulator.

Simulates a complete physical toy: servos, LEDs, battery, thermal.
Integrates with BehaviorEngine and SafetyManager for full pipeline testing.
Can be wrapped as a Gymnasium environment for RL training.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from simulator.servo_model import ServoModel
from simulator.battery_model import BatteryModel
from safety.thermal_model import ServoThermalModel


@dataclass
class SimState:
    """Snapshot of simulator state at one time step."""
    time: float = 0.0
    servo_positions: dict[str, float] = field(default_factory=dict)
    servo_temperatures: dict[str, float] = field(default_factory=dict)
    led_values: dict[str, list] = field(default_factory=dict)
    battery_voltage: float = 3.7
    battery_soc: float = 100.0


@dataclass
class SimReport:
    """Full simulation report."""
    duration_s: float = 0.0
    total_frames: int = 0
    states: list[SimState] = field(default_factory=list)
    peak_temperature: float = 0.0
    min_battery_voltage: float = 3.7
    avg_current_draw_ma: float = 0.0


class ToySimulator:
    """Full toy digital twin."""

    def __init__(self, manifest: dict):
        self.manifest = manifest
        self._servos: dict[str, ServoModel] = {}
        self._thermals: dict[str, ServoThermalModel] = {}
        self._battery = BatteryModel(
            capacity_mah=manifest.get("power", {}).get("battery_capacity_mah", 2500),
            voltage_nominal=manifest.get("power", {}).get("voltage_nominal", 3.7),
            voltage_cutoff=manifest.get("power", {}).get("voltage_cutoff", 3.3),
        )
        self._led_state: dict[str, list] = {}
        self._time = 0.0

        # Initialize actuator models
        for act in manifest.get("actuators", []):
            aid = act["id"]
            if act["type"] == "servo":
                self._servos[aid] = ServoModel(
                    range_min=act.get("range_min", -90),
                    range_max=act.get("range_max", 90),
                    max_speed=act.get("max_speed", 300),
                )
                self._thermals[aid] = ServoThermalModel()
            elif act["type"] in ("led_rgb", "led_matrix"):
                self._led_state[aid] = [0, 0, 0]
            elif act["type"] == "led_single":
                self._led_state[aid] = [0]

    def step(self, commands: list[dict], dt: float = 0.02) -> SimState:
        """Execute commands and advance simulation one step."""
        self._time += dt
        total_current = 50.0  # base idle current (mA)

        # Process commands
        for cmd in commands:
            aid = cmd.get("actuator_id", "")
            val = cmd.get("value", 0)
            ctype = cmd.get("command_type", "")

            if aid in self._servos and ctype == "position":
                servo = self._servos[aid]
                servo.step(float(val), dt)
                # Estimate current from velocity
                current = abs(servo.velocity) * 0.5  # rough: 0.5mA per deg/s
                total_current += current
                # Thermal update
                torque = abs(servo.velocity) / max(servo.max_speed, 1)
                if aid in self._thermals:
                    self._thermals[aid].step(torque, dt)

            elif aid in self._led_state and ctype in ("color", "brightness"):
                if isinstance(val, list):
                    self._led_state[aid] = val[:3]
                else:
                    self._led_state[aid] = [int(float(val) * 255)]
                total_current += 20  # LED current

        # Battery
        voltage = self._battery.step(total_current, dt)

        return SimState(
            time=round(self._time, 4),
            servo_positions={aid: round(s.position, 2) for aid, s in self._servos.items()},
            servo_temperatures={aid: round(t.temperature, 1) for aid, t in self._thermals.items()},
            led_values=dict(self._led_state),
            battery_voltage=round(voltage, 3),
            battery_soc=round(self._battery.soc_pct, 1),
        )

    def run(self, command_sequence: list[list[dict]], dt: float = 0.02) -> SimReport:
        """Run a full command sequence and produce a report."""
        self.reset()
        states = []
        peak_temp = 0.0
        min_voltage = 5.0
        total_current = 0.0

        for frame_cmds in command_sequence:
            state = self.step(frame_cmds, dt)
            states.append(state)
            for t in state.servo_temperatures.values():
                peak_temp = max(peak_temp, t)
            min_voltage = min(min_voltage, state.battery_voltage)
            total_current += self._battery.current_draw_ma

        n = len(command_sequence)
        return SimReport(
            duration_s=round(n * dt, 2),
            total_frames=n,
            states=states,
            peak_temperature=round(peak_temp, 1),
            min_battery_voltage=round(min_voltage, 3),
            avg_current_draw_ma=round(total_current / max(n, 1), 1),
        )

    def reset(self):
        self._time = 0.0
        for s in self._servos.values():
            s.reset()
        for t in self._thermals.values():
            t.reset()
        self._battery.reset()
        for k in self._led_state:
            self._led_state[k] = [0] * len(self._led_state[k])

    def get_state(self) -> SimState:
        return SimState(
            time=round(self._time, 4),
            servo_positions={aid: round(s.position, 2) for aid, s in self._servos.items()},
            servo_temperatures={aid: round(t.temperature, 1) for aid, t in self._thermals.items()},
            led_values=dict(self._led_state),
            battery_voltage=round(self._battery.step(0, 0), 3),
            battery_soc=round(self._battery.soc_pct, 1),
        )
