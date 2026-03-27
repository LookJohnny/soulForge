"""Tests for Believability RL Environment (Tasks 5B + 5C)."""

import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from believability.gym_env import BelievabilityEnv, HAS_GYM
from believability.scenario_generator import generate as gen_scenario
from believability.train import BelievabilityTrainer
from believability.policy import BelievabilityPolicy


class TestScenarioGenerator:
    def test_generates_events(self):
        events = gen_scenario(60.0, "mixed", seed=42)
        assert len(events) > 10

    def test_all_5_types(self):
        for stype in ["conversation", "touch_play", "idle", "emotional", "anomaly"]:
            events = gen_scenario(30.0, stype, seed=1)
            assert len(events) >= 1, f"{stype} produced no events"

    def test_events_sorted(self):
        events = gen_scenario(60.0, "mixed", seed=42)
        times = [e["t"] for e in events]
        assert times == sorted(times)


class TestBelievabilityEnv:
    def test_reset_returns_valid_obs(self):
        env = BelievabilityEnv(episode_length=100)
        obs, info = env.reset(seed=42)
        assert isinstance(obs, dict)
        assert "emotion_context" in obs
        assert "channel_history" in obs
        assert obs["emotion_context"].shape == (12,)
        assert obs["channel_history"].shape == (10, 20)

    def test_step_returns_correct_format(self):
        env = BelievabilityEnv(episode_length=100)
        env.reset(seed=42)
        action = np.random.uniform(0, 1, size=24).astype(np.float32)
        obs, reward, terminated, truncated, info = env.step(action)

        assert isinstance(obs, dict)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_reward_in_range(self):
        env = BelievabilityEnv(episode_length=100)
        env.reset(seed=42)
        rewards = []
        for _ in range(100):
            action = np.random.uniform(0, 1, size=24).astype(np.float32)
            _, reward, done, _, _ = env.step(action)
            rewards.append(reward)
            if done:
                break
        # Rewards should be finite and in reasonable range
        assert all(not np.isnan(r) and not np.isinf(r) for r in rewards)
        assert all(-10 <= r <= 10 for r in rewards), f"Reward out of range: {min(rewards):.2f} to {max(rewards):.2f}"

    def test_random_policy_1000_steps(self):
        """Random policy runs 1000 steps without error."""
        env = BelievabilityEnv(episode_length=1000)
        obs, _ = env.reset(seed=42)
        for _ in range(1000):
            action = np.random.uniform(0, 1, size=24).astype(np.float32)
            obs, reward, done, trunc, info = env.step(action)
            if done:
                obs, _ = env.reset()

    def test_info_contains_sub_metrics(self):
        env = BelievabilityEnv(episode_length=50)
        env.reset(seed=42)
        action = np.random.uniform(0, 1, size=24).astype(np.float32)
        _, _, _, _, info = env.step(action)
        assert "believability_score" in info
        assert "sub_metrics" in info
        assert isinstance(info["sub_metrics"], dict)

    def test_terminates_at_episode_length(self):
        env = BelievabilityEnv(episode_length=50)
        env.reset(seed=42)
        done = False
        steps = 0
        while not done and steps < 100:
            action = np.random.uniform(0, 1, size=24).astype(np.float32)
            _, _, done, _, _ = env.step(action)
            steps += 1
        assert done
        assert steps == 50


class TestTrainer:
    def test_simple_train_short(self):
        """Simple ES trainer runs without crash."""
        import tempfile
        env = BelievabilityEnv(episode_length=50)
        trainer = BelievabilityTrainer(env=env)
        result = trainer._train_simple(1000, tempfile.mkdtemp())
        assert result["status"] == "trained"
        assert result["best_reward"] > -100  # got some reward

    def test_evaluate(self):
        env = BelievabilityEnv(episode_length=50)
        trainer = BelievabilityTrainer(env=env)
        result = trainer.evaluate(num_episodes=3)
        assert "mean_believability_score" in result
        assert "mean_episode_reward" in result
        assert result["num_episodes"] == 3


class TestPolicy:
    def test_load_nonexistent(self):
        policy = BelievabilityPolicy.load("/nonexistent/path")
        assert not policy.is_loaded

    def test_predict_fallback(self):
        """Unloaded policy falls back to random."""
        policy = BelievabilityPolicy()
        obs = {"emotion_context": np.zeros(12)}
        action = policy.predict(obs)
        assert action.shape == (24,)
        assert all(0 <= a <= 1 for a in action)

    def test_load_simple_weights(self):
        """Save and load numpy weights."""
        weights = np.random.uniform(0, 1, size=24).astype(np.float32)
        path = "/tmp/sf_test_policy.npy"
        np.save(path, weights)

        policy = BelievabilityPolicy.load(path)
        assert policy.is_loaded
        assert policy.backend == "simple"
        action = policy.predict({})
        assert action.shape == (24,)
