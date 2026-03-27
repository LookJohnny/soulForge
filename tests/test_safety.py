"""Tests for Safety module (Tasks 3A + 3B)."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from safety.cbf_constraint import CBFConstraint
from safety.thermal_model import ServoThermalModel


class TestCBFConstraint:
    def test_at_upper_limit_positive_rate_violates(self):
        """x = x_max, ẋ > 0 → violation > 0."""
        c = CBFConstraint("test", 0, 100, gamma=20.0)
        v = c.compute_violation(100.0, 1.0)
        assert v > 0

    def test_midpoint_any_rate_safe(self):
        """x = midpoint, reasonable ẋ → violation = 0."""
        c = CBFConstraint("test", 0, 100, gamma=20.0)
        v = c.compute_violation(50.0, 50.0)
        assert v == 0.0

    def test_clamp_rate_satisfies_cbf(self):
        """Clamped rate always satisfies CBF condition."""
        c = CBFConstraint("test", 0, 100, gamma=20.0)
        for x in [0, 10, 50, 90, 100]:
            for x_dot in [-500, -100, 0, 100, 500]:
                clamped = c.clamp_rate(float(x), float(x_dot))
                assert c.compute_violation(float(x), clamped) < 1e-10

    def test_gamma_affects_approach_time(self):
        """Higher gamma allows faster approach → less time to reach boundary."""
        c_slow = CBFConstraint("slow", 0, 100, gamma=0.3)
        c_fast = CBFConstraint("fast", 0, 100, gamma=20.0)

        # At x=80, max approach rate to upper bound
        _, rate_slow = c_slow.compute_safe_rate(80.0)
        _, rate_fast = c_fast.compute_safe_rate(80.0)

        assert rate_fast > rate_slow * 50  # gamma=20 should be ~67x faster than gamma=0.3

    def test_margin(self):
        """Margin shrinks the effective safe range."""
        c = CBFConstraint("test", 0, 100, gamma=20.0, margin=5.0)
        # Effective range is [5, 95]
        assert c.is_safe(50.0)
        assert c.is_safe(5.0)
        assert not c.is_safe(4.9)
        assert not c.is_safe(95.1)

    def test_at_lower_limit_negative_rate_violates(self):
        c = CBFConstraint("test", 0, 100, gamma=20.0)
        v = c.compute_violation(0.0, -1.0)
        assert v > 0

    def test_status_levels(self):
        c = CBFConstraint("test", 0, 100, gamma=20.0)
        assert c.status(50.0) == "normal"
        assert c.status(88.0) == "warning"
        assert c.status(97.0) == "critical"

    def test_boundary_values(self):
        c = CBFConstraint("test", -90, 90, gamma=20.0)
        lo, hi = c.compute_safe_rate(0.0)
        assert hi > 0 and lo < 0  # both directions allowed at center
        _, hi_at_max = c.compute_safe_rate(90.0)
        assert abs(hi_at_max) < 1e-10  # no more room to go up


class TestServoThermalModel:
    def test_constant_torque_monotonic_rise(self):
        """Constant τ=1.0 → temperature rises monotonically."""
        m = ServoThermalModel(alpha=0.025, beta=0.5, t_ambient=35.0)
        prev = m.temperature
        for _ in range(100):
            t = m.step(1.0, 0.02)
            assert t >= prev
            prev = t

    def test_constant_torque_converges_to_steady_state(self):
        """Should converge to T_ss = T_ambient + β·τ²/α."""
        m = ServoThermalModel(alpha=0.025, beta=0.5, t_ambient=35.0)
        t_ss = m.steady_state(1.0)
        # Run for a long time
        for _ in range(50000):
            m.step(1.0, 0.02)
        assert abs(m.temperature - t_ss) < 0.5  # within 0.5°C of steady state

    def test_zero_torque_cools_down(self):
        """τ=0, starting hot → exponential decay to T_ambient."""
        m = ServoThermalModel(t_initial=70.0)
        for _ in range(50000):
            m.step(0.0, 0.02)
        assert abs(m.temperature - m.t_ambient) < 0.5

    def test_predict_matches_step(self):
        """predict_trajectory should match sequential step() calls."""
        m1 = ServoThermalModel(t_initial=40.0)
        m2 = ServoThermalModel(t_initial=40.0)

        torques = [0.5] * 50 + [1.0] * 50 + [0.0] * 50
        predicted = m1.predict_trajectory(torques, 0.02)

        stepped = []
        for tau in torques:
            stepped.append(m2.step(tau, 0.02))

        for p, s in zip(predicted, stepped):
            assert abs(p - s) < 0.01

    def test_time_to_overheat(self):
        """time_to_overheat prediction matches step simulation."""
        m = ServoThermalModel(t_initial=35.0)
        predicted_time = m.time_to_overheat(1.0, 60.0)

        # Simulate
        m.reset(35.0)
        actual_time = 0.0
        while m.temperature < 60.0 and actual_time < 3600:
            m.step(1.0, 0.02)
            actual_time += 0.02

        assert abs(predicted_time - actual_time) < actual_time * 0.05  # within 5%

    def test_fit_from_data(self):
        """fit_from_data recovers known parameters from synthetic data."""
        import numpy as np

        alpha_true, beta_true, t_amb_true = 0.03, 0.4, 36.0
        m = ServoThermalModel(alpha=alpha_true, beta=beta_true, t_ambient=t_amb_true, t_initial=36.0)

        dt = 0.1
        timestamps = [i * dt for i in range(200)]
        torques = [0.8 if i < 100 else 0.0 for i in range(200)]
        temperatures = [36.0]
        for tau in torques[:-1]:
            temperatures.append(m.step(tau, dt))

        alpha_fit, beta_fit, t_amb_fit = ServoThermalModel.fit_from_data(
            timestamps, temperatures, torques
        )

        assert abs(alpha_fit - alpha_true) / alpha_true < 0.05  # < 5% error
        assert abs(beta_fit - beta_true) / beta_true < 0.05
        assert abs(t_amb_fit - t_amb_true) < 1.0  # within 1°C
