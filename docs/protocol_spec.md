# Performance Primitive Protocol Specification

**Version**: 1.0
**Status**: Stable
**Format**: Protocol Buffers (proto3)

This document specifies the Performance Primitive Protocol used by SoulForge to describe character expression on physical toys. The protocol is inspired by Disney Research's "Olaf" system (arXiv:2512.16705) and defines standardized messages that translate high-level character intent into hardware-agnostic performance instructions.

---

## 1. Overview

The Performance Primitive Protocol defines seven message types that together describe everything a toy character can express: emotions, attention, gestures, speech, rhythm, idle behavior, and composite multi-channel performances.

All primitives are defined in `protocol/primitives.proto` using Protocol Buffers v3 syntax. The package name is `soulforge`.

**Design principles:**

- **Hardware-agnostic**: Primitives describe *what* to express, not *how*. The Mapping Engine (`protocol/mapping_engine.py`) translates primitives to specific actuator commands.
- **Degradation-friendly**: Every primitive can be expressed at multiple fidelity levels. A toy with only an LED and vibration motor can still convey joy -- just not as richly as one with servos and an LED matrix.
- **Composable**: Individual primitives combine into a `CompositePrimitive` that represents a single frame of multi-channel performance.

---

## 2. Message Types

### 2.1 EmotionPrimitive

Describes the character's emotional state.

```protobuf
message EmotionPrimitive {
  EmotionType type = 1;
  float intensity = 2;            // 0.0-1.0
  uint32 duration_ms = 3;
  float transition_speed = 4;     // 0.0(gradual)-1.0(instant)
  EmotionType blend_with = 5;     // secondary emotion for blending
  float blend_ratio = 6;          // 0.0=primary only, 1.0=secondary only
}
```

**Fields:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `type` | EmotionType | 0-10 | Primary emotion (see enum below) |
| `intensity` | float | 0.0 - 1.0 | How strongly the emotion is expressed. 0.0 = barely perceptible, 1.0 = maximum expression |
| `duration_ms` | uint32 | 0 - 60000 | How long to hold this emotion. 0 = indefinite (until next primitive) |
| `transition_speed` | float | 0.0 - 1.0 | How quickly to transition from the current emotion. 0.0 = slow gradual blend, 1.0 = instant snap |
| `blend_with` | EmotionType | 0-10 | Optional secondary emotion to blend with the primary |
| `blend_ratio` | float | 0.0 - 1.0 | Blend weight. 0.0 = 100% primary, 0.5 = equal mix, 1.0 = 100% secondary |

### 2.2 AttentionPrimitive

Controls where and how the character directs its gaze.

```protobuf
message AttentionPrimitive {
  AttentionMode mode = 1;
  float yaw = 2;                  // horizontal angle -180~180
  float pitch = 3;                // vertical angle -90~90
  float tracking_speed = 4;       // tracking responsiveness
  uint32 hold_duration_ms = 5;    // gaze hold time
  float saccade_frequency = 6;    // micro-saccade rate (Hz)
}
```

**Fields:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `mode` | AttentionMode | 0-5 | Attention behavior mode (see enum below) |
| `yaw` | float | -180.0 to 180.0 | Horizontal gaze angle in degrees. 0 = forward, positive = right |
| `pitch` | float | -90.0 to 90.0 | Vertical gaze angle in degrees. 0 = level, positive = up |
| `tracking_speed` | float | 0.0 - 1.0 | How quickly gaze follows a target. 0.0 = lazy, 1.0 = snappy |
| `hold_duration_ms` | uint32 | 0 - 30000 | How long to hold gaze at a point before moving on |
| `saccade_frequency` | float | 0.0 - 5.0 | Rate of micro-saccades in Hz. Natural human range is 2-3 Hz |

### 2.3 GesturePrimitive

Describes a body gesture or movement.

```protobuf
message GesturePrimitive {
  GestureType type = 1;
  float amplitude = 2;            // motion magnitude 0.0-1.0
  float speed = 3;                // motion speed 0.0-1.0
  uint32 repeat_count = 4;        // 0 = single execution
  float expressiveness = 5;       // exaggeration factor 0.0-1.0
}
```

**Fields:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `type` | GestureType | 0-12 | Which gesture to perform (see enum below) |
| `amplitude` | float | 0.0 - 1.0 | How large the motion is. 0.0 = subtle, 1.0 = full range of motion |
| `speed` | float | 0.0 - 1.0 | Motion speed. 0.0 = slow and deliberate, 1.0 = fast and energetic |
| `repeat_count` | uint32 | 0 - 10 | Number of repetitions. 0 = execute once. E.g., wave 3 times |
| `expressiveness` | float | 0.0 - 1.0 | Exaggeration factor. Higher values add overshoot, secondary motion, and style |

### 2.4 VocalizationPrimitive

Controls speech output and lip-sync coordination.

```protobuf
message PhonemeTiming {
  string phoneme = 1;
  uint32 start_ms = 2;
  uint32 end_ms = 3;
}

message VocalizationPrimitive {
  string speech_text = 1;
  EmotionType emotion_overlay = 2;
  float volume = 3;               // 0.0-1.0
  float pitch_shift = 4;          // -1.0(low) ~ 1.0(high)
  float speed_ratio = 5;          // 0.5-2.0
  bool sync_gestures = 6;         // auto-sync body with speech
  repeated PhonemeTiming phonemes = 7;
}
```

**Fields:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `speech_text` | string | - | The text to speak via TTS |
| `emotion_overlay` | EmotionType | 0-10 | Emotion coloring for the TTS voice |
| `volume` | float | 0.0 - 1.0 | Output volume. Capped by SafetyManager to 65 dB |
| `pitch_shift` | float | -1.0 to 1.0 | Voice pitch adjustment. Negative = deeper, positive = higher |
| `speed_ratio` | float | 0.5 - 2.0 | Speech speed multiplier. 1.0 = normal |
| `sync_gestures` | bool | true/false | When true, the BehaviorEngine auto-generates gestures synchronized to speech rhythm |
| `phonemes` | PhonemeTiming[] | - | Optional per-phoneme timing for precise lip-sync and jaw movement |

### 2.5 RhythmPrimitive

Makes the character move to a beat, useful for music interaction.

```protobuf
message RhythmPrimitive {
  float bpm = 1;
  float body_sway_amplitude = 2;
  float head_bob_intensity = 3;
  float phase_offset = 4;         // 0-2*pi
  bool sync_to_audio = 5;
}
```

**Fields:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `bpm` | float | 20.0 - 300.0 | Beats per minute to synchronize movement to |
| `body_sway_amplitude` | float | 0.0 - 1.0 | How much the body sways side-to-side on the beat |
| `head_bob_intensity` | float | 0.0 - 1.0 | How much the head bobs up and down on the beat |
| `phase_offset` | float | 0.0 - 6.283 | Phase offset in radians. Allows head and body to move out of phase for more natural rhythm |
| `sync_to_audio` | bool | true/false | When true, BPM is auto-detected from the audio stream |

### 2.6 IdlePrimitive

Defines background alive-ness when no active interaction is happening.

```protobuf
message IdlePrimitive {
  float breathing_rate = 1;           // breaths/min, default 12-20
  float micro_movement_intensity = 2; // 0.0-1.0
  float eye_saccade_frequency = 3;    // Hz
  float fidget_probability = 4;       // probability/second
  string personality_preset = 5;      // "calm", "restless", "playful"
}
```

**Fields:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `breathing_rate` | float | 5.0 - 30.0 | Breaths per minute. Natural human range: 12-20. Toys can go outside this range for stylistic effect |
| `micro_movement_intensity` | float | 0.0 - 1.0 | Overall intensity of idle micro-movements (body drift, weight shifts) |
| `eye_saccade_frequency` | float | 0.5 - 5.0 | How often eye micro-saccades occur, in Hz. Natural: 2-3 Hz |
| `fidget_probability` | float | 0.0 - 1.0 | Probability per second of triggering a fidget animation (scratch, stretch, yawn) |
| `personality_preset` | string | "calm", "restless", "playful" | Shorthand for a set of idle parameters defined in persona presets |

### 2.7 CompositePrimitive

Combines all primitive types into a single multi-channel frame.

```protobuf
message CompositePrimitive {
  EmotionPrimitive emotion = 1;
  AttentionPrimitive attention = 2;
  GesturePrimitive gesture = 3;
  VocalizationPrimitive vocalization = 4;
  RhythmPrimitive rhythm = 5;
  IdlePrimitive idle = 6;

  uint64 timestamp_ms = 10;
  uint32 priority = 11;
  string source = 12;               // "llm", "sensor", "ambient"
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `emotion` | EmotionPrimitive | Emotional state for this frame |
| `attention` | AttentionPrimitive | Gaze direction and mode |
| `gesture` | GesturePrimitive | Body gesture to perform |
| `vocalization` | VocalizationPrimitive | Speech output |
| `rhythm` | RhythmPrimitive | Rhythmic movement parameters |
| `idle` | IdlePrimitive | Background alive-ness parameters |
| `timestamp_ms` | uint64 | Unix epoch milliseconds when this primitive was generated |
| `priority` | uint32 | Priority level (higher = more important). Used by the BehaviorEngine for conflict resolution |
| `source` | string | Origin of this primitive: `"llm"` (from AI), `"sensor"` (from hardware sensor), `"ambient"` (from idle behavior system) |

---

## 3. Enum Definitions

### 3.1 EmotionType (11 values)

```protobuf
enum EmotionType {
  NEUTRAL   = 0;   // No specific emotion, default state
  JOY       = 1;   // Happiness, delight
  SADNESS   = 2;   // Sorrow, disappointment
  SURPRISE  = 3;   // Unexpected event reaction
  ANGER     = 4;   // Frustration, annoyance
  FEAR      = 5;   // Anxiety, worry
  DISGUST   = 6;   // Displeasure, aversion
  CURIOSITY = 7;   // Interest, inquisitiveness
  AFFECTION = 8;   // Love, warmth, tenderness
  SLEEPY    = 9;   // Drowsiness, tiredness
  EXCITED   = 10;  // High-energy enthusiasm
}
```

Emotions map to specific hardware expression strategies via the Degradation Matrix in `protocol/mapping_engine.py`. Each emotion has predefined LED colors, head positions, and vibration patterns.

### 3.2 AttentionMode (6 values)

```protobuf
enum AttentionMode {
  IDLE_SCAN   = 0;  // Slowly scanning the environment
  DIRECT_GAZE = 1;  // Looking directly at a specific point
  AVERTED     = 2;  // Looking away (shy, thinking)
  TRACKING    = 3;  // Following a moving target
  DISTRACTED  = 4;  // Attention drifting away
  SEARCHING   = 5;  // Actively looking for something
}
```

### 3.3 GestureType (13 values)

```protobuf
enum GestureType {
  GESTURE_NONE = 0;   // No gesture
  WAVE         = 1;   // Arm wave (greeting/goodbye)
  NOD          = 2;   // Head nod (agreement, acknowledgment)
  SHAKE_HEAD   = 3;   // Head shake (disagreement, "no")
  TILT_HEAD    = 4;   // Head tilt (curiosity, thinking)
  SHRUG        = 5;   // Shoulder shrug (uncertainty)
  BOUNCE       = 6;   // Body bounce (excitement, rhythm)
  WIGGLE       = 7;   // Body wiggle (joy, playfulness)
  LEAN_FORWARD = 8;   // Lean forward (interest, engagement)
  LEAN_BACK    = 9;   // Lean back (relaxation, surprise)
  HUG_READY    = 10;  // Arms open for hug
  CLAP         = 11;  // Clapping (celebration)
  POINT        = 12;  // Pointing at something
}
```

---

## 4. Degradation Matrix

The Degradation Matrix is the mechanism that maps abstract primitives to concrete hardware commands across different hardware capability levels. It is implemented in `protocol/mapping_engine.py`.

For each primitive type, the matrix defines an ordered list of **expression strategies**. The Mapping Engine tries strategies top-down and picks the first one whose required actuators exist in the hardware manifest.

### Example: JOY emotion degradation chain

| Strategy | Required Hardware | Fidelity | Description |
|----------|-------------------|----------|-------------|
| `full_joy` | LED RGB/matrix + neck servo + body servo | 1.0 | Full expression: warm LED + head up + body bounce |
| `mid_joy` | LED RGB/matrix + neck servo | 0.75 | Good: warm LED + head tilt up |
| `led_joy` | Any LED | 0.50 | Okay: warm LED color only |
| `vib_joy` | Vibration motor | 0.25 | Minimal: short vibration pulse |

### Example: WAVE gesture degradation chain

| Strategy | Required Hardware | Fidelity | Description |
|----------|-------------------|----------|-------------|
| `arm_wave` | Arm servo | 1.0 | True arm wave motion |
| `body_wave` | Body/neck servo | 0.50 | Body sway to suggest waving |
| `led_wave` | Any LED | 0.30 | LED blink pattern |
| `vib_wave` | Vibration motor | 0.15 | Short vibration pulses |

---

## 5. Hardware Manifest

Every toy device is described by a Hardware Manifest JSON file (schema: `protocol/hardware_manifest.schema.json`). The manifest tells the Mapping Engine what actuators and sensors are available.

Three example manifests ship with SoulForge:

| Tier | File | Actuators | Believability ceiling |
|------|------|-----------|----------------------|
| Full | `protocol/examples/full_featured.json` | 4 servos + LED matrix + speaker + vibration | 0.85 |
| Mid | `protocol/examples/mid_range.json` | 1 servo + LED RGB + speaker | 0.50 |
| Basic | `protocol/examples/basic.json` | 2 LED single + speaker + vibration | 0.25 |

---

## 6. Serialization

### Protobuf Binary

The canonical wire format is Protocol Buffers binary encoding. Use the generated Python bindings:

```python
from protocol.primitives_pb2 import (
    CompositePrimitive, EmotionPrimitive, GesturePrimitive,
    EmotionType, GestureType,
)

# Create a composite primitive
msg = CompositePrimitive()
msg.emotion.type = EmotionType.JOY
msg.emotion.intensity = 0.8
msg.emotion.duration_ms = 500
msg.gesture.type = GestureType.BOUNCE
msg.gesture.amplitude = 0.6
msg.gesture.speed = 0.7
msg.timestamp_ms = 1711440000000
msg.priority = 5
msg.source = "llm"

# Serialize to bytes
data = msg.SerializeToString()

# Deserialize
msg2 = CompositePrimitive()
msg2.ParseFromString(data)
```

### JSON (for debugging and WebSocket)

For debugging or when protobuf is not available (e.g., web interfaces), primitives can be represented as JSON:

```json
{
  "emotion": {
    "type": 1,
    "intensity": 0.8,
    "duration_ms": 500,
    "transition_speed": 0.3
  },
  "gesture": {
    "type": 6,
    "amplitude": 0.6,
    "speed": 0.7,
    "repeat_count": 0,
    "expressiveness": 0.5
  },
  "timestamp_ms": 1711440000000,
  "priority": 5,
  "source": "llm"
}
```

---

## 7. Usage Examples

### 7.1 Greeting a user

A child walks up to the toy. The AI decides to greet them with joy.

```python
msg = CompositePrimitive()
msg.emotion.type = EmotionType.JOY
msg.emotion.intensity = 0.7
msg.emotion.duration_ms = 2000
msg.attention.mode = AttentionMode.DIRECT_GAZE
msg.attention.yaw = 0
msg.attention.pitch = 10  # slightly upward (child is taller)
msg.gesture.type = GestureType.WAVE
msg.gesture.amplitude = 0.8
msg.gesture.speed = 0.6
msg.gesture.repeat_count = 2
msg.vocalization.speech_text = "Hi there! I'm so happy to see you!"
msg.vocalization.emotion_overlay = EmotionType.JOY
msg.vocalization.volume = 0.7
msg.source = "llm"
```

### 7.2 Listening attentively

The child is telling a story. The toy shows active listening.

```python
msg = CompositePrimitive()
msg.emotion.type = EmotionType.CURIOSITY
msg.emotion.intensity = 0.5
msg.attention.mode = AttentionMode.DIRECT_GAZE
msg.attention.tracking_speed = 0.3
msg.gesture.type = GestureType.NOD
msg.gesture.amplitude = 0.3
msg.gesture.speed = 0.4
msg.gesture.repeat_count = 1
msg.idle.breathing_rate = 14
msg.idle.eye_saccade_frequency = 2.0
msg.source = "llm"
```

### 7.3 Idle behavior (no interaction)

The child has left. The toy is alone but should still look alive.

```python
msg = CompositePrimitive()
msg.emotion.type = EmotionType.NEUTRAL
msg.emotion.intensity = 0.2
msg.attention.mode = AttentionMode.IDLE_SCAN
msg.attention.saccade_frequency = 2.5
msg.idle.breathing_rate = 15
msg.idle.micro_movement_intensity = 0.3
msg.idle.eye_saccade_frequency = 2.5
msg.idle.fidget_probability = 0.1
msg.idle.personality_preset = "calm"
msg.source = "ambient"
```

### 7.4 Reacting to being picked up

The IMU detects a sudden lift. The reactive layer generates a surprise response.

```python
msg = CompositePrimitive()
msg.emotion.type = EmotionType.SURPRISE
msg.emotion.intensity = 0.9
msg.emotion.transition_speed = 0.9  # fast reaction
msg.gesture.type = GestureType.LEAN_BACK
msg.gesture.amplitude = 0.5
msg.gesture.speed = 0.8
msg.vocalization.speech_text = "Whoa!"
msg.vocalization.emotion_overlay = EmotionType.SURPRISE
msg.vocalization.volume = 0.6
msg.priority = 8  # high priority, overrides ambient
msg.source = "sensor"
```

### 7.5 Blended emotions

The child is leaving. The toy feels happy about the interaction but sad about the departure.

```python
msg = CompositePrimitive()
msg.emotion.type = EmotionType.AFFECTION
msg.emotion.intensity = 0.6
msg.emotion.blend_with = EmotionType.SADNESS
msg.emotion.blend_ratio = 0.3  # 70% affection, 30% sadness
msg.emotion.transition_speed = 0.2  # gradual
msg.gesture.type = GestureType.WAVE
msg.gesture.amplitude = 0.5
msg.gesture.speed = 0.3  # slow, reluctant wave
msg.vocalization.speech_text = "Bye bye... come back soon okay?"
msg.vocalization.pitch_shift = -0.1
msg.vocalization.speed_ratio = 0.9  # slightly slower
msg.source = "llm"
```

---

## 8. Pipeline Integration

The primitive flows through the SoulForge pipeline as follows:

```
LLM/Sensor/Ambient
       |
       v
CompositePrimitive
       |
       v
BehaviorEngine (3-layer blending: Ambient + Triggered + Reactive)
       |
       v
ChannelBlender (resolve conflicts per channel)
       |
       v
SafetyManager (CBF constraints: temperature, battery, joint limits)
       |
       v
MotionSmoother (jerk minimization)
       |
       v
MappingEngine (Degradation Matrix -> hardware commands)
       |
       v
HardwareCommands -> Actuators
```

The `MappingEngine.map()` method accepts a `CompositePrimitive` and returns a list of `HardwareCommand` objects ready to send to the device.

---

## 9. Versioning

Protocol versions follow semantic versioning. The current version is 1.0.

- **Patch** (1.0.x): Bug fixes, documentation updates. Fully backward compatible.
- **Minor** (1.x.0): New optional fields or enum values. Old clients can ignore new fields.
- **Major** (x.0.0): Breaking changes to existing message structure. Requires client updates.

New enum values (emotions, gestures, attention modes) are always added as minor versions and will not break existing implementations.
