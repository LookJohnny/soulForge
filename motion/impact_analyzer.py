"""Impact Analyzer — quantifies motion jerkiness and noise.

Ref: Olaf Tab. I (Sound suppression):
  Impact metric = Σ min(Δv²_z, Δv²_max)
"""

from __future__ import annotations

import math


class ImpactAnalyzer:
    """Analyzes motion sequences for impacts, jitter, and noise."""

    def analyze(self, positions: list[float], dt: float,
                accel_threshold: float = 500.0) -> dict:
        """Analyze a position sequence for smoothness metrics.

        Returns:
            peak_velocity, peak_acceleration, impact_count,
            estimated_noise_reduction_db, smoothness_score, impact_events
        """
        n = len(positions)
        if n < 3:
            return {"peak_velocity": 0, "peak_acceleration": 0, "impact_count": 0,
                    "estimated_noise_reduction_db": 0, "smoothness_score": 1.0, "impact_events": []}

        # Compute velocity and acceleration
        velocities = [(positions[i + 1] - positions[i]) / dt for i in range(n - 1)]
        accelerations = [(velocities[i + 1] - velocities[i]) / dt for i in range(len(velocities) - 1)]

        peak_vel = max(abs(v) for v in velocities) if velocities else 0
        peak_acc = max(abs(a) for a in accelerations) if accelerations else 0

        # Impact events: acceleration exceeds threshold
        impacts = []
        for i, a in enumerate(accelerations):
            if abs(a) > accel_threshold:
                impacts.append({"time": round(i * dt, 4), "severity": round(abs(a) / accel_threshold, 2)})

        # Jerk (derivative of acceleration)
        jerks = [(accelerations[i + 1] - accelerations[i]) / dt for i in range(len(accelerations) - 1)] if len(accelerations) > 1 else [0]
        rms_jerk = math.sqrt(sum(j * j for j in jerks) / max(len(jerks), 1))

        # Smoothness score: inverse of normalized jerk
        max_expected_jerk = accel_threshold / dt  # rough upper bound
        smoothness = max(0.0, 1.0 - rms_jerk / max(max_expected_jerk, 1))

        return {
            "peak_velocity": round(peak_vel, 2),
            "peak_acceleration": round(peak_acc, 2),
            "impact_count": len(impacts),
            "estimated_noise_reduction_db": 0.0,  # computed in compare()
            "smoothness_score": round(smoothness, 4),
            "impact_events": impacts,
        }

    def compare(self, raw: list[float], smoothed: list[float], dt: float) -> dict:
        """Compare raw vs smoothed motion metrics."""
        raw_m = self.analyze(raw, dt)
        smooth_m = self.analyze(smoothed, dt)

        # Noise reduction estimate (dB scale)
        raw_energy = sum((raw[i + 1] - raw[i]) ** 2 for i in range(len(raw) - 1))
        smooth_energy = sum((smoothed[i + 1] - smoothed[i]) ** 2 for i in range(len(smoothed) - 1))

        if raw_energy > 0 and smooth_energy > 0:
            noise_reduction_db = 10 * math.log10(raw_energy / smooth_energy)
        else:
            noise_reduction_db = 0.0

        return {
            "raw": raw_m,
            "smoothed": smooth_m,
            "peak_accel_reduction_pct": round(
                (1 - smooth_m["peak_acceleration"] / max(raw_m["peak_acceleration"], 1)) * 100, 1
            ),
            "noise_reduction_db": round(noise_reduction_db, 1),
        }
