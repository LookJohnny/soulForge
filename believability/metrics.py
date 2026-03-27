"""Believability Metrics — quantified believability scoring.

Ref: Olaf paper Tab. I (reward terms), formula (4), Tab. III (weights).

Decomposes believability into 6 measurable dimensions:
  1. Coherence     — emotion-action alignment, speech-expression sync
  2. Naturalness   — motion smoothness, rhythm variation, idle liveliness
  3. Responsiveness — reaction latency, context appropriateness
  4. Personality   — character consistency (reserved for future)
  5. Physical      — jitter penalty, impact noise
  6. Safety        — constraint violation penalty

Total score = weighted sum of all sub-metrics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ── Emotion-action expected directions ────────────
# Maps EmotionType int → expected channel directions
# Positive = channel should increase, negative = decrease
_EMOTION_EXPECTED: dict[int, dict[str, float]] = {
    1:  {"head_pitch": 1, "body_pitch": 0.3, "led_brightness": 1},        # JOY
    2:  {"head_pitch": -1, "body_pitch": -0.3, "led_brightness": -0.5},   # SADNESS
    3:  {"head_pitch": 1, "eyelid": 1, "body_pitch": -0.5},              # SURPRISE
    4:  {"head_pitch": -0.5, "body_pitch": 0.3, "led_brightness": 0.3},  # ANGER
    5:  {"head_pitch": -0.3, "body_pitch": -0.5},                         # FEAR
    7:  {"head_pitch": 0.5, "eye_yaw": 0.3},                             # CURIOSITY
    8:  {"head_pitch": 0.3, "led_brightness": 0.3},                       # AFFECTION
    9:  {"head_pitch": -0.5, "eyelid": -0.5, "led_brightness": -0.5},    # SLEEPY
    10: {"head_pitch": 0.8, "body_pitch": 0.5, "led_brightness": 1},     # EXCITED
}

# ── Reaction latency expected ranges (ms) ─────────
_EXPECTED_LATENCY: dict[str, tuple[float, float, float]] = {
    # (min_ok, optimal, max_ok)
    "touch": (50, 120, 300),
    "speech": (200, 350, 600),
    "visual": (150, 220, 400),
}

# ── Context appropriateness rules ─────────────────
_APPROPRIATE_RESPONSES: dict[tuple[str, int], list[str]] = {
    # (trigger, emotion_context) → acceptable behaviors
    ("touch_head", 0): ["listening_nod", "happy_wiggle"],
    ("touch_head", 1): ["happy_wiggle"],
    ("touch_belly", 0): ["happy_wiggle"],
    ("proximity_close", 0): ["surprised_jump"],
    ("proximity_close", 5): ["surprised_jump"],
    ("loud_noise", 0): ["surprised_jump"],
}


class BelievabilityMetrics:
    """Quantified believability scoring framework.

    Total = Σ w_i · r_i  (weighted sub-metrics, ref Olaf formula 4)
    """

    # ── Dimension 1: Coherence ────────────────────

    @staticmethod
    def emotion_action_coherence(emotion_type: int, emotion_intensity: float,
                                  active_channels: dict[str, float]) -> float:
        """Emotion-action consistency score.

        Computes cosine similarity between actual channel outputs
        and expected directions for the given emotion.

        Returns: 0.0-1.0
        """
        expected = _EMOTION_EXPECTED.get(emotion_type, {})
        if not expected or not active_channels:
            return 0.5  # neutral

        dot = 0.0
        mag_exp = 0.0
        mag_act = 0.0

        for ch, exp_dir in expected.items():
            act_val = active_channels.get(ch, 0.0)
            weighted_exp = exp_dir * emotion_intensity
            dot += weighted_exp * act_val
            mag_exp += weighted_exp ** 2
            mag_act += act_val ** 2

        if mag_exp < 1e-6 or mag_act < 1e-6:
            return 0.5

        cosine = dot / (math.sqrt(mag_exp) * math.sqrt(mag_act))
        return max(0.0, min(1.0, (cosine + 1.0) / 2.0))  # map [-1,1] → [0,1]

    @staticmethod
    def attention_continuity(gaze_history: list[tuple[float, float]],
                              window_seconds: float = 5.0,
                              sample_rate: float = 50.0) -> float:
        """Attention continuity: penalizes erratic gaze jumps.

        Natural: smooth transitions with occasional saccades.
        Unnatural: random jumps >30° per frame, or frozen >10s.

        Returns: 0.0-1.0
        """
        if len(gaze_history) < 3:
            return 0.5

        n = min(len(gaze_history), int(window_seconds * sample_rate))
        recent = gaze_history[-n:]

        # Count large jumps (>30° per frame)
        large_jumps = 0
        for i in range(1, len(recent)):
            dy = abs(recent[i][0] - recent[i - 1][0])
            dp = abs(recent[i][1] - recent[i - 1][1])
            if dy > 30 or dp > 30:
                large_jumps += 1

        jump_rate = large_jumps / max(len(recent) - 1, 1)

        # Check for frozen gaze (all values identical)
        total_movement = sum(
            abs(recent[i][0] - recent[i - 1][0]) + abs(recent[i][1] - recent[i - 1][1])
            for i in range(1, len(recent))
        )
        is_frozen = total_movement < 0.1 and len(recent) > sample_rate * 3  # >3s frozen

        score = 1.0 - jump_rate * 5.0  # each jump costs 0.2
        if is_frozen:
            score -= 0.3

        return max(0.0, min(1.0, score))

    # ── Dimension 2: Naturalness ──────────────────

    @staticmethod
    def motion_smoothness(channel_history: list[float], dt: float) -> float:
        """Motion smoothness via jerk (third derivative) minimization.

        Ref: Olaf Tab. I regularization: -‖q̈‖², -‖a - a_{t-1}‖²

        Returns: 0.0-1.0
        """
        if len(channel_history) < 4:
            return 1.0

        # Compute velocities
        vels = [(channel_history[i + 1] - channel_history[i]) / dt for i in range(len(channel_history) - 1)]
        # Compute accelerations
        accels = [(vels[i + 1] - vels[i]) / dt for i in range(len(vels) - 1)]
        # Compute jerk
        jerks = [(accels[i + 1] - accels[i]) / dt for i in range(len(accels) - 1)]

        if not jerks:
            return 1.0

        rms_jerk = math.sqrt(sum(j * j for j in jerks) / len(jerks))

        # Normalize: jerk of 10000 °/s³ → score 0, jerk of 0 → score 1
        score = max(0.0, 1.0 - rms_jerk / 10000.0)
        return score

    @staticmethod
    def rhythm_variation(channel_history: list[float], window_seconds: float = 10.0,
                          dt: float = 0.02) -> float:
        """Rhythm variation: penalizes perfectly mechanical repetition.

        Natural motion has micro-variations; perfect sine waves are unnatural.
        Uses autocorrelation decay as the metric.

        Returns: 0.0-1.0
        """
        n = min(len(channel_history), int(window_seconds / dt))
        if n < 20:
            return 0.5

        data = channel_history[-n:]
        mean = sum(data) / len(data)
        centered = [x - mean for x in data]
        variance = sum(x * x for x in centered)

        if variance < 1e-10:
            return 0.3  # constant = mildly unnatural

        # Autocorrelation at lag = 2 seconds
        lag = min(int(2.0 / dt), n // 2)
        auto = sum(centered[i] * centered[i + lag] for i in range(n - lag)) / variance

        # High autocorrelation at lag>2s = too periodic = bad
        # Score: auto=1 → 0.0, auto=0 → 1.0
        return max(0.0, min(1.0, 1.0 - abs(auto)))

    @staticmethod
    def idle_liveliness(all_channels: dict[str, list[float]],
                         window_seconds: float = 10.0, dt: float = 0.02) -> float:
        """Idle liveliness: does the character look alive when idle?

        Rewards breathing, eye movement, micro-expressions.
        Penalizes total stillness >3s or perfectly synchronized channels.

        Returns: 0.0-1.0
        """
        if not all_channels:
            return 0.0

        n_samples = int(window_seconds / dt)
        active_count = 0
        total_channels = len(all_channels)

        for ch_id, history in all_channels.items():
            recent = history[-n_samples:] if len(history) > n_samples else history
            if len(recent) < 10:
                continue

            # Check if channel has any movement
            total_var = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))
            if total_var > 0.01:
                active_count += 1

        if total_channels == 0:
            return 0.0

        activity_ratio = active_count / total_channels

        # At least 30% of channels should be moving
        if activity_ratio < 0.1:
            return 0.1  # almost dead
        elif activity_ratio < 0.3:
            return 0.3 + activity_ratio
        else:
            return min(1.0, 0.5 + activity_ratio * 0.5)

    # ── Dimension 3: Responsiveness ───────────────

    @staticmethod
    def reaction_latency(stimulus_time: float, response_start_time: float,
                          stimulus_type: str = "touch") -> float:
        """Reaction latency score using Gaussian reward.

        Too fast = unnatural, too slow = unresponsive.

        Returns: 0.0-1.0
        """
        latency_ms = (response_start_time - stimulus_time) * 1000
        params = _EXPECTED_LATENCY.get(stimulus_type, (100, 200, 400))
        min_ok, optimal, max_ok = params

        if latency_ms < 0:
            return 0.0
        if latency_ms < min_ok * 0.5:
            return 0.3  # too fast
        if latency_ms > max_ok * 2:
            return 0.1  # too slow

        # Gaussian around optimal
        sigma = (max_ok - min_ok) / 3
        score = math.exp(-0.5 * ((latency_ms - optimal) / max(sigma, 1)) ** 2)
        return max(0.0, min(1.0, score))

    @staticmethod
    def context_appropriateness(trigger_event: str, response_behavior: str,
                                 emotional_context: int = 0) -> float:
        """Context appropriateness: is the response sensible for the trigger?

        Returns: 0.0-1.0
        """
        key = (trigger_event, emotional_context)
        acceptable = _APPROPRIATE_RESPONSES.get(key)

        if acceptable is None:
            # Try without emotion context
            for k, v in _APPROPRIATE_RESPONSES.items():
                if k[0] == trigger_event:
                    acceptable = v
                    break

        if acceptable is None:
            return 0.5  # unknown trigger, neutral score

        if response_behavior in acceptable:
            return 1.0
        return 0.2  # wrong response

    # ── Dimension 5: Physical Plausibility ────────

    @staticmethod
    def jitter_penalty(channel_history: list[float], dt: float,
                        threshold: float = 50.0) -> float:
        """Jitter detection: penalizes high-frequency oscillation.

        Detects ≥3 consecutive direction reversals above threshold.

        Returns: 0.0 (severe jitter) - 1.0 (no jitter)
        """
        if len(channel_history) < 4:
            return 1.0

        vels = [(channel_history[i + 1] - channel_history[i]) / dt for i in range(len(channel_history) - 1)]

        reversal_count = 0
        consecutive = 0

        for i in range(1, len(vels)):
            if abs(vels[i]) > threshold and abs(vels[i - 1]) > threshold:
                if vels[i] * vels[i - 1] < 0:  # direction change
                    consecutive += 1
                    if consecutive >= 2:
                        reversal_count += 1
                else:
                    consecutive = 0
            else:
                consecutive = 0

        jitter_rate = reversal_count / max(len(vels), 1)
        return max(0.0, 1.0 - jitter_rate * 20)

    @staticmethod
    def impact_noise_estimate(velocity_history: list[float], dt: float) -> float:
        """Impact noise estimate.

        Ref: Olaf Tab. I: noise ∝ Σ min(Δv², Δv²_max)

        Returns: 0.0 (noisy) - 1.0 (silent)
        """
        if len(velocity_history) < 2:
            return 1.0

        dv_max_sq = 100.0 ** 2  # threshold
        total_impact = sum(
            min((velocity_history[i] - velocity_history[i - 1]) ** 2, dv_max_sq)
            for i in range(1, len(velocity_history))
        )

        normalized = total_impact / (len(velocity_history) * dv_max_sq)
        return max(0.0, 1.0 - normalized * 5)

    # ── Composite score ───────────────────────────

    DEFAULT_WEIGHTS: dict[str, float] = {
        "emotion_action_coherence": 4.0,
        "attention_continuity": 2.0,
        "motion_smoothness": 3.0,
        "rhythm_variation": 1.5,
        "idle_liveliness": 2.5,
        "reaction_latency": 2.0,
        "context_appropriateness": 3.0,
        "jitter_penalty": 5.0,
        "impact_noise": 2.5,
    }

    def compute_total_score(self, state: dict,
                             weights: dict[str, float] | None = None) -> tuple[float, dict[str, float]]:
        """Compute weighted total believability score.

        Args:
            state: dict with pre-computed sub-metric values
                   (keys match DEFAULT_WEIGHTS)
            weights: optional weight overrides

        Returns: (total_score_0_to_1, {metric: individual_score})
        """
        w = weights or self.DEFAULT_WEIGHTS
        scores: dict[str, float] = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for metric, weight in w.items():
            val = state.get(metric, 0.5)  # default neutral
            scores[metric] = round(val, 4)
            weighted_sum += val * weight
            total_weight += weight

        total = weighted_sum / max(total_weight, 1e-6)
        return (round(max(0.0, min(1.0, total)), 4), scores)
