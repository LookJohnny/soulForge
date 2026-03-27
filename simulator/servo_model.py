"""Servo actuator physics model for digital twin simulation."""

from __future__ import annotations
import math


class ServoModel:
    """Simulates a single servo actuator with inertia and friction."""

    def __init__(self, range_min: float = -90, range_max: float = 90,
                 max_speed: float = 300, damping: float = 0.15,
                 noise_std: float = 0.5):
        self.range_min = range_min
        self.range_max = range_max
        self.max_speed = max_speed
        self.damping = damping
        self.noise_std = noise_std
        self.position = 0.0
        self.velocity = 0.0

    def step(self, target: float, dt: float) -> float:
        target = max(self.range_min, min(self.range_max, target))
        error = target - self.position
        desired_vel = error / max(dt, 1e-6)
        desired_vel = max(-self.max_speed, min(self.max_speed, desired_vel))
        self.velocity += (desired_vel - self.velocity) * min(1.0, (1.0 - self.damping))
        self.position += self.velocity * dt
        self.position = max(self.range_min, min(self.range_max, self.position))
        return self.position

    def reset(self, position: float = 0.0):
        self.position = position
        self.velocity = 0.0
