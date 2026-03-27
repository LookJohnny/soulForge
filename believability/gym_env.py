"""Believability RL Training Environment.

Ref: Olaf Sec. V-B formula (3) state definition, Sec. V-C formula (4) reward.

Gymnasium-compatible environment for training believability policies.
Observation = emotion context + channel history + sensors + hardware state.
Action = parameterized CompositePrimitive selection.
Reward = BelievabilityMetrics.compute_total_score() + safety bonus.
"""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
    HAS_GYM = True
except ImportError:
    HAS_GYM = False
    # Minimal stub for environments without gymnasium
    class _StubEnv:
        observation_space = None
        action_space = None
        def step(self, action): ...
        def reset(self, **kw): ...
    gym = type('gym', (), {'Env': _StubEnv, 'spaces': type('spaces', (), {
        'Dict': dict, 'Box': lambda **kw: None, 'Discrete': lambda n: None,
    })})()

from believability.metrics import BelievabilityMetrics
from believability.scenario_generator import generate as gen_scenario


# Number of channels tracked
N_CHANNELS = 20
HISTORY_LEN = 10  # frames of history in observation
N_EMOTIONS = 11
N_GESTURES = 13
N_SENSORS = 8


class BelievabilityEnv(gym.Env if HAS_GYM else object):
    """RL environment for believability optimization.

    Observation space (Dict):
      emotion_context: Box(12)  — one-hot emotion + intensity
      channel_history: Box(10,20) — last 10 frames × 20 channels
      sensor_inputs: Box(8)
      hw_state: Box(10) — temperatures, battery
      prev_action: Box(24)
      time_in_state: Box(1)

    Action space: Box(24)
      Encodes: emotion_type(11) + intensity(1) + gesture(12) +
               amplitude(1) + speed(1) + attention_yaw(1) + pitch(1) +
               idle params(2) = ~30 dims, compressed to 24.

    Reward = believability_score + safety_bonus - constraint_violations
    """

    metadata = {"render_modes": []}

    def __init__(self, hardware_manifest: dict | None = None,
                 persona_config: dict | None = None,
                 scenario_type: str = "mixed",
                 episode_length: int = 500):
        super().__init__()

        self.scenario_type = scenario_type
        self.episode_length = episode_length
        self.metrics = BelievabilityMetrics()

        if HAS_GYM:
            self.observation_space = spaces.Dict({
                "emotion_context": spaces.Box(low=0, high=1, shape=(N_EMOTIONS + 1,), dtype=np.float32),
                "channel_history": spaces.Box(low=-1, high=1, shape=(HISTORY_LEN, N_CHANNELS), dtype=np.float32),
                "sensor_inputs": spaces.Box(low=0, high=1, shape=(N_SENSORS,), dtype=np.float32),
                "hw_state": spaces.Box(low=0, high=1, shape=(10,), dtype=np.float32),
                "prev_action": spaces.Box(low=0, high=1, shape=(24,), dtype=np.float32),
                "time_in_state": spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32),
            })
            self.action_space = spaces.Box(low=0, high=1, shape=(24,), dtype=np.float32)

        # Internal state
        self._step_count = 0
        self._time = 0.0
        self._dt = 0.02  # 50Hz
        self._channel_history = np.zeros((HISTORY_LEN, N_CHANNELS), dtype=np.float32)
        self._current_emotion = 0
        self._emotion_intensity = 0.0
        self._sensor_state = np.zeros(N_SENSORS, dtype=np.float32)
        self._hw_state = np.ones(10, dtype=np.float32) * 0.5
        self._prev_action = np.zeros(24, dtype=np.float32)
        self._scenario_events: list[dict] = []
        self._event_idx = 0
        self._gaze_history: list[tuple[float, float]] = []

    def reset(self, seed=None, options=None):
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        self._step_count = 0
        self._time = 0.0
        self._channel_history = np.zeros((HISTORY_LEN, N_CHANNELS), dtype=np.float32)
        self._current_emotion = 0
        self._emotion_intensity = 0.0
        self._sensor_state = np.zeros(N_SENSORS, dtype=np.float32)
        self._hw_state = np.ones(10, dtype=np.float32) * 0.5
        self._hw_state[0] = 0.9  # battery starts high
        self._prev_action = np.zeros(24, dtype=np.float32)
        self._gaze_history = []

        # Generate scenario
        duration = self.episode_length * self._dt
        self._scenario_events = gen_scenario(duration, self.scenario_type, seed)
        self._event_idx = 0

        obs = self._get_obs()
        return obs, {}

    def step(self, action: np.ndarray):
        self._step_count += 1
        self._time += self._dt

        # Decode action → channel outputs (simplified)
        channel_output = self._decode_action(action)

        # Process scenario events up to current time
        self._process_events()

        # Update channel history
        self._channel_history = np.roll(self._channel_history, -1, axis=0)
        self._channel_history[-1] = channel_output[:N_CHANNELS]

        # Simulate hardware state changes
        self._hw_state[0] -= 0.0001  # battery drain
        self._hw_state[0] = max(0, self._hw_state[0])
        # Temperature slowly rises with activity
        activity = float(np.mean(np.abs(channel_output[:N_CHANNELS])))
        self._hw_state[1] = min(1.0, self._hw_state[1] + activity * 0.001)

        # Track gaze for attention continuity
        yaw = float(channel_output[8]) * 60  # eye_yaw
        pitch = float(channel_output[9]) * 30  # eye_pitch
        self._gaze_history.append((yaw, pitch))
        if len(self._gaze_history) > 250:
            self._gaze_history = self._gaze_history[-250:]

        # Compute reward
        reward, info = self._compute_reward(action, channel_output)

        self._prev_action = action.copy()

        terminated = self._step_count >= self.episode_length
        truncated = False

        return self._get_obs(), reward, terminated, truncated, info

    def _get_obs(self) -> dict:
        emotion_ctx = np.zeros(N_EMOTIONS + 1, dtype=np.float32)
        if 0 <= self._current_emotion < N_EMOTIONS:
            emotion_ctx[self._current_emotion] = 1.0
        emotion_ctx[-1] = self._emotion_intensity

        return {
            "emotion_context": emotion_ctx,
            "channel_history": self._channel_history.copy(),
            "sensor_inputs": self._sensor_state.copy(),
            "hw_state": self._hw_state.copy(),
            "prev_action": self._prev_action.copy(),
            "time_in_state": np.array([min(1.0, self._step_count / self.episode_length)], dtype=np.float32),
        }

    def _decode_action(self, action: np.ndarray) -> np.ndarray:
        """Decode 24-dim action vector into channel outputs."""
        output = np.zeros(N_CHANNELS, dtype=np.float32)

        # Action dims: [0-10] emotion one-hot → not directly a channel
        # [11] emotion intensity
        # [12-14] head_yaw, head_pitch, head_roll
        # [15-16] body_pitch, body_roll
        # [17-18] left_arm, right_arm
        # [19-20] eye_yaw, eye_pitch
        # [21] eyelid
        # [22] led_brightness
        # [23] mouth

        output[0] = (action[12] - 0.5) * 2  # head_yaw [-1, 1]
        output[1] = (action[13] - 0.5) * 2  # head_pitch
        output[2] = (action[14] - 0.5) * 2  # head_roll
        output[3] = (action[15] - 0.5) * 2  # body_pitch
        output[4] = (action[16] - 0.5) * 2  # body_roll
        output[5] = action[17] * 2 - 1      # left_arm
        output[6] = action[18] * 2 - 1      # right_arm
        output[7] = action[22]               # led_brightness
        output[8] = (action[19] - 0.5) * 2  # eye_yaw
        output[9] = (action[20] - 0.5) * 2  # eye_pitch
        output[10] = action[21]              # eyelid
        output[11] = (action[23] - 0.5) * 2 # mouth

        return output

    def _process_events(self):
        """Consume scenario events up to current time."""
        while self._event_idx < len(self._scenario_events):
            event = self._scenario_events[self._event_idx]
            if event["t"] > self._time:
                break
            self._event_idx += 1

            if event["type"] == "emotion_change":
                self._current_emotion = event["data"].get("emotion", 0)
                self._emotion_intensity = event["data"].get("intensity", 0.5)
            elif event["type"] == "sensor":
                for k, v in event["data"].items():
                    idx = hash(k) % N_SENSORS
                    self._sensor_state[idx] = min(1.0, v)
            elif event["type"] == "idle_start":
                self._sensor_state[:] = 0

    def _compute_reward(self, action: np.ndarray, channels: np.ndarray) -> tuple[float, dict]:
        """Compute believability reward."""
        ch_dict = {f"ch_{i}": float(channels[i]) for i in range(N_CHANNELS)}

        # Sub-metrics
        coherence = self.metrics.emotion_action_coherence(
            self._current_emotion, self._emotion_intensity,
            {"head_pitch": float(channels[1]), "led_brightness": float(channels[7]),
             "body_pitch": float(channels[3])},
        )

        # Motion smoothness (from history)
        history = self._channel_history[:, 1].tolist()  # head_pitch channel
        smoothness = self.metrics.motion_smoothness(history, self._dt)

        # Jitter
        jitter = self.metrics.jitter_penalty(history, self._dt)

        # Attention continuity
        attention = self.metrics.attention_continuity(self._gaze_history)

        # Idle liveliness (all channels)
        idle = self.metrics.idle_liveliness(
            {f"ch_{i}": self._channel_history[:, i].tolist() for i in range(min(5, N_CHANNELS))},
            dt=self._dt,
        )

        state = {
            "emotion_action_coherence": coherence,
            "attention_continuity": attention,
            "motion_smoothness": smoothness,
            "rhythm_variation": 0.5,  # hard to compute per-step
            "idle_liveliness": idle,
            "reaction_latency": 0.7,  # would need event tracking
            "context_appropriateness": 0.6,
            "jitter_penalty": jitter,
            "impact_noise": 0.8,
        }

        total, breakdown = self.metrics.compute_total_score(state)

        # Safety bonus: battery and temperature OK
        safety_bonus = 0.1 if self._hw_state[0] > 0.2 and self._hw_state[1] < 0.8 else -0.1

        # Survival reward (ref Olaf Tab. I: survival = 1.0)
        survival = 0.05

        reward = float(total) + safety_bonus + survival

        info = {"believability_score": total, "sub_metrics": breakdown,
                "safety_bonus": safety_bonus}
        return reward, info
