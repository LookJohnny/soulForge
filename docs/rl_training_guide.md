# RL Training Operations Manual

**Audience**: Engineers training and deploying believability policies for SoulForge toys.

This guide covers the reinforcement learning (RL) system that optimizes how a toy character expresses emotions, gestures, and idle behavior. The RL policy learns to maximize a "believability score" -- a composite metric inspired by Disney Research's Olaf system.

---

## 1. Prerequisites

### 1.1 Python Environment

SoulForge requires Python 3.12+. All dependencies are managed by `uv`.

```bash
cd soulForge
uv sync
```

### 1.2 Required Packages

The RL system has two backends:

**Simple ES backend** (no extra dependencies -- always available):
- `numpy` (included in base install)

**Full PPO backend** (optional, for production training):
```bash
uv add stable-baselines3 gymnasium torch
```

The system auto-detects which backend is available and falls back gracefully.

### 1.3 Hardware Manifest

Training requires a hardware manifest (JSON) that describes the target toy. Three examples ship with SoulForge:

| Manifest | Path | Hardware Level |
|----------|------|---------------|
| Full-featured | `protocol/examples/full_featured.json` | 4 servos, LED matrix, vibration |
| Mid-range | `protocol/examples/mid_range.json` | 1 servo, RGB LED |
| Basic | `protocol/examples/basic.json` | LEDs, vibration only |

### 1.4 Configuration File

Training parameters are defined in `configs/default_believability.yaml`:

```yaml
weights:
  emotion_action_coherence: 4.0   # Most important: emotion-action alignment
  speech_expression_sync: 3.0     # Mouth moves when speaking
  attention_continuity: 2.0       # Eyes don't jump randomly
  motion_smoothness: 3.0          # No jerkiness
  rhythm_variation: 1.5           # Not too mechanical
  idle_liveliness: 2.5            # Looks alive when idle
  reaction_latency: 2.0           # Response speed is natural
  context_appropriateness: 3.0    # Response makes sense
  jitter_penalty: 5.0             # Heavy penalty for oscillation
  impact_noise: 2.5               # Noise from mechanical impacts

training:
  algorithm: PPO
  learning_rate: 3e-4
  gamma: 0.99
  gae_lambda: 0.95
  clip_range: 0.2
  n_steps: 512
  batch_size: 64
  n_epochs: 10
  net_arch: [256, 256, 256]
  n_envs: 4
  total_timesteps: 1000000
```

You can adjust the metric weights to prioritize different aspects of believability. For example, increase `idle_liveliness` weight for toys that spend most of their time idle.

---

## 2. Quick Start: Running a Training Session

### 2.1 Simple ES Training (5 minutes, no GPU)

The simplest way to get a trained policy:

```bash
cd soulForge
uv run python -c "
from believability.train import BelievabilityTrainer
from believability.gym_env import BelievabilityEnv

env = BelievabilityEnv(episode_length=200)
trainer = BelievabilityTrainer(env=env)
result = trainer.train(total_timesteps=5000, save_path='checkpoints/')
print(result)
"
```

This runs a simple evolutionary strategy (ES) optimizer. It samples random action biases, evaluates them over 200-step episodes, and keeps the best-performing weights. Output is saved to `checkpoints/simple_policy.npy`.

Expected output:
```
{'status': 'trained', 'episodes': 25, 'best_reward': 42.5, 'backend': 'simple_es'}
```

### 2.2 Full PPO Training (requires stable-baselines3)

For production-quality policies:

```bash
cd soulForge
uv run python -c "
from believability.train import BelievabilityTrainer
from believability.gym_env import BelievabilityEnv

env = BelievabilityEnv(episode_length=500)
trainer = BelievabilityTrainer(env=env, config={
    'learning_rate': 3e-4,
    'n_envs': 4,
    'total_timesteps': 100000,
})
result = trainer.train(total_timesteps=100000, save_path='checkpoints/')
print(result)
"
```

PPO training uses 4 parallel environments and a 3-layer MLP (256 units each). On a CPU, 100K timesteps takes approximately 10-15 minutes. Output is saved as `checkpoints/believability_policy.zip`.

---

## 3. Understanding the Environment

### 3.1 Observation Space

The RL agent sees the following observation at each timestep:

| Key | Shape | Description |
|-----|-------|-------------|
| `emotion_context` | (12,) | One-hot encoded current emotion (11) + intensity (1) |
| `channel_history` | (10, 20) | Last 10 frames of 20 channel outputs (head, body, eyes, LEDs, etc.) |
| `sensor_inputs` | (8,) | Current sensor readings (touch, proximity, IMU, etc.) |
| `hw_state` | (10,) | Hardware state: battery level, servo temperatures, etc. |
| `prev_action` | (24,) | The action taken at the previous timestep |
| `time_in_state` | (1,) | Fraction of episode elapsed (0.0 to 1.0) |

### 3.2 Action Space

The agent outputs a 24-dimensional continuous action vector (all values 0.0 to 1.0):

| Dims | Channel | Description |
|------|---------|-------------|
| 0-10 | Emotion one-hot | Not directly a channel; used for coherence scoring |
| 11 | Emotion intensity | How strongly to express the emotion |
| 12-14 | head_yaw, head_pitch, head_roll | Head servo targets (centered at 0.5) |
| 15-16 | body_pitch, body_roll | Body servo targets |
| 17-18 | left_arm, right_arm | Arm servo targets |
| 19-20 | eye_yaw, eye_pitch | Eye gaze targets |
| 21 | eyelid | Eyelid openness |
| 22 | led_brightness | LED brightness level |
| 23 | mouth | Mouth position |

### 3.3 Reward Function

The reward at each step is:

```
reward = believability_score + safety_bonus + survival_reward
```

Where:
- `believability_score` is a weighted sum of 9 sub-metrics (see section 4)
- `safety_bonus` = +0.1 if battery > 20% and temperature < 80%, else -0.1
- `survival_reward` = +0.05 (constant, encourages not crashing)

### 3.4 Scenarios

The environment generates scenarios from 5 types, mixed together:

| Scenario | Duration | Events |
|----------|----------|--------|
| Conversation | 20% | Speech inputs + emotion shifts |
| Touch play | 20% | Touch sensor activations |
| Idle | 20% | No inputs (tests idle liveliness) |
| Emotional | 20% | Gradual emotion arc transitions |
| Anomaly | 20% | Sudden loud noise, shake, freefall |

---

## 4. Monitoring Training Progress

### 4.1 Training Log

The `BelievabilityTrainer` records the best reward every 50 episodes in `trainer._train_log`:

```python
trainer = BelievabilityTrainer(env=env)
result = trainer.train(5000, "checkpoints/")
for entry in trainer._train_log:
    print(f"Episode {entry['episode']:4d}  Best reward: {entry['best_reward']:.2f}")
```

### 4.2 Key Metrics to Watch

| Metric | Good Range | What it means |
|--------|-----------|---------------|
| `emotion_action_coherence` | > 0.6 | Head tilts up for joy, down for sadness |
| `motion_smoothness` | > 0.7 | No jerky movements |
| `jitter_penalty` | > 0.8 | No high-frequency oscillation |
| `attention_continuity` | > 0.6 | Gaze moves smoothly, not randomly |
| `idle_liveliness` | > 0.4 | Character looks alive when idle |
| `reaction_latency` | > 0.5 | Responds at natural speed (not too fast, not too slow) |

### 4.3 Warning Signs

- **Reward plateaus early (< episode 50)**: Learning rate may be too high. Try `3e-5`.
- **Jitter penalty drops below 0.5**: The policy is oscillating actuators. Increase `jitter_penalty` weight.
- **Motion smoothness stays low**: The policy changes actions too aggressively. Increase `motion_smoothness` weight.
- **All sub-metrics are ~0.5**: The policy has not learned anything meaningful. Check that scenarios are generating events.

---

## 5. Evaluating Trained Policies

### 5.1 Built-in Evaluation

```python
from believability.train import BelievabilityTrainer
from believability.gym_env import BelievabilityEnv

env = BelievabilityEnv(episode_length=300)
trainer = BelievabilityTrainer(env=env)

# Load a trained policy for evaluation
# (For simple_es, the trainer uses random as fallback if no model is loaded)
result = trainer.evaluate(num_episodes=20)

print(f"Mean believability: {result['mean_believability_score']:.4f}")
print(f"Mean reward:        {result['mean_episode_reward']:.2f}")
print(f"Reward std:         {result['std_reward']:.2f}")
print()
print("Per-metric breakdown:")
for metric, score in result['per_metric_scores'].items():
    print(f"  {metric:30s}  {score:.4f}")
```

### 5.2 Comparison Demo

Run the comparison demo to see how different strategies perform side-by-side:

```bash
cd soulForge
uv run python demo/comparison_demo.py
```

This compares three strategies:
1. **Random** (baseline): Uniformly random actions
2. **Rule-based**: The BehaviorEngine with default behaviors
3. **RL-trained**: Loaded from `checkpoints/simple_policy.npy`

### 5.3 Interpreting Scores

| Total Score | Rating | Meaning |
|-------------|--------|---------|
| < 0.3 | Poor | Toy looks broken or mechanical |
| 0.3 - 0.5 | Fair | Recognizable as "trying to be alive" but unconvincing |
| 0.5 - 0.7 | Good | Believable character for most interactions |
| 0.7 - 0.85 | Great | Consistently natural, engaging behavior |
| > 0.85 | Excellent | Disney-quality character expression |

---

## 6. Deploying Policies

### 6.1 Loading a Policy for Inference

```python
from believability.policy import BelievabilityPolicy

# Load from checkpoint directory (auto-detects format)
policy = BelievabilityPolicy.load("checkpoints/")
print(f"Backend: {policy.backend}")  # "simple" or "sb3"

# Predict action from observation
observation = {
    "emotion_context": emotion_ctx_array,
    "channel_history": channel_history_array,
    "sensor_inputs": sensor_array,
    "hw_state": hw_state_array,
    "prev_action": prev_action_array,
    "time_in_state": time_array,
}
action = policy.predict(observation)
```

The policy runs inference in under 5ms on CPU, supporting the 50Hz (20ms) control loop.

### 6.2 ONNX Export (Edge Deployment)

For deploying on resource-constrained edge devices, export the policy to ONNX:

```python
from believability.policy import BelievabilityPolicy

policy = BelievabilityPolicy.load("checkpoints/believability_policy.zip")
success = policy.export_onnx("checkpoints/policy.onnx")

if success:
    print("ONNX export successful")
else:
    print("ONNX export requires sb3 backend with PyTorch")
```

ONNX export is only available for PPO-trained policies (the `.zip` format). Simple ES weights (`.npy` format) are just a single vector and can be loaded directly with `numpy.load()` on any platform.

### 6.3 Supported Formats

| Format | Extension | Backend | Size | Use case |
|--------|-----------|---------|------|----------|
| Simple weights | `.npy` | numpy | ~200 bytes | Prototype, embedded |
| SB3 checkpoint | `.zip` | stable-baselines3 | ~5 MB | Server-side inference |
| ONNX | `.onnx` | onnxruntime | ~2 MB | Edge devices, mobile |

### 6.4 Auto-detection from Directory

`BelievabilityPolicy.load()` accepts a directory path and auto-detects the format:

```python
# Checks for believability_policy.zip first, then simple_policy.npy
policy = BelievabilityPolicy.load("checkpoints/")
```

---

## 7. Advanced Configuration

### 7.1 Custom Metric Weights

To train a policy that prioritizes different aspects, modify the metric weights:

```python
from believability.metrics import BelievabilityMetrics

custom_weights = {
    "emotion_action_coherence": 6.0,  # Prioritize emotion expression
    "attention_continuity": 1.0,
    "motion_smoothness": 2.0,
    "rhythm_variation": 1.0,
    "idle_liveliness": 4.0,           # Important for this toy (lots of idle time)
    "reaction_latency": 2.0,
    "context_appropriateness": 2.0,
    "jitter_penalty": 5.0,
    "impact_noise": 2.0,
}

metrics = BelievabilityMetrics()
state = { ... }  # sub-metric values
total, breakdown = metrics.compute_total_score(state, weights=custom_weights)
```

### 7.2 Custom Scenarios

Create scenario-specific training by setting `scenario_type`:

```python
# Train only on idle scenarios (for a "sleeping companion" product)
env = BelievabilityEnv(scenario_type="idle", episode_length=500)

# Train only on conversation scenarios (for a "chat buddy" product)
env = BelievabilityEnv(scenario_type="conversation", episode_length=300)
```

Available types: `"mixed"`, `"conversation"`, `"touch_play"`, `"idle"`, `"emotional"`, `"anomaly"`

### 7.3 Persona-Specific Training

Different persona presets (see `configs/persona_presets/`) affect the ideal behavior style. A "calm_rabbit" should move differently from an "energetic_puppy."

Load a persona config and pass it to the environment:

```python
import yaml

with open("configs/persona_presets/energetic_puppy.yaml") as f:
    persona = yaml.safe_load(f)

env = BelievabilityEnv(persona_config=persona, episode_length=300)
```

---

## 8. Troubleshooting

### Problem: "ModuleNotFoundError: No module named 'gymnasium'"

The Simple ES backend does not require gymnasium. If you see this error during import, it is non-fatal -- the system falls back automatically. To use the full PPO backend:

```bash
uv add gymnasium stable-baselines3 torch
```

### Problem: Training produces NaN rewards

This usually means the environment is generating extreme values. Check:
1. That `episode_length` is > 50 (too short episodes produce unreliable scores)
2. That the `dt` parameter (0.02 by default) is reasonable for your scenario duration

### Problem: Policy oscillates between two values

The jitter penalty weight may be too low. Increase it:
```python
# In the reward computation or via custom weights
custom_weights = {**BelievabilityMetrics.DEFAULT_WEIGHTS, "jitter_penalty": 8.0}
```

### Problem: RL policy is worse than random

This can happen with very short training runs. The Simple ES backend needs at least 25 episodes (5000 timesteps with episode_length=200) to find a reasonable policy. For PPO, use at least 50K timesteps.

### Problem: ONNX export fails

ONNX export requires:
1. A PPO-trained policy (not simple_es)
2. PyTorch installed (`uv add torch`)
3. The policy loaded via `BelievabilityPolicy.load("checkpoints/believability_policy.zip")`

### Problem: Checkpoint directory is empty

Make sure the `save_path` directory exists and is writable. The trainer creates it automatically, but permission issues can prevent writing:
```bash
mkdir -p checkpoints
chmod 755 checkpoints
```

---

## 9. Architecture Reference

```
believability/
  gym_env.py              # Gymnasium environment (observation, action, reward)
  metrics.py              # 9 believability sub-metrics + weighted total
  policy.py               # Policy loading and inference (sb3/numpy/onnx)
  scenario_generator.py   # 5 scenario types for diverse training
  train.py                # BelievabilityTrainer (PPO + Simple ES)

configs/
  default_believability.yaml   # Metric weights + training hyperparameters
  default_behaviors.yaml       # BehaviorEngine configuration
  persona_presets/             # Per-character behavior tuning
    calm_rabbit.yaml
    cheerful_bear.yaml
    energetic_puppy.yaml

checkpoints/                   # Training outputs (gitignored)
  simple_policy.npy            # Simple ES weights
  believability_policy.zip     # SB3 PPO checkpoint
  policy.onnx                  # ONNX export for edge deployment
```
