#!/usr/bin/env python3
"""Run all RL tasks: train, compare strategies, evaluate.

Usage:
    cd soulForge
    uv run python scripts/run_rl_tasks.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "checkpoints"), exist_ok=True)


def task1_train():
    """Task 3: Run a short RL training session."""
    from believability.train import BelievabilityTrainer
    from believability.gym_env import BelievabilityEnv

    print("=" * 60)
    print("TASK 1: RL Training (Simple ES, 5000 timesteps)")
    print("=" * 60)
    print()

    env = BelievabilityEnv(episode_length=200)
    trainer = BelievabilityTrainer(env=env)
    result = trainer._train_simple(5000, "checkpoints/")

    print("Training result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print()
    print("Training log:")
    for entry in trainer._train_log:
        print(f"  Episode {entry['episode']:4d}  Best reward: {entry['best_reward']:.2f}")
    print()
    return result


def task2_compare():
    """Task 2: Run comparison demo."""
    print("=" * 60)
    print("TASK 2: Strategy Comparison Demo")
    print("=" * 60)
    print()

    # Import and run the comparison demo
    import demo.comparison_demo as comp
    comp.main()


def task3_evaluate():
    """Evaluate the trained policy."""
    from believability.train import BelievabilityTrainer
    from believability.gym_env import BelievabilityEnv
    from believability.policy import BelievabilityPolicy
    import numpy as np

    print("=" * 60)
    print("TASK 3: RL Policy Evaluation (20 episodes)")
    print("=" * 60)
    print()

    # Load trained policy
    policy = BelievabilityPolicy.load("checkpoints/")
    print(f"Policy backend: {policy.backend}")
    print(f"Policy loaded: {policy.is_loaded}")
    print()

    # Evaluate with loaded policy
    env = BelievabilityEnv(episode_length=300, scenario_type="mixed")

    scores = []
    rewards = []
    sub_metrics_accum = {}

    for ep in range(20):
        obs, _ = env.reset(seed=ep + 1000)
        ep_reward = 0.0
        ep_scores = []

        for _ in range(300):
            action = policy.predict(obs)
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

    print(f"Mean believability score: {np.mean(scores):.4f} +/- {np.std(scores):.4f}")
    print(f"Mean episode reward:     {np.mean(rewards):.2f} +/- {np.std(rewards):.2f}")
    print()
    print("Per-metric breakdown:")
    for k in sorted(sub_metrics_accum.keys()):
        v = sub_metrics_accum[k]
        print(f"  {k:30s}  {np.mean(v):.4f}")
    print()


if __name__ == "__main__":
    task1_train()
    task2_compare()
    task3_evaluate()
    print("All tasks complete.")
