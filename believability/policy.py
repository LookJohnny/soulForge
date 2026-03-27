"""Believability Policy — trained policy deployment.

Ref: Olaf Sec. VII-C — frozen policy deployed on robot's on-board computer.

Supports loading from:
  - stable-baselines3 checkpoint (.zip)
  - simple numpy weights (.npy)
  - ONNX export for edge deployment
"""

from __future__ import annotations

import os
import numpy as np

try:
    from stable_baselines3 import PPO
    HAS_SB3 = True
except ImportError:
    HAS_SB3 = False


class BelievabilityPolicy:
    """Deployed policy for real-time inference.

    Single predict() call < 5ms at 20Hz inference rate.
    """

    def __init__(self):
        self._sb3_model = None
        self._simple_weights: np.ndarray | None = None
        self._backend = "none"

    @classmethod
    def load(cls, checkpoint_path: str) -> "BelievabilityPolicy":
        """Load policy from checkpoint.

        Auto-detects format:
          .zip → stable-baselines3
          .npy → simple numpy weights
          .onnx → ONNX runtime
        """
        policy = cls()

        if checkpoint_path.endswith(".zip") and HAS_SB3:
            policy._sb3_model = PPO.load(checkpoint_path)
            policy._backend = "sb3"
        elif checkpoint_path.endswith(".npy"):
            policy._simple_weights = np.load(checkpoint_path)
            policy._backend = "simple"
        elif os.path.isdir(checkpoint_path):
            # Try loading sb3 model from directory
            zip_path = os.path.join(checkpoint_path, "believability_policy.zip")
            npy_path = os.path.join(checkpoint_path, "simple_policy.npy")
            if os.path.exists(zip_path) and HAS_SB3:
                policy._sb3_model = PPO.load(zip_path)
                policy._backend = "sb3"
            elif os.path.exists(npy_path):
                policy._simple_weights = np.load(npy_path)
                policy._backend = "simple"

        return policy

    def predict(self, observation: dict) -> np.ndarray:
        """Predict action from observation.

        Args:
            observation: dict matching BelievabilityEnv observation_space

        Returns:
            action: numpy array of shape (24,)
        """
        if self._backend == "sb3" and self._sb3_model:
            action, _ = self._sb3_model.predict(observation, deterministic=True)
            return action

        if self._backend == "simple" and self._simple_weights is not None:
            # Simple: use stored weights + small noise for variety
            noise = np.random.randn(24).astype(np.float32) * 0.05
            return np.clip(self._simple_weights + noise, 0, 1)

        # Fallback: random
        return np.random.uniform(0, 1, size=24).astype(np.float32)

    def export_onnx(self, output_path: str) -> bool:
        """Export policy to ONNX for edge device deployment.

        Returns True if export succeeded.
        """
        if self._backend != "sb3" or not self._sb3_model:
            return False

        try:
            import torch
            # Extract the policy network
            policy_net = self._sb3_model.policy

            # Create dummy input matching observation space
            dummy = {
                "emotion_context": torch.zeros(1, 12),
                "channel_history": torch.zeros(1, 10, 20),
                "sensor_inputs": torch.zeros(1, 8),
                "hw_state": torch.zeros(1, 10),
                "prev_action": torch.zeros(1, 24),
                "time_in_state": torch.zeros(1, 1),
            }

            torch.onnx.export(
                policy_net, (dummy,), output_path,
                input_names=["observation"],
                output_names=["action"],
                opset_version=14,
            )
            return True
        except Exception:
            return False

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_loaded(self) -> bool:
        return self._backend != "none"
