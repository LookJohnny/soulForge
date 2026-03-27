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
        """Decode 24-dim action vector into channel outputs.

        Channel layout optimized for expressive toy (round display eyes + voice):
        [0-4]  Eye display: shape, size, pupil_size, eyelid, color_warmth
        [5-7]  Voice: speed, pitch, volume
        [8-9]  Eye gaze: yaw, pitch
        [10]   LED brightness
        [11]   Mouth shape (for display)
        [12-19] Reserved (body/limbs, unused for expressive toy)
        """
        output = np.zeros(N_CHANNELS, dtype=np.float32)

        # Eye display channels (primary)
        output[0] = (action[0] - 0.5) * 2   # eye_shape (-1=sad, +1=happy arc)
        output[1] = (action[1] - 0.5) * 2   # eye_size (-1=squint, +1=wide)
        output[2] = (action[2] - 0.5) * 2   # pupil_size (-1=small, +1=dilated)
        output[3] = (action[3] - 0.5) * 2   # eyelid (-1=closed, +1=open wide)
        output[4] = (action[4] - 0.5) * 2   # eye_color_warmth (-1=cool blue, +1=warm amber)

        # Voice channels
        output[5] = (action[5] - 0.5) * 2   # voice_speed (-1=slow, +1=fast)
        output[6] = (action[6] - 0.5) * 2   # voice_pitch (-1=low, +1=high)
        output[7] = (action[7] - 0.5) * 2   # voice_volume (-1=whisper, +1=loud)

        # Eye gaze (for tracking/attention)
        output[8] = (action[8] - 0.5) * 2   # eye_yaw
        output[9] = (action[9] - 0.5) * 2   # eye_pitch

        # Display
        output[10] = action[10]              # led_brightness (0-1)
        output[11] = (action[11] - 0.5) * 2 # mouth_shape

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
        """Compute believability reward — focused on eyes + voice + dialogue."""

        # Eye display channels
        eye_channels = {
            "eye_shape": float(channels[0]),
            "eye_size": float(channels[1]),
            "pupil_size": float(channels[2]),
            "eyelid": float(channels[3]),
            "eye_color_warmth": float(channels[4]),
        }

        # Voice channels
        voice_speed = float(channels[5])
        voice_pitch = float(channels[6])
        voice_volume = float(channels[7])

        # === PRIMARY: Eye + Voice metrics ===

        # Eye-emotion coherence (are the eyes expressing the right emotion?)
        eye_coherence = self.metrics.eye_emotion_coherence(
            self._current_emotion, self._emotion_intensity, eye_channels,
        )

        # Eye expression richness (are the eyes alive, not frozen?)
        eye_history = {
            f"ch_{i}": self._channel_history[:, i].tolist()
            for i in range(5)  # eye channels 0-4
        }
        eye_richness = self.metrics.eye_expression_richness(eye_history, dt=self._dt)

        # Voice-emotion match
        voice_match = self.metrics.voice_emotion_match(
            self._current_emotion, voice_speed, voice_pitch, voice_volume,
        )

        # Overall emotion-expression coherence (generic)
        coherence = self.metrics.emotion_action_coherence(
            self._current_emotion, self._emotion_intensity,
            {**eye_channels, "voice_speed": voice_speed, "voice_pitch": voice_pitch,
             "led_brightness": float(channels[10])},
        )

        # === SECONDARY: General naturalness ===

        attention = self.metrics.attention_continuity(self._gaze_history)

        eye_all_history = {
            f"ch_{i}": self._channel_history[:, i].tolist()
            for i in range(8)  # eye + voice channels
        }
        idle = self.metrics.idle_liveliness(eye_all_history, dt=self._dt)

        # Eye smoothness (no display flicker)
        eye_shape_hist = self._channel_history[:, 0].tolist()
        smoothness = self.metrics.motion_smoothness(eye_shape_hist, self._dt)
        jitter = self.metrics.jitter_penalty(eye_shape_hist, self._dt)

        state = {
            "eye_emotion_coherence": eye_coherence,
            "eye_expression_richness": eye_richness,
            "voice_emotion_match": voice_match,
            "dialogue_timing": 0.7,  # computed at dialogue events, default good
            "emotion_action_coherence": coherence,
            "attention_continuity": attention,
            "idle_liveliness": idle,
            "context_appropriateness": 0.6,
            "reaction_latency": 0.7,
            "motion_smoothness": smoothness,
            "jitter_penalty": jitter,
            "rhythm_variation": 0.5,
            "impact_noise": 1.0,  # no mechanical parts
        }

        total, breakdown = self.metrics.compute_total_score(state)

        safety_bonus = 0.1 if self._hw_state[0] > 0.2 else -0.1
        survival = 0.05
        reward = float(total) + safety_bonus + survival

        info = {"believability_score": total, "sub_metrics": breakdown,
                "safety_bonus": safety_bonus}
        return reward, info
