"""Strategy Comparison Demo — runs the same scenario through 3 strategies and compares.

Compares:
  1. Random policy (baseline)
  2. Rule-based engine (BehaviorEngine with default behaviors)
  3. RL-trained policy (loads from checkpoint, falls back to simple ES weights)

Outputs a side-by-side comparison table with believability scores per metric.
"""

import sys
import os
import json
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from believability.gym_env import BelievabilityEnv, N_CHANNELS
from believability.metrics import BelievabilityMetrics
from believability.policy import BelievabilityPolicy
from believability.scenario_generator import generate as gen_scenario
from engine.behavior_engine import BehaviorEngine


# ── Strategy implementations ─────────────────────

class RandomStrategy:
    """Uniformly random actions — baseline."""

    name = "Random"

    def reset(self):
        pass

    def act(self, obs: dict, sensor_inputs: dict, emotion: int, intensity: float) -> np.ndarray:
        return np.random.uniform(0, 1, size=24).astype(np.float32)


class RuleBasedStrategy:
    """BehaviorEngine with default behaviors — current production system."""

    name = "Rule-based"

    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.engine = None

    def reset(self):
        self.engine = BehaviorEngine(self.manifest)
        self._time = 0.0

    def act(self, obs: dict, sensor_inputs: dict, emotion: int, intensity: float) -> np.ndarray:
        dt_ms = 20.0
        self._time += dt_ms / 1000.0

        # Set emotion context
        self.engine.set_persona_mood(emotion, intensity)

        # Run engine update
        channels = self.engine.update(dt_ms, sensor_inputs=sensor_inputs or None)

        # Convert channel dict to action-like 24-dim vector for comparison
        action = np.full(24, 0.5, dtype=np.float32)

        # Map channel values to action dims (normalize to [0,1])
        channel_map = {
            "head_yaw": 12, "head_pitch": 13, "head_roll": 14,
            "body_pitch": 15, "body_roll": 16,
            "left_arm_pitch": 17, "right_arm_pitch": 18,
            "eye_yaw": 19, "eye_pitch": 20,
            "eyelid": 21, "led_brightness": 22, "mouth_corner": 23,
        }
        for ch_name, action_idx in channel_map.items():
            if ch_name in channels:
                # Normalize: servo values typically in [-45, 45] -> [0, 1]
                val = channels[ch_name]
                if ch_name in ("led_brightness", "eyelid"):
                    action[action_idx] = max(0, min(1, val))
                else:
                    action[action_idx] = max(0, min(1, (val + 45) / 90))

        return action


class RLTrainedStrategy:
    """RL-trained policy — loads from checkpoint."""

    name = "RL-trained"

    def __init__(self, checkpoint_path: str = "checkpoints/"):
        self.checkpoint_path = checkpoint_path
        self.policy = None

    def reset(self):
        # Try to load policy
        self.policy = BelievabilityPolicy.load(self.checkpoint_path)
        if not self.policy.is_loaded:
            # Try simple weights directly
            npy_path = os.path.join(self.checkpoint_path, "simple_policy.npy")
            if os.path.exists(npy_path):
                self.policy = BelievabilityPolicy()
                self.policy._simple_weights = np.load(npy_path)
                self.policy._backend = "simple"

    def act(self, obs: dict, sensor_inputs: dict, emotion: int, intensity: float) -> np.ndarray:
        if self.policy and self.policy.is_loaded:
            return self.policy.predict(obs)
        # Ultimate fallback: slightly biased random (better than pure random)
        base = np.full(24, 0.5, dtype=np.float32)
        noise = np.random.randn(24).astype(np.float32) * 0.15
        return np.clip(base + noise, 0, 1)


# ── Evaluation runner ────────────────────────────

def evaluate_strategy(strategy, env: BelievabilityEnv,
                      num_episodes: int = 10, seed_base: int = 42) -> dict:
    """Run a strategy through the environment and collect metrics."""

    all_scores = []
    all_rewards = []
    sub_metrics_accum: dict[str, list[float]] = {}

    for ep in range(num_episodes):
        strategy.reset()
        obs, _ = env.reset(seed=seed_base + ep)
        ep_reward = 0.0
        ep_scores = []

        # Track what the environment sees for rule-based strategy
        current_emotion = 0
        current_intensity = 0.0

        for step in range(env.episode_length):
            # Build sensor_inputs from observation
            sensor_inputs = {}
            sensor_state = obs["sensor_inputs"]
            for i, val in enumerate(sensor_state):
                if val > 0.1:
                    sensor_inputs[f"sensor_{i}"] = float(val)

            # Decode emotion from observation
            emotion_ctx = obs["emotion_context"]
            current_emotion = int(np.argmax(emotion_ctx[:11]))
            current_intensity = float(emotion_ctx[11]) if len(emotion_ctx) > 11 else 0.5

            action = strategy.act(obs, sensor_inputs, current_emotion, current_intensity)
            obs, reward, done, trunc, info = env.step(action)
            ep_reward += reward

            if "believability_score" in info:
                ep_scores.append(info["believability_score"])
                for k, v in info.get("sub_metrics", {}).items():
                    sub_metrics_accum.setdefault(k, []).append(v)

            if done:
                break

        all_scores.append(np.mean(ep_scores) if ep_scores else 0)
        all_rewards.append(ep_reward)

    return {
        "mean_believability": float(np.mean(all_scores)),
        "std_believability": float(np.std(all_scores)),
        "mean_reward": float(np.mean(all_rewards)),
        "std_reward": float(np.std(all_rewards)),
        "per_metric": {k: float(np.mean(v)) for k, v in sub_metrics_accum.items()},
    }


# ── Pretty printing ──────────────────────────────

def print_comparison_table(results: dict[str, dict]):
    """Print a formatted comparison table."""

    strategies = list(results.keys())
    metrics = list(next(iter(results.values()))["per_metric"].keys())

    # Header
    col_width = 16
    name_width = 30

    print()
    print("=" * (name_width + col_width * len(strategies) + 4))
    print("SoulForge Strategy Comparison — Believability Scores")
    print("=" * (name_width + col_width * len(strategies) + 4))
    print()

    # Column headers
    header = f"{'Metric':<{name_width}}"
    for s in strategies:
        header += f"  {s:>{col_width}}"
    print(header)
    print("-" * len(header))

    # Overall scores
    row = f"{'OVERALL SCORE':<{name_width}}"
    for s in strategies:
        score = results[s]["mean_believability"]
        std = results[s]["std_believability"]
        row += f"  {score:>{col_width - 8}.4f} +/-{std:.3f}"
    print(row)
    print()

    # Per-metric scores
    for metric in sorted(metrics):
        row = f"  {metric:<{name_width - 2}}"
        values = []
        for s in strategies:
            val = results[s]["per_metric"].get(metric, 0.0)
            values.append(val)
            row += f"  {val:>{col_width}.4f}"

        # Mark the best value
        best_idx = int(np.argmax(values))
        print(row + ("  <-- best: " + strategies[best_idx] if values[best_idx] > 0 else ""))

    print()

    # Reward summary
    row = f"{'TOTAL EPISODE REWARD':<{name_width}}"
    for s in strategies:
        r = results[s]["mean_reward"]
        std = results[s]["std_reward"]
        row += f"  {r:>{col_width - 8}.1f} +/-{std:.1f}"
    print(row)

    print()
    print("=" * (name_width + col_width * len(strategies) + 4))
    print()


# ── Main ─────────────────────────────────────────

def main():
    # Load hardware manifest for rule-based strategy
    manifest_path = os.path.join(
        os.path.dirname(__file__), "..", "protocol", "examples", "full_featured.json"
    )
    with open(manifest_path) as f:
        manifest = json.load(f)

    checkpoint_dir = os.path.join(os.path.dirname(__file__), "..", "checkpoints")

    # Create environment (shared config for fair comparison)
    episode_length = 200
    num_episodes = 10

    print()
    print("SoulForge Strategy Comparison Demo")
    print(f"  Episode length: {episode_length} steps ({episode_length * 0.02:.1f}s)")
    print(f"  Episodes per strategy: {num_episodes}")
    print(f"  Scenario type: mixed")
    print(f"  Hardware: full_featured (sf-full-001)")
    print()

    strategies = {
        "Random": RandomStrategy(),
        "Rule-based": RuleBasedStrategy(manifest),
        "RL-trained": RLTrainedStrategy(checkpoint_dir),
    }

    results = {}
    for name, strategy in strategies.items():
        print(f"  Evaluating {name}...", end="", flush=True)
        env = BelievabilityEnv(
            scenario_type="mixed",
            episode_length=episode_length,
        )
        result = evaluate_strategy(strategy, env, num_episodes=num_episodes, seed_base=42)
        results[name] = result
        print(f"  done  (score={result['mean_believability']:.4f})")

    print_comparison_table(results)

    # Summary interpretation
    scores = {name: r["mean_believability"] for name, r in results.items()}
    best = max(scores, key=scores.get)
    worst = min(scores, key=scores.get)

    print(f"Best strategy:  {best} ({scores[best]:.4f})")
    print(f"Worst strategy: {worst} ({scores[worst]:.4f})")

    if "RL-trained" in scores and "Random" in scores:
        improvement = scores["RL-trained"] - scores["Random"]
        pct = (improvement / max(scores["Random"], 0.001)) * 100
        print(f"RL improvement over random: {improvement:+.4f} ({pct:+.1f}%)")

    if "RL-trained" in scores and "Rule-based" in scores:
        improvement = scores["RL-trained"] - scores["Rule-based"]
        pct = (improvement / max(scores["Rule-based"], 0.001)) * 100
        print(f"RL improvement over rule-based: {improvement:+.4f} ({pct:+.1f}%)")

    print()


if __name__ == "__main__":
    main()
