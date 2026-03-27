"""Tests for Believability Metrics (Task 5A)."""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from believability.metrics import BelievabilityMetrics


class TestEmotionActionCoherence:
    def test_joy_head_up_scores_higher(self):
        """JOY + head up should score higher than JOY + head down."""
        m = BelievabilityMetrics
        good = m.emotion_action_coherence(1, 0.8, {"head_pitch": 10, "led_brightness": 0.8})
        bad = m.emotion_action_coherence(1, 0.8, {"head_pitch": -10, "led_brightness": -0.5})
        assert good > bad
        assert good - bad >= 0.3

    def test_sadness_head_down_coherent(self):
        sad_down = BelievabilityMetrics.emotion_action_coherence(2, 0.7, {"head_pitch": -8})
        sad_up = BelievabilityMetrics.emotion_action_coherence(2, 0.7, {"head_pitch": 8})
        assert sad_down > sad_up


class TestMotionSmoothness:
    def test_sine_smoother_than_square(self):
        dt = 0.02
        sine = [10 * math.sin(2 * math.pi * 0.5 * i * dt) for i in range(200)]
        square = [10 if (i // 25) % 2 == 0 else -10 for i in range(200)]

        s_sine = BelievabilityMetrics.motion_smoothness(sine, dt)
        s_square = BelievabilityMetrics.motion_smoothness(square, dt)
        assert s_sine > s_square

    def test_constant_is_perfectly_smooth(self):
        constant = [5.0] * 100
        assert BelievabilityMetrics.motion_smoothness(constant, 0.02) >= 0.99


class TestIdleLiveliness:
    def test_breathing_beats_frozen(self):
        dt = 0.02
        # Active channels (breathing)
        breathing = [0.03 * math.sin(2 * math.pi * 0.25 * i * dt) for i in range(500)]
        saccade = [2 * math.sin(2 * math.pi * 2.5 * i * dt) for i in range(500)]

        alive = BelievabilityMetrics.idle_liveliness(
            {"body_pitch": breathing, "eye_yaw": saccade, "head_yaw": breathing},
            dt=dt,
        )

        # Frozen
        frozen = BelievabilityMetrics.idle_liveliness(
            {"body_pitch": [0] * 500, "eye_yaw": [0] * 500, "head_yaw": [0] * 500},
            dt=dt,
        )
        assert alive > frozen

    def test_completely_still_low_score(self):
        score = BelievabilityMetrics.idle_liveliness(
            {"ch1": [0] * 500, "ch2": [0] * 500}, dt=0.02
        )
        assert score < 0.3


class TestJitterPenalty:
    def test_oscillation_penalized(self):
        # High-frequency oscillation
        jittery = [(-1) ** i * 10.0 for i in range(100)]
        score = BelievabilityMetrics.jitter_penalty(jittery, 0.02, threshold=50)
        assert score < 0.3

    def test_smooth_no_penalty(self):
        smooth = [i * 0.5 for i in range(100)]
        score = BelievabilityMetrics.jitter_penalty(smooth, 0.02)
        assert score >= 0.9


class TestReactionLatency:
    def test_optimal_latency_high_score(self):
        # Touch optimal ~120ms
        score = BelievabilityMetrics.reaction_latency(0.0, 0.12, "touch")
        assert score > 0.8

    def test_too_fast_penalized(self):
        score = BelievabilityMetrics.reaction_latency(0.0, 0.01, "touch")
        assert score < 0.5

    def test_too_slow_penalized(self):
        score = BelievabilityMetrics.reaction_latency(0.0, 1.0, "touch")
        assert score < 0.3


class TestCompositeScore:
    def test_good_behavior_above_07(self):
        m = BelievabilityMetrics()
        state = {
            "emotion_action_coherence": 0.9,
            "attention_continuity": 0.8,
            "motion_smoothness": 0.85,
            "rhythm_variation": 0.7,
            "idle_liveliness": 0.8,
            "reaction_latency": 0.9,
            "context_appropriateness": 0.85,
            "jitter_penalty": 0.95,
            "impact_noise": 0.9,
        }
        total, breakdown = m.compute_total_score(state)
        assert total > 0.7

    def test_bad_behavior_below_03(self):
        m = BelievabilityMetrics()
        state = {
            "emotion_action_coherence": 0.1,
            "attention_continuity": 0.2,
            "motion_smoothness": 0.1,
            "rhythm_variation": 0.1,
            "idle_liveliness": 0.1,
            "reaction_latency": 0.1,
            "context_appropriateness": 0.1,
            "jitter_penalty": 0.1,
            "impact_noise": 0.1,
        }
        total, breakdown = m.compute_total_score(state)
        assert total < 0.3

    def test_weights_configurable(self):
        m = BelievabilityMetrics()
        state = {"jitter_penalty": 1.0, "motion_smoothness": 0.0}
        # Default weights: jitter=5, smoothness=3
        t1, _ = m.compute_total_score(state)
        # Custom: flip weights
        t2, _ = m.compute_total_score(state, {"jitter_penalty": 1.0, "motion_smoothness": 10.0})
        assert t2 < t1  # smoothness=0 now weighs more
