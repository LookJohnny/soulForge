"""Tests for the life loop state machine and vocabulary."""

import random

from gateway.life import LifeState, compute_state
from gateway.life import vocab
from gateway.life.loop import GAP_RANGES, is_night, next_gap

CFG = {
    "bored_after": 90,
    "sleepy_after": 600,
    "asleep_after": 1200,
    "night_start": 22,
    "night_end": 7,
}


class TestComputeState:
    def test_awake_when_recently_active(self):
        assert compute_state(0, 12, **CFG) is LifeState.AWAKE
        assert compute_state(89, 12, **CFG) is LifeState.AWAKE

    def test_bored_after_threshold(self):
        assert compute_state(90, 12, **CFG) is LifeState.BORED
        assert compute_state(599, 12, **CFG) is LifeState.BORED

    def test_sleepy_then_asleep_daytime(self):
        assert compute_state(600, 12, **CFG) is LifeState.SLEEPY
        assert compute_state(1199, 12, **CFG) is LifeState.SLEEPY
        assert compute_state(1200, 12, **CFG) is LifeState.ASLEEP

    def test_night_halves_drowsy_thresholds(self):
        # At 23:00 sleepy threshold is 300s, asleep is 600s
        assert compute_state(300, 23, **CFG) is LifeState.SLEEPY
        assert compute_state(600, 23, **CFG) is LifeState.ASLEEP
        # Same idle time during the day is merely bored/sleepy
        assert compute_state(300, 12, **CFG) is LifeState.BORED
        assert compute_state(600, 12, **CFG) is LifeState.SLEEPY

    def test_early_morning_counts_as_night(self):
        assert compute_state(300, 3, **CFG) is LifeState.SLEEPY

    def test_bored_threshold_unchanged_at_night(self):
        assert compute_state(89, 23, **CFG) is LifeState.AWAKE
        assert compute_state(90, 23, **CFG) is LifeState.BORED


class TestIsNight:
    def test_wraps_midnight(self):
        assert is_night(22, 22, 7)
        assert is_night(23, 22, 7)
        assert is_night(0, 22, 7)
        assert is_night(6, 22, 7)
        assert not is_night(7, 22, 7)
        assert not is_night(12, 22, 7)
        assert not is_night(21, 22, 7)


class TestNextGap:
    def test_within_configured_range(self):
        rng = random.Random(42)
        for state, (lo, hi) in GAP_RANGES.items():
            for _ in range(20):
                gap = next_gap(state, rng)
                assert lo <= gap <= hi

    def test_unknown_state_falls_back_to_bored_range(self):
        gap = next_gap(LifeState.AWAKE, random.Random(1))
        lo, hi = GAP_RANGES[LifeState.BORED]
        assert lo <= gap <= hi


class TestVocab:
    def test_all_states_have_utterances(self):
        for state in ("bored", "sleepy", "asleep"):
            assert vocab.AMBIENT[state], f"no utterances for {state}"

    def test_utterances_are_pure_vocal_text(self):
        # No stage directions — these go straight to TTS
        for pool in (*vocab.AMBIENT.values(), vocab.THINKING_FILLERS):
            for text in pool:
                assert text.strip()
                assert "（" not in text and "(" not in text, f"stage direction in: {text}"

    def test_pick_ambient_deterministic_with_seeded_rng(self):
        rng = random.Random(7)
        choice = vocab.pick_ambient("bored", rng)
        assert choice in vocab.BORED

    def test_pick_ambient_unknown_state_uses_bored(self):
        assert vocab.pick_ambient("nonsense", random.Random(1)) in vocab.BORED


class TestEnergyBias:
    def test_low_energy_gets_sleepy_sooner(self):
        # thresholds: sleepy 600 / asleep 1200 at noon
        assert compute_state(400, 12, **CFG, energy=100) is LifeState.BORED
        assert compute_state(400, 12, **CFG, energy=0) is LifeState.SLEEPY  # halved → 300
        assert compute_state(700, 12, **CFG, energy=0) is LifeState.ASLEEP  # halved → 600
        assert compute_state(500, 12, **CFG, energy=50) is LifeState.SLEEPY  # ×0.75 → 450

    def test_energy_stacks_with_night(self):
        assert compute_state(200, 23, **CFG, energy=0) is LifeState.SLEEPY  # 600/2×0.5 = 150
        assert compute_state(200, 23, **CFG, energy=100) is LifeState.BORED  # 300 → not yet sleepy
