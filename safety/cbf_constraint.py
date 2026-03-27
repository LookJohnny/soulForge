"""Control Barrier Function (CBF) safety constraint.

Ref: Olaf paper Sec. V-D, formulas (5a-5c), (7-8).

Core idea: instead of hard-clamping at limits (which causes jarring stops),
CBF smoothly reduces the allowed rate of change as the state approaches
its boundary. The closer to the limit, the slower you're allowed to move
toward it. At the boundary, only retreat is allowed.

    h(x) = x_max - x ≥ 0               (safety set)
    ḣ(x) + γ·h(x) ≥ 0                  (CBF condition)
    → ẋ ≤ γ·(x_max - x)               (max approach rate)

Physical meaning: near the boundary, approach speed is proportional
to remaining distance. This creates a natural deceleration curve.
"""

from __future__ import annotations


class CBFConstraint:
    """Single-dimension CBF safety constraint.

    Args:
        name: Human-readable constraint name (e.g. "neck_servo_temp").
        x_min: Lower bound of safe range.
        x_max: Upper bound of safe range.
        gamma: CBF stiffness. Higher = harder constraint.
               Ref values: temperature 0.3 (slow), joint 20.0 (fast).
               See Olaf Tab. I: γ_q = 20 for joint limits.
        margin: Safety margin inside the physical limits.
                Ref: Olaf formula (7-8), q_m = 0.1 rad ≈ 5.7°.
    """

    def __init__(self, name: str, x_min: float, x_max: float,
                 gamma: float, margin: float = 0.0):
        if x_min >= x_max:
            raise ValueError(f"x_min ({x_min}) must be < x_max ({x_max})")
        self.name = name
        self.x_min = x_min + margin
        self.x_max = x_max - margin
        self.gamma = gamma

    def compute_violation(self, x: float, x_dot: float) -> float:
        """Compute CBF violation penalty.

        Ref: Olaf Tab. I (Limits):
          upper: violation = max(0, ẋ - γ·(x_max - x))
          lower: violation = max(0, -ẋ - γ·(x - x_min))

        Returns: ≥0 penalty. 0 means safe.
        """
        upper = max(0.0, x_dot - self.gamma * (self.x_max - x))
        lower = max(0.0, -x_dot - self.gamma * (x - self.x_min))
        return upper + lower

    def compute_safe_rate(self, x: float) -> tuple[float, float]:
        """Allowed rate-of-change range at current state.

        Returns: (x_dot_min, x_dot_max)
          x_dot_max = γ·(x_max - x)    (max approach to upper bound)
          x_dot_min = -γ·(x - x_min)   (max approach to lower bound)
        """
        return (
            -self.gamma * (x - self.x_min),
            self.gamma * (self.x_max - x),
        )

    def clamp_rate(self, x: float, x_dot: float) -> float:
        """Clamp rate of change to safe range."""
        lo, hi = self.compute_safe_rate(x)
        return max(lo, min(hi, x_dot))

    def is_safe(self, x: float) -> bool:
        """Check if current state is within safe bounds."""
        return self.x_min <= x <= self.x_max

    def margin_pct(self, x: float) -> float:
        """Percentage of remaining margin to nearest boundary."""
        if self.x_max == self.x_min:
            return 0.0
        dist_to_edge = min(x - self.x_min, self.x_max - x)
        total_range = (self.x_max - self.x_min) / 2
        return max(0.0, min(100.0, dist_to_edge / total_range * 100))

    def status(self, x: float) -> str:
        """Return status string: 'normal', 'warning', 'critical'."""
        pct = self.margin_pct(x)
        if pct > 30:
            return "normal"
        elif pct > 10:
            return "warning"
        return "critical"
