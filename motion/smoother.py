"""Motion Smoother — multi-stage signal conditioning.

Ref: Olaf paper Sec. VII-C:
  Policy 50Hz → servo 600Hz (first-order hold upsampling)
  37.5Hz cutoff Butterworth low-pass
  Impact Reduction Reward: -13.5dB noise (Sec. VIII-C)

SoulForge pipeline:
  Raw command (policy_rate Hz)
    → velocity limiter (prevent sudden starts/stops)
    → acceleration limiter (prevent impacts)
    → first-order hold upsample (policy_rate → servo_rate)
    → Butterworth low-pass filter (cutoff_hz)
    → smooth output (servo_rate Hz)
"""

from __future__ import annotations

import math


class MotionSmoother:
    """Multi-stage motion command smoother."""

    def __init__(self, policy_rate: int = 20, servo_rate: int = 100,
                 cutoff_hz: float = 15.0, max_velocity: float = 300.0,
                 max_acceleration: float = 1000.0, filter_order: int = 2):
        self.policy_rate = policy_rate
        self.servo_rate = servo_rate
        self.cutoff_hz = cutoff_hz
        self.max_velocity = max_velocity
        self.max_acceleration = max_acceleration
        self.upsample_ratio = servo_rate // policy_rate

        # Butterworth filter state (second-order section)
        self._filter_state = [0.0, 0.0]
        self._filter_coeffs = self._compute_butterworth(cutoff_hz, servo_rate, filter_order)

        # State tracking
        self._prev_position = 0.0
        self._prev_velocity = 0.0
        self._initialized = False

    def _compute_butterworth(self, cutoff: float, fs: float, order: int) -> tuple:
        """Compute 2nd-order Butterworth IIR coefficients (bilinear transform)."""
        wc = 2.0 * math.pi * cutoff
        T = 1.0 / fs
        # Pre-warp
        wc_d = 2.0 / T * math.tan(wc * T / 2.0)
        K = wc_d * T / 2.0
        K2 = K * K
        sqrt2K = math.sqrt(2.0) * K
        norm = 1.0 + sqrt2K + K2

        b0 = K2 / norm
        b1 = 2.0 * K2 / norm
        b2 = K2 / norm
        a1 = 2.0 * (K2 - 1.0) / norm
        a2 = (1.0 - sqrt2K + K2) / norm

        return (b0, b1, b2, a1, a2)

    def _apply_filter(self, x: float) -> float:
        """Apply IIR filter to one sample."""
        b0, b1, b2, a1, a2 = self._filter_coeffs
        y = b0 * x + self._filter_state[0]
        self._filter_state[0] = b1 * x - a1 * y + self._filter_state[1]
        self._filter_state[1] = b2 * x - a2 * y
        return y

    def process(self, target_position: float) -> list[float]:
        """Process one policy step. Returns list of servo-rate samples.

        Args:
            target_position: desired position at this policy step

        Returns:
            list of smoothed positions (length = upsample_ratio)
        """
        if not self._initialized:
            self._prev_position = target_position
            self._prev_velocity = 0.0
            self._filter_state = [0.0, 0.0]
            self._initialized = True
            return [target_position] * self.upsample_ratio

        dt_policy = 1.0 / self.policy_rate
        dt_servo = 1.0 / self.servo_rate

        # Step 1: Velocity limit
        desired_vel = (target_position - self._prev_position) / dt_policy
        clamped_vel = max(-self.max_velocity, min(self.max_velocity, desired_vel))

        # Step 2: Acceleration limit
        accel = (clamped_vel - self._prev_velocity) / dt_policy
        clamped_accel = max(-self.max_acceleration, min(self.max_acceleration, accel))
        final_vel = self._prev_velocity + clamped_accel * dt_policy

        limited_target = self._prev_position + final_vel * dt_policy

        # Step 3: First-order hold upsample
        upsampled = []
        for i in range(self.upsample_ratio):
            frac = (i + 1) / self.upsample_ratio
            interp = self._prev_position + (limited_target - self._prev_position) * frac
            upsampled.append(interp)

        # Step 4: Butterworth low-pass filter
        filtered = [self._apply_filter(s) for s in upsampled]

        self._prev_position = limited_target
        self._prev_velocity = final_vel

        return filtered

    def reset(self):
        """Reset filter state (call on strategy/behavior switch)."""
        self._initialized = False
        self._filter_state = [0.0, 0.0]
        self._prev_position = 0.0
        self._prev_velocity = 0.0
