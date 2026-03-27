"""Servo thermal model.

Ref: Olaf paper Sec. V-D formula (6), Sec. VII-A, Tab. II.

    Ṫ = -α·(T - T_ambient) + β·τ²

Where:
  α: heat dissipation coefficient (cooling rate)
  β: heat generation coefficient (torque-to-heat conversion)
  T_ambient: ambient temperature inside the toy enclosure

Olaf fitted values (Tab. II): α=0.038, β=0.377, T_ambient=43.94°C

SoulForge adjustments for plush toys:
  - More enclosed → higher T_ambient (~35°C for plush vs 44°C for Olaf)
  - Cheaper servos → worse dissipation (lower α ~0.025)
  - Lower torque → smaller β impact
"""

from __future__ import annotations

import math


class ServoThermalModel:
    """First-order thermal dynamics for a single servo.

    Uses explicit Euler integration consistent with Olaf Sec. VII-A
    at 50Hz sampling rate.
    """

    def __init__(self, alpha: float = 0.025, beta: float = 0.5,
                 t_ambient: float = 35.0, t_initial: float = 35.0):
        self.alpha = alpha
        self.beta = beta
        self.t_ambient = t_ambient
        self.temperature = t_initial

    def step(self, torque: float, dt: float) -> float:
        """Advance one time step.

        Ṫ = -α·(T - T_ambient) + β·τ²
        T_new = T + Ṫ·dt
        """
        t_dot = -self.alpha * (self.temperature - self.t_ambient) + self.beta * torque * torque
        self.temperature += t_dot * dt
        return self.temperature

    def predict_trajectory(self, torque_sequence: list[float], dt: float) -> list[float]:
        """Predict temperature evolution for a torque sequence (non-destructive)."""
        temps = []
        t = self.temperature
        for tau in torque_sequence:
            t_dot = -self.alpha * (t - self.t_ambient) + self.beta * tau * tau
            t += t_dot * dt
            temps.append(t)
        return temps

    def steady_state(self, constant_torque: float) -> float:
        """Analytical steady-state temperature at constant torque.

        At steady state, Ṫ = 0:
        0 = -α·(T_ss - T_ambient) + β·τ²
        T_ss = T_ambient + β·τ² / α
        """
        return self.t_ambient + self.beta * constant_torque ** 2 / self.alpha

    def time_to_overheat(self, constant_torque: float, t_max: float,
                         dt: float = 0.02, max_time: float = 3600.0) -> float:
        """Estimate time to reach t_max at constant torque.

        Returns time in seconds, or max_time if steady state < t_max.
        """
        if self.steady_state(constant_torque) < t_max:
            return max_time  # will never reach

        t = self.temperature
        elapsed = 0.0
        while elapsed < max_time:
            t_dot = -self.alpha * (t - self.t_ambient) + self.beta * constant_torque ** 2
            t += t_dot * dt
            elapsed += dt
            if t >= t_max:
                return elapsed
        return max_time

    def reset(self, temperature: float | None = None):
        """Reset to initial or specified temperature."""
        self.temperature = temperature if temperature is not None else self.t_ambient

    @classmethod
    def fit_from_data(cls, timestamps: list[float], temperatures: list[float],
                      torques: list[float]) -> tuple[float, float, float]:
        """Fit model parameters from measured data.

        Ref: Olaf Sec. VII-A — least-squares regression on the
        explicit Euler discretization.

        Given: T_{k+1} = T_k + dt·(-α·(T_k - T_amb) + β·τ_k²)
        Rearrange: (T_{k+1} - T_k)/dt = -α·T_k + α·T_amb + β·τ_k²

        Let y_k = (T_{k+1} - T_k) / dt_k
        Then: y_k = [-T_k, 1, τ_k²] · [α, α·T_amb, β]ᵀ

        Solve via least squares.

        Returns: (alpha, beta, t_ambient)
        """
        import numpy as np

        n = len(timestamps) - 1
        if n < 3:
            raise ValueError("Need at least 4 data points")

        A = np.zeros((n, 3))
        b = np.zeros(n)

        for k in range(n):
            dt = timestamps[k + 1] - timestamps[k]
            if dt <= 0:
                continue
            y = (temperatures[k + 1] - temperatures[k]) / dt
            A[k, 0] = -temperatures[k]
            A[k, 1] = 1.0
            A[k, 2] = torques[k] ** 2
            b[k] = y

        x, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

        alpha = x[0]
        t_ambient = x[1] / alpha if abs(alpha) > 1e-10 else 35.0
        beta = x[2]

        return (abs(alpha), abs(beta), t_ambient)
