"""Believability RL Trainer.

Ref: Olaf Sec. VII-B — PPO with 3-layer MLP, privileged critic.

Uses stable-baselines3 for PPO implementation.
Falls back to a simple random-search trainer if SB3 is not installed.
"""

from __future__ import annotations

import os
import json
import time
import numpy as np

from believability.gym_env import BelievabilityEnv, HAS_GYM

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv
    HAS_SB3 = True
except ImportError:
    HAS_SB3 = False


class BelievabilityTrainer:
    """RL training entry point.

    Ref: Olaf Sec. VII-B training config:
      Algorithm: PPO
      Network: 3-layer MLP, 256 units (Olaf uses 512)
      Parallel envs: 64 (Olaf uses 8192, we run on CPU)
      Learning rate: 3e-4
      Gamma: 0.99
      GAE lambda: 0.95
      Clip range: 0.2
    """

    def __init__(self, env: BelievabilityEnv | None = None, config: dict | None = None):
        cfg = config or {}
        self.config = {
            "learning_rate": cfg.get("learning_rate", 3e-4),
            "gamma": cfg.get("gamma", 0.99),
            "gae_lambda": cfg.get("gae_lambda", 0.95),
            "clip_range": cfg.get("clip_range", 0.2),
            "n_steps": cfg.get("n_steps", 512),
            "batch_size": cfg.get("batch_size", 64),
            "n_epochs": cfg.get("n_epochs", 10),
            "net_arch": cfg.get("net_arch", [256, 256, 256]),
            "n_envs": cfg.get("n_envs", 4),
        }

        self.env = env
        self.model = None
        self._train_log: list[dict] = []

    def train(self, total_timesteps: int = 100_000, save_path: str = "./checkpoints/"):
        """Train the policy."""
        os.makedirs(save_path, exist_ok=True)

        if HAS_SB3 and HAS_GYM:
            return self._train_sb3(total_timesteps, save_path)
        else:
            return self._train_simple(total_timesteps, save_path)

    def _train_sb3(self, total_timesteps: int, save_path: str):
        """Train with stable-baselines3 PPO."""
        def make_env():
            return BelievabilityEnv(scenario_type="mixed", episode_length=500)

        vec_env = DummyVecEnv([make_env for _ in range(self.config["n_envs"])])

        self.model = PPO(
            "MultiInputPolicy",
            vec_env,
            learning_rate=self.config["learning_rate"],
            gamma=self.config["gamma"],
            gae_lambda=self.config["gae_lambda"],
            clip_range=self.config["clip_range"],
            n_steps=self.config["n_steps"],
            batch_size=self.config["batch_size"],
            n_epochs=self.config["n_epochs"],
            policy_kwargs={"net_arch": self.config["net_arch"]},
            verbose=1,
        )

        self.model.learn(total_timesteps=total_timesteps)
        self.model.save(os.path.join(save_path, "believability_policy"))

        return {"status": "trained", "timesteps": total_timesteps, "backend": "sb3"}

    def _train_simple(self, total_timesteps: int, save_path: str):
        """Simple random-search fallback (no torch/sb3 dependency)."""
        env = self.env or BelievabilityEnv(scenario_type="mixed", episode_length=200)

        best_reward = -float("inf")
        best_weights = None
        action_dim = 24

        # Simple evolution strategy
        mean = np.zeros(action_dim, dtype=np.float32)
        std = np.ones(action_dim, dtype=np.float32) * 0.3

        episodes = total_timesteps // 200
        for ep in range(episodes):
            # Sample action bias
            weights = mean + std * np.random.randn(action_dim).astype(np.float32)
            weights = np.clip(weights, 0, 1)

            obs, _ = env.reset(seed=ep)
            total_reward = 0.0
            for _ in range(200):
                action = np.clip(weights + np.random.randn(action_dim).astype(np.float32) * 0.1, 0, 1)
                obs, reward, done, trunc, info = env.step(action)
                total_reward += reward
                if done:
                    break

            if total_reward > best_reward:
                best_reward = total_reward
                best_weights = weights.copy()
                mean = 0.9 * mean + 0.1 * weights  # move mean toward best

            if ep % 50 == 0:
                self._train_log.append({"episode": ep, "best_reward": float(best_reward)})

        # Save best weights
        if best_weights is not None:
            np.save(os.path.join(save_path, "simple_policy.npy"), best_weights)

        return {
            "status": "trained",
            "episodes": episodes,
            "best_reward": float(best_reward),
            "backend": "simple_es",
        }

    def evaluate(self, num_episodes: int = 20) -> dict:
        """Evaluate current policy."""
        env = self.env or BelievabilityEnv(scenario_type="mixed", episode_length=300)

        scores = []
        rewards = []
        sub_metrics_accum: dict[str, list[float]] = {}

        for ep in range(num_episodes):
            obs, _ = env.reset(seed=ep + 1000)
            ep_reward = 0.0
            ep_scores = []

            for _ in range(300):
                if self.model and HAS_SB3:
                    action, _ = self.model.predict(obs, deterministic=True)
                else:
                    action = np.random.uniform(0, 1, size=24).astype(np.float32)

                obs, reward, done, trunc, info = env.step(action)
                ep_reward += reward

                if "believability_score" in info:
                    ep_scores.append(info["believability_score"])
                    for k, v in info.get("sub_metrics", {}).items():
                        sub_metrics_accum.setdefault(k, []).append(v)

                if done:
                    break

            scores.append(np.mean(ep_scores) if ep_scores else 0)
            rewards.append(ep_reward)

        return {
            "mean_believability_score": float(np.mean(scores)),
            "mean_episode_reward": float(np.mean(rewards)),
            "std_reward": float(np.std(rewards)),
            "per_metric_scores": {
                k: float(np.mean(v)) for k, v in sub_metrics_accum.items()
            },
            "num_episodes": num_episodes,
        }
