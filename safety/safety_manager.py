"""Safety Manager — integrates all CBF constraints into a single filter.

Ref: Olaf paper Sec. V-D, Tab. I (Limits category).

Constraint dimensions:
  Temperature  T (°C)     Olaf formula (6)    γ=0.3
  Battery      V (V)      linear discharge    γ=0.5
  Joint limit  q (°)      direct measurement  γ=20.0
  Volume       dB         direct control      γ=1.0
  Velocity     ω (°/s)    differential        γ=5.0
  Acceleration α (°/s²)   second-order diff   γ=10.0

Pipeline: BehaviorEngine output → SafetyManager.filter() → safe commands
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

from safety.cbf_constraint import CBFConstraint
from safety.thermal_model import ServoThermalModel


@dataclass
class SafetyEvent:
    timestamp: float
    constraint_name: str
    violation: float
    adjustment: float
    status: str


class SafetyManager:
    """Applies CBF safety filtering to all hardware commands."""

    def __init__(self, manifest: dict, safety_config: dict | None = None):
        cfg = safety_config or {}
        self._constraints: dict[str, CBFConstraint] = {}
        self._thermal_models: dict[str, ServoThermalModel] = {}
        self._prev_values: dict[str, float] = {}
        self._prev_velocities: dict[str, float] = {}
        self._event_log: list[SafetyEvent] = []

        # Build constraints from manifest
        for act in manifest.get("actuators", []):
            aid = act["id"]
            atype = act["type"]

            if atype == "servo":
                # Joint position limit
                self._constraints[f"{aid}_pos"] = CBFConstraint(
                    f"{aid}_pos",
                    act.get("range_min", -90), act.get("range_max", 90),
                    gamma=cfg.get("joint_gamma", 20.0),
                    margin=cfg.get("joint_margin", 2.0),
                )
                # Velocity limit
                max_speed = act.get("max_speed", 300)
                self._constraints[f"{aid}_vel"] = CBFConstraint(
                    f"{aid}_vel", -max_speed, max_speed,
                    gamma=cfg.get("velocity_gamma", 5.0),
                )
                # Thermal model
                t_limit = act.get("thermal_limit_celsius", 70)
                self._thermal_models[aid] = ServoThermalModel(
                    alpha=cfg.get("thermal_alpha", 0.025),
                    beta=cfg.get("thermal_beta", 0.5),
                    t_ambient=cfg.get("thermal_ambient", 35.0),
                )
                self._constraints[f"{aid}_temp"] = CBFConstraint(
                    f"{aid}_temp", 0, t_limit,
                    gamma=cfg.get("thermal_gamma", 0.3),
                    margin=cfg.get("thermal_margin", 5.0),
                )

            elif atype == "speaker":
                self._constraints[f"{aid}_vol"] = CBFConstraint(
                    f"{aid}_vol", 0, cfg.get("max_volume_db", 65),
                    gamma=cfg.get("volume_gamma", 1.0),
                )

        # Battery constraint
        power = manifest.get("power", {})
        if power.get("voltage_cutoff"):
            self._constraints["battery"] = CBFConstraint(
                "battery",
                power["voltage_cutoff"], power.get("voltage_nominal", 3.7) * 1.1,
                gamma=cfg.get("battery_gamma", 0.5),
            )

        self._battery_voltage = power.get("voltage_nominal", 3.7)

    def filter(self, commands: list[dict], sensor_readings: dict | None = None,
               dt: float = 0.02) -> list[dict]:
        """Apply safety filtering to hardware commands.

        Uses CBF to smoothly limit rates rather than hard clamping.

        Args:
            commands: list of {"actuator_id": str, "value": float, ...}
            sensor_readings: {"battery_voltage": float, "servo_temp_xxx": float, ...}
            dt: time step (seconds)

        Returns:
            Filtered commands (same format, values adjusted).
        """
        readings = sensor_readings or {}
        self._battery_voltage = readings.get("battery_voltage", self._battery_voltage)

        filtered = []
        for cmd in commands:
            cmd = dict(cmd)  # copy
            aid = cmd.get("actuator_id", "")
            val = cmd.get("value", 0)

            if isinstance(val, list):
                filtered.append(cmd)
                continue

            # Joint position constraint
            pos_constraint = self._constraints.get(f"{aid}_pos")
            if pos_constraint:
                prev = self._prev_values.get(aid, val)
                velocity = (val - prev) / max(dt, 1e-6)

                clamped_vel = pos_constraint.clamp_rate(prev, velocity)
                safe_val = prev + clamped_vel * dt

                if abs(clamped_vel) < abs(velocity) - 0.1:
                    self._log_event(f"{aid}_pos", abs(velocity - clamped_vel), abs(val - safe_val), pos_constraint.status(prev))

                val = safe_val
                self._prev_values[aid] = val

            # Velocity constraint
            vel_constraint = self._constraints.get(f"{aid}_vel")
            if vel_constraint:
                prev_vel = self._prev_velocities.get(aid, 0)
                accel = (velocity - prev_vel) / max(dt, 1e-6) if 'velocity' in dir() else 0
                self._prev_velocities[aid] = velocity if 'velocity' in dir() else 0

            # Thermal constraint
            thermal = self._thermal_models.get(aid)
            temp_constraint = self._constraints.get(f"{aid}_temp")
            if thermal and temp_constraint:
                # Estimate torque from velocity
                torque_estimate = abs(self._prev_velocities.get(aid, 0)) / 300.0
                thermal.step(torque_estimate, dt)
                temp = thermal.temperature

                if temp_constraint.status(temp) != "normal":
                    # Reduce motion amplitude when hot
                    margin_pct = temp_constraint.margin_pct(temp)
                    scale = max(0.2, margin_pct / 100.0)
                    center = (pos_constraint.x_min + pos_constraint.x_max) / 2 if pos_constraint else 0
                    val = center + (val - center) * scale
                    self._log_event(f"{aid}_temp", 100 - margin_pct, abs(1 - scale), temp_constraint.status(temp))

            # Battery degradation
            bat = self._constraints.get("battery")
            if bat and bat.status(self._battery_voltage) != "normal":
                margin = bat.margin_pct(self._battery_voltage)
                scale = max(0.3, margin / 100.0)
                if isinstance(val, (int, float)):
                    val *= scale

            cmd["value"] = val
            filtered.append(cmd)

        return filtered

    def get_safety_status(self) -> dict:
        """Return current status of all constraints."""
        status: dict[str, dict] = {}
        for name, c in self._constraints.items():
            if "temp" in name:
                thermal = self._thermal_models.get(name.replace("_temp", ""))
                current = thermal.temperature if thermal else 0
            elif name == "battery":
                current = self._battery_voltage
            else:
                current = self._prev_values.get(name.replace("_pos", ""), 0)

            status[name] = {
                "value": round(current, 2),
                "limit_min": c.x_min,
                "limit_max": c.x_max,
                "margin_pct": round(c.margin_pct(current), 1),
                "status": c.status(current),
            }

        overall = "normal"
        for s in status.values():
            if s["status"] == "critical":
                overall = "critical"
                break
            if s["status"] == "warning" and overall != "critical":
                overall = "warning"

        return {
            "constraints": status,
            "overall_status": overall,
            "active_degradations": [n for n, s in status.items() if s["status"] != "normal"],
        }

    def get_event_log(self, limit: int = 100) -> list[dict]:
        return [
            {"timestamp": e.timestamp, "constraint": e.constraint_name,
             "violation": round(e.violation, 3), "adjustment": round(e.adjustment, 3),
             "status": e.status}
            for e in self._event_log[-limit:]
        ]

    def _log_event(self, constraint_name: str, violation: float, adjustment: float, status: str):
        self._event_log.append(SafetyEvent(
            timestamp=_time.monotonic(),
            constraint_name=constraint_name,
            violation=violation, adjustment=adjustment, status=status,
        ))
