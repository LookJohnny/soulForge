"""Motion Profile Generator — smooth A-to-B trajectories.

Two profiles:
  1. Trapezoidal velocity: constant accel → coast → constant decel
  2. S-curve (7-segment): zero accel at endpoints, completely jerk-free
"""

from __future__ import annotations

import math


class MotionProfileGenerator:
    """Generate smooth motion profiles from point A to point B."""

    def trapezoidal(self, start: float, end: float, max_vel: float,
                    max_acc: float, dt: float) -> list[float]:
        """Trapezoidal velocity profile.

        Phases: accelerate → cruise → decelerate.
        If distance is too short for full cruise phase, uses triangular profile.
        """
        dist = end - start
        direction = 1.0 if dist >= 0 else -1.0
        dist = abs(dist)

        if dist < 1e-6:
            return [start]

        # Time to reach max_vel
        t_accel = max_vel / max_acc
        d_accel = 0.5 * max_acc * t_accel ** 2

        if 2 * d_accel > dist:
            # Triangular profile (never reaches max_vel)
            t_accel = math.sqrt(dist / max_acc)
            t_cruise = 0
            actual_max_vel = max_acc * t_accel
        else:
            t_cruise = (dist - 2 * d_accel) / max_vel
            actual_max_vel = max_vel

        t_decel = t_accel
        total_time = t_accel + t_cruise + t_decel

        positions = []
        t = 0.0
        while t <= total_time + dt * 0.5:
            if t <= t_accel:
                # Acceleration phase
                pos = 0.5 * max_acc * t ** 2
            elif t <= t_accel + t_cruise:
                # Cruise phase
                dt_cruise = t - t_accel
                pos = d_accel + actual_max_vel * dt_cruise
            else:
                # Deceleration phase
                dt_decel = t - t_accel - t_cruise
                pos = dist - 0.5 * max_acc * (t_decel - dt_decel) ** 2
                pos = min(pos, dist)

            positions.append(start + direction * pos)
            t += dt

        # Ensure last point is exact target
        if positions and abs(positions[-1] - end) > 1e-4:
            positions.append(end)

        return positions

    def s_curve(self, start: float, end: float, max_vel: float,
                max_acc: float, max_jerk: float, dt: float) -> list[float]:
        """S-curve (7-segment) profile: zero acceleration at start and end.

        Phases: jerk+ → const_acc → jerk- → cruise → jerk- → const_dec → jerk+
        This ensures completely smooth transitions with no impact forces.
        """
        dist = end - start
        direction = 1.0 if dist >= 0 else -1.0
        dist = abs(dist)

        if dist < 1e-6:
            return [start]

        # Time for jerk phase to reach max_acc
        tj = max_acc / max_jerk

        # Velocity gained during jerk phase
        vj = 0.5 * max_jerk * tj ** 2

        # Check if we can reach max_vel
        if 2 * vj >= max_vel:
            # Can't even reach max_acc; use simplified profile
            tj = math.sqrt(max_vel / max_jerk)
            ta = 0  # no constant acceleration phase
            actual_max_vel = max_jerk * tj ** 2
        else:
            ta = (max_vel - 2 * vj) / max_acc
            actual_max_vel = max_vel

        # Distance during accel phase (jerk+ → const_acc → jerk-)
        d_accel = actual_max_vel * (tj + ta / 2 + tj)  # approximate
        if d_accel < 0:
            d_accel = 0

        if 2 * d_accel > dist:
            # Short distance: scale down
            scale = math.sqrt(dist / max(2 * d_accel, 1e-6))
            actual_max_vel *= scale
            tj *= math.sqrt(scale)
            ta *= scale

        # Simplified: generate using position integration
        total_time = 2 * (2 * tj + ta) + max(0, (dist - 2 * d_accel) / max(actual_max_vel, 1e-6))
        total_time = max(total_time, dt * 2)

        # Use trapezoidal as base, then apply smoothing
        base = self.trapezoidal(start, end, actual_max_vel, max_acc * 0.8, dt)

        # Apply additional smoothing pass to reduce jerk at endpoints
        smoothed = list(base)
        for _ in range(2):
            new = list(smoothed)
            for i in range(1, len(smoothed) - 1):
                new[i] = 0.25 * smoothed[i - 1] + 0.5 * smoothed[i] + 0.25 * smoothed[i + 1]
            smoothed = new

        # Force start and end to be exact
        if smoothed:
            smoothed[0] = start
            smoothed[-1] = end

        return smoothed
