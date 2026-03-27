"""Tests for Channel Blender (Task 2A)."""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.blender import ChannelBlender, ChannelMode, TransitionCurve


class TestExclusiveMode:
    def test_higher_layer_overrides(self):
        b = ChannelBlender({"head_yaw": ChannelMode.EXCLUSIVE})
        b.set_layer_output(1, "head_yaw", 10.0, transition_ms=0)
        b.set_layer_output(2, "head_yaw", 30.0, transition_ms=0)
        r = b.tick(20)
        assert abs(r["head_yaw"] - 30.0) < 1e-5

    def test_release_falls_back_to_lower_layer(self):
        b = ChannelBlender({"head_yaw": ChannelMode.EXCLUSIVE})
        b.set_layer_output(1, "head_yaw", 10.0, transition_ms=0)
        b.set_layer_output(2, "head_yaw", 30.0, transition_ms=0)
        b.tick(20)

        # Release layer 2 with short fade
        b.release_channel(2, "head_yaw", fade_ms=100)

        # After fade completes, should be back to layer 1
        for _ in range(10):
            r = b.tick(20)
        assert abs(r["head_yaw"] - 10.0) < 1.0  # smooth transition back

    def test_release_smooth_no_jump(self):
        """Releasing a layer should not cause a sudden jump."""
        b = ChannelBlender({"v": ChannelMode.EXCLUSIVE})
        b.set_layer_output(1, "v", 10.0, transition_ms=0)
        b.set_layer_output(2, "v", 50.0, transition_ms=0)
        b.tick(0)

        b.release_channel(2, "v", fade_ms=200)

        values = []
        for _ in range(20):
            r = b.tick(20)
            values.append(r["v"])

        # No sudden jump > 10 between consecutive frames
        for i in range(1, len(values)):
            assert abs(values[i] - values[i - 1]) < 15


class TestAdditiveMode:
    def test_layers_stack(self):
        b = ChannelBlender({"brightness": ChannelMode.ADDITIVE})
        b.set_layer_output(1, "brightness", 0.3, transition_ms=0)
        b.set_layer_output(2, "brightness", 0.3, transition_ms=0)
        r = b.tick(20)
        assert abs(r["brightness"] - 0.6) < 1e-5

    def test_clamp_to_range(self):
        b = ChannelBlender({"brightness": ChannelMode.ADDITIVE})
        b.set_layer_output(1, "brightness", 0.8, transition_ms=0)
        b.set_layer_output(2, "brightness", 0.5, transition_ms=0)
        r = b.tick(20)
        assert r["brightness"] <= 1.0


class TestBlendedMode:
    def test_equal_weight_blend(self):
        b = ChannelBlender({"color_r": ChannelMode.BLENDED})
        b.set_layer_output(1, "color_r", 255.0, transition_ms=0, weight=0.5)
        b.set_layer_output(2, "color_r", 0.0, transition_ms=0, weight=0.5)
        r = b.tick(20)
        assert abs(r["color_r"] - 127.5) < 1.0

    def test_weighted_blend(self):
        b = ChannelBlender({"v": ChannelMode.BLENDED})
        b.set_layer_output(1, "v", 100.0, transition_ms=0, weight=0.75)
        b.set_layer_output(2, "v", 0.0, transition_ms=0, weight=0.25)
        r = b.tick(20)
        assert abs(r["v"] - 75.0) < 1.0


class TestTransitionCurves:
    def test_spring_has_overshoot(self):
        """Spring curve should overshoot slightly before settling."""
        b = ChannelBlender({"v": ChannelMode.EXCLUSIVE})
        b.set_layer_output(1, "v", 0.0, transition_ms=0)
        b.tick(0)
        b.set_layer_output(1, "v", 100.0, transition_ms=500, curve=TransitionCurve.SPRING)

        values = []
        for _ in range(50):
            r = b.tick(20)
            values.append(r["v"])

        # Should overshoot past 100 at some point
        assert max(values) > 100.0
        # But final value should be near 100
        assert abs(values[-1] - 100.0) < 2.0

    def test_critical_damp_no_overshoot(self):
        """Critical damp should NOT overshoot."""
        b = ChannelBlender({"v": ChannelMode.EXCLUSIVE})
        b.set_layer_output(1, "v", 0.0, transition_ms=0)
        b.tick(0)
        b.set_layer_output(1, "v", 100.0, transition_ms=500, curve=TransitionCurve.CRITICAL_DAMP)

        values = []
        for _ in range(50):
            r = b.tick(20)
            values.append(r["v"])

        assert max(values) <= 100.5  # no significant overshoot


class TestPerformance:
    def test_100_channels_under_half_ms(self):
        channels = {f"ch_{i}": ChannelMode.EXCLUSIVE for i in range(100)}
        b = ChannelBlender(channels)

        for i in range(100):
            b.set_layer_output(1, f"ch_{i}", float(i), transition_ms=0)
            b.set_layer_output(2, f"ch_{i}", float(i * 2), transition_ms=100)

        start = time.perf_counter()
        for _ in range(1000):
            b.tick(20)
        elapsed_ms = (time.perf_counter() - start) * 1000

        per_tick = elapsed_ms / 1000
        assert per_tick < 0.5, f"tick() took {per_tick:.3f}ms, expected < 0.5ms"
