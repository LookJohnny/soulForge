"""Tests for Personality Micro-Drift."""

from ai_core.services.personality_drift import merge_personality_with_drift


class TestMergeWithDrift:
    def test_no_drift_no_offsets(self):
        base = {"extrovert": 50, "humor": 50}
        result = merge_personality_with_drift(base, None, None)
        assert result == {"extrovert": 50, "humor": 50}

    def test_with_offsets_only(self):
        base = {"extrovert": 50, "humor": 50}
        offsets = {"extrovert": 10}
        result = merge_personality_with_drift(base, offsets, None)
        assert result["extrovert"] == 60
        assert result["humor"] == 50

    def test_with_drift_only(self):
        base = {"extrovert": 50, "humor": 50}
        drift = {"humor": 5}
        result = merge_personality_with_drift(base, None, drift)
        assert result["humor"] == 55
        assert result["extrovert"] == 50

    def test_three_layer_merge(self):
        base = {"warmth": 50}
        offsets = {"warmth": 10}
        drift = {"warmth": 3}
        result = merge_personality_with_drift(base, offsets, drift)
        assert result["warmth"] == 63

    def test_clamped_to_100(self):
        base = {"energy": 95}
        offsets = {"energy": 5}
        drift = {"energy": 10}
        result = merge_personality_with_drift(base, offsets, drift)
        assert result["energy"] == 100

    def test_clamped_to_0(self):
        base = {"curiosity": 5}
        offsets = {"curiosity": -3}
        drift = {"curiosity": -10}
        result = merge_personality_with_drift(base, None, drift)
        assert result["curiosity"] == 0

    def test_skips_metadata_keys(self):
        base = {"humor": 50}
        drift = {"humor": 3, "_last_drift_date": "2026-03-18"}
        result = merge_personality_with_drift(base, None, drift)
        assert result["humor"] == 53
        assert "_last_drift_date" not in result

    def test_unknown_drift_keys_ignored(self):
        base = {"humor": 50}
        drift = {"nonexistent": 5}
        result = merge_personality_with_drift(base, None, drift)
        assert result == {"humor": 50}
