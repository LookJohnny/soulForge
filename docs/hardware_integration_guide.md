# Hardware Integration Guide

**Audience**: Toy manufacturers and hardware engineers integrating SoulForge into physical products.
**Prerequisites**: Basic electronics knowledge (servos, LEDs, microcontrollers). No AI expertise required.

---

## 1. What SoulForge Does for Your Toy

SoulForge turns a regular toy into an expressive, AI-powered character. You provide the physical hardware (servos, LEDs, speakers, sensors); SoulForge provides the brain that decides what to do and when.

Your hardware connects to SoulForge via a WebSocket. SoulForge sends commands like "move the head servo to 15 degrees over 500ms" and "set eye LEDs to warm yellow." Your firmware just executes them.

**What you need to build:**
1. A Hardware Manifest (JSON file describing your toy's capabilities)
2. A WebSocket client on your microcontroller (ESP32 recommended)
3. Actuator drivers (servo PWM, LED control, speaker output)

**What SoulForge provides:**
- AI conversation (speech recognition, LLM, text-to-speech)
- Emotional expression logic (which emotions map to which movements)
- Safety limits (thermal protection, battery management, joint limits)
- Graceful degradation (works on cheap hardware and premium hardware)

---

## 2. Integration Process Overview

```
Step 1: Define your hardware      (write hardware_manifest.json)
Step 2: Wire up your electronics  (servos, LEDs, sensors, speaker)
Step 3: Flash the firmware        (ESP32 + xiaozhi protocol)
Step 4: Connect to SoulForge      (WebSocket handshake)
Step 5: Test with the simulator   (digital twin before real hardware)
Step 6: Tune and optimize         (adjust manifest, test scenarios)
```

---

## 3. Step 1: Write Your Hardware Manifest

The Hardware Manifest is a JSON file that tells SoulForge exactly what your toy can do. It follows the schema defined in `protocol/hardware_manifest.schema.json`.

### 3.1 Manifest Structure

```json
{
  "device_id": "your-product-id-001",
  "form_factor": { ... },
  "actuators": [ ... ],
  "sensors": [ ... ],
  "power": { ... },
  "believability_profile": { ... }
}
```

### 3.2 Form Factor

Describes the physical body of the toy.

```json
"form_factor": {
  "type": "plush",
  "height_cm": 30,
  "weight_g": 500,
  "has_costume": true,
  "costume_friction_factor": 0.3
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `type` | `"plush"`, `"rigid"`, `"hybrid"` | Body material type. Affects how movements look and sound |
| `height_cm` | number | Total height of the toy |
| `weight_g` | number | Total weight including electronics |
| `has_costume` | boolean | Whether the toy wears fabric clothing over its mechanism |
| `costume_friction_factor` | 0.0 - 1.0 | How much the costume resists servo motion (0 = none, 1 = heavy resistance) |

### 3.3 Actuators

List every motor, LED, and speaker in your toy.

```json
"actuators": [
  {
    "id": "neck_yaw",
    "type": "servo",
    "body_part": "neck",
    "dof": 1,
    "range_min": -45,
    "range_max": 45,
    "unit": "degrees",
    "max_speed": 200,
    "thermal_limit_celsius": 65,
    "noise_db_at_max_speed": 38,
    "stall_torque_nm": 0.5,
    "backlash_degrees": 2.0
  }
]
```

**Actuator types:**

| Type | Description | Required fields |
|------|-------------|-----------------|
| `servo` | Rotary servo motor | range_min, range_max (degrees), max_speed (deg/s), thermal_limit_celsius |
| `motor` | DC or stepper motor | range_min, range_max, max_speed |
| `led_single` | Single-color LED | range_min=0, range_max=255 (brightness) |
| `led_rgb` | RGB LED | range_min=0, range_max=255 (per channel) |
| `led_matrix` | LED matrix display (for eye expressions) | range_min=0, range_max=255 |
| `speaker` | Audio speaker | range_min=0, range_max=100 (volume %) |
| `vibration` | Vibration motor | range_min=0, range_max=255 (intensity) |
| `linear_actuator` | Linear push/pull actuator | range_min, range_max (mm) |

**Body parts:**

`head`, `neck`, `left_arm`, `right_arm`, `body`, `left_leg`, `right_leg`, `eyes`, `mouth`, `tail`, `ears`

### 3.4 Sensors

List every sensor that provides input to SoulForge.

```json
"sensors": [
  {
    "id": "touch_head",
    "type": "touch_pressure",
    "body_part": "head",
    "sample_rate_hz": 20,
    "range_min": 0,
    "range_max": 1023
  }
]
```

**Sensor types:**

| Type | Description | Typical sample rate |
|------|-------------|-------------------|
| `touch_binary` | Simple on/off touch sensor | 10 Hz |
| `touch_pressure` | Pressure-sensitive touch (analog) | 20 Hz |
| `proximity_ir` | Infrared proximity sensor | 10 Hz |
| `proximity_ultrasonic` | Ultrasonic distance sensor | 10 Hz |
| `microphone` | Audio input | 16000 Hz |
| `camera` | Visual input | 15-30 Hz |
| `imu_6dof` | 6-axis accelerometer + gyroscope | 100 Hz |
| `imu_9dof` | 9-axis IMU (+ magnetometer) | 100 Hz |
| `temperature` | Temperature sensor | 1 Hz |
| `light_ambient` | Ambient light level | 5 Hz |
| `button` | Physical push button | 10 Hz |

### 3.5 Power

Describe the battery system.

```json
"power": {
  "battery_capacity_mah": 2500,
  "voltage_nominal": 3.7,
  "voltage_cutoff": 3.3,
  "max_continuous_draw_ma": 1500,
  "charging_method": "usb_c"
}
```

SoulForge uses the `voltage_cutoff` to automatically reduce motor activity when the battery is low, preventing brownout resets.

**Charging methods:** `"usb_c"`, `"micro_usb"`, `"wireless_qi"`, `"replaceable_battery"`

### 3.6 Believability Profile

Declares the upper limit of expression quality your hardware can achieve. SoulForge uses this to set realistic expectations for the AI.

```json
"believability_profile": {
  "max_emotion_channels": 5,
  "gesture_fluidity_score": 0.85,
  "audio_visual_sync_capable": true,
  "idle_animation_capable": true,
  "touch_responsive": true
}
```

| Field | Description | How to determine |
|-------|-------------|------------------|
| `max_emotion_channels` | How many independent actuators can express emotion simultaneously | Count your servo + LED + vibration actuators |
| `gesture_fluidity_score` | 0.0 (on/off only) to 1.0 (fully continuous smooth motion) | Servos with >100 deg/s and <3 deg backlash score >0.7. LEDs only = 0.1 |
| `audio_visual_sync_capable` | Can your hardware play audio and move servos at the same time? | true if speaker and servos share a stable power supply |
| `idle_animation_capable` | Can the toy run subtle idle animations continuously? | true if battery lasts >2 hours with idle animations |
| `touch_responsive` | Does the toy have any touch sensors? | true if at least one touch sensor is present |

---

## 4. Hardware Tier Suggestions

SoulForge works across three hardware tiers. Pick the one that matches your product's price point.

### 4.1 Basic Tier (~$5-10 electronics BOM)

**Target**: Low-cost plush toys, impulse purchases.

| Component | Suggested Part | Qty | Purpose |
|-----------|---------------|-----|---------|
| MCU | ESP32-C3-MINI-1 | 1 | WiFi, audio processing |
| Speaker | 28mm 8ohm 1W | 1 | Voice output |
| LED | Single-color warm white | 2 | Eye glow |
| Vibration motor | 3V coin type | 1 | Touch feedback |
| Button | Tactile switch | 1 | Belly button input |
| Battery | 600mAh LiPo | 1 | ~3 hours runtime |
| Microphone | INMP441 I2S MEMS | 1 | Voice input |

**Believability ceiling**: ~0.25. Can convey emotions through LED brightness, vibration patterns, and voice tone. No physical movement.

### 4.2 Mid Tier (~$15-25 electronics BOM)

**Target**: Gift-quality interactive toys.

| Component | Suggested Part | Qty | Purpose |
|-----------|---------------|-----|---------|
| MCU | ESP32-S3-WROOM-1-N16R8 | 1 | WiFi, BT, dual core |
| Speaker | 40mm 4ohm 3W | 1 | Clear voice output |
| Servo | SG90 micro servo | 1 | Head pan (yaw) |
| LED | WS2812B RGB | 2 | Eye expressions |
| Touch sensor | TTP223 capacitive | 1 | Head pat detection |
| Microphone | INMP441 I2S MEMS | 1 | Voice input |
| Battery | 1200mAh LiPo | 1 | ~4 hours runtime |

**Believability ceiling**: ~0.50. Head can turn to track the user, eyes change color with mood, and touch triggers reactions.

### 4.3 Full Tier (~$40-60 electronics BOM)

**Target**: Premium character toys, educational companions.

| Component | Suggested Part | Qty | Purpose |
|-----------|---------------|-----|---------|
| MCU | ESP32-S3-WROOM-1-N16R8 | 1 | WiFi, BT, dual core |
| Speaker | 40mm 4ohm 5W + I2S DAC | 1 | High-quality audio |
| Servo (head) | MG90S metal gear | 2 | Head pan + tilt |
| Servo (arms) | SG90 micro | 2 | Arm wave/hug |
| LED | 8x8 LED matrix (IS31FL3731) | 2 | Animated eye expressions |
| Vibration motor | LRA linear resonant | 1 | Haptic feedback |
| Touch sensor | MPR121 12-channel capacitive | 1 | Head, belly, hand zones |
| Proximity sensor | VL53L0X ToF | 1 | Detect approaching user |
| IMU | MPU6050 6-axis | 1 | Detect pick-up, shake |
| Microphone | INMP441 I2S MEMS | 1 | Voice input |
| Battery | 2500mAh LiPo | 1 | ~5 hours runtime |

**Believability ceiling**: ~0.85. Full emotional expression through movement, eye animations, touch responses, and context-aware reactions.

---

## 5. Connecting to the Gateway

### 5.1 WebSocket Connection

Your device connects to the SoulForge Gateway via WebSocket:

```
ws://<gateway-host>:8080/ws
```

The Gateway auto-detects your protocol from the first message. SoulForge supports the **xiaozhi-esp32** protocol natively, which is the recommended approach.

### 5.2 Xiaozhi Protocol Messages

The xiaozhi protocol uses text frames (JSON) for control and binary frames for audio.

#### Connection Handshake

Your device sends a `hello` message as the first frame:

```json
{
  "type": "hello",
  "device_id": "sf-full-001",
  "device_secret": "optional-auth-token",
  "firmware_version": "1.0.0",
  "hardware_manifest_id": "sf-full-001"
}
```

The server responds:

```json
{
  "type": "hello",
  "session_id": "abc123",
  "transport": "websocket"
}
```

#### Sending Audio (Voice Input)

1. Start listening:
```json
{"type": "listen", "state": "start"}
```

2. Stream audio as binary frames (16kHz, 16-bit PCM, little-endian). Send chunks of 320-640 bytes (10-20ms of audio) at a regular interval.

3. Stop listening:
```json
{"type": "listen", "state": "stop"}
```

4. The server will respond with TTS text and audio:
```json
{"type": "tts", "state": "start", "text": ""}
```
```json
{"type": "tts", "state": "sentence", "text": "Hi there! I'm happy to see you!"}
```
Binary frames containing TTS audio (same format: 16kHz 16-bit PCM).
```json
{"type": "tts", "state": "stop", "text": ""}
```

#### Sending Touch Events

When a touch sensor is activated:

```json
{
  "type": "touch",
  "gesture": "pat",
  "zone": "head",
  "pressure": 0.7,
  "duration_ms": 500
}
```

**Gesture values**: `"pat"`, `"stroke"`, `"poke"`, `"hold"`, `"squeeze"`, `"none"`

**Zone values**: Match the `body_part` values from your hardware manifest.

#### Aborting a Response

To interrupt the current AI response (e.g., user starts talking again):

```json
{"type": "abort"}
```

#### IoT Descriptors (Optional)

Report device state for context-aware responses:

```json
{
  "type": "iot",
  "descriptors": {
    "battery_pct": 85,
    "ambient_light": "dim",
    "temperature_c": 24,
    "charging": false
  }
}
```

### 5.3 Receiving Hardware Commands

SoulForge sends hardware commands as JSON text frames:

```json
{
  "type": "command",
  "commands": [
    {
      "actuator_id": "neck_yaw",
      "command_type": "position",
      "value": 15.0,
      "duration_ms": 500,
      "easing": "ease_in_out"
    },
    {
      "actuator_id": "eyes_led",
      "command_type": "color",
      "value": [255, 210, 90],
      "duration_ms": 500,
      "easing": "ease_in_out"
    },
    {
      "actuator_id": "body_vibration",
      "command_type": "vibration",
      "value": 0.3,
      "duration_ms": 300,
      "easing": "linear"
    }
  ]
}
```

**Command types:**

| Type | Value format | Description |
|------|-------------|-------------|
| `position` | float (degrees or mm) | Move servo/actuator to target position |
| `color` | [R, G, B] (0-255 each) | Set LED color |
| `brightness` | float (0.0-1.0) | Set LED brightness |
| `vibration` | float (0.0-1.0) | Set vibration motor intensity |
| `audio` | (sent as binary frame) | Play audio through speaker |

**Easing curves:**

| Easing | Description | Use case |
|--------|-------------|----------|
| `linear` | Constant speed | LEDs, vibration |
| `ease_in` | Start slow, finish fast | Anticipation |
| `ease_out` | Start fast, finish slow | Natural deceleration |
| `ease_in_out` | Slow-fast-slow (smoothstep) | Default for servos |

### 5.4 Firmware Implementation Tips

1. **Command buffering**: Buffer incoming commands and execute them at a fixed rate (50 Hz recommended). Do not execute commands as soon as they arrive -- this causes jitter.

2. **Interpolation**: For servo positions, always interpolate between the current position and the target using the specified easing curve and duration. Never snap directly to a target position.

3. **Audio priority**: When TTS audio is playing, prioritize speaker output over movement commands. A slight delay in movement (50-100ms) while starting audio playback is acceptable.

4. **Power management**: Monitor battery voltage. When voltage drops below `voltage_cutoff + 0.2V`, reduce servo speed by 50% and LED brightness by 30%.

5. **Watchdog**: If no WebSocket message is received for 30 seconds, send a heartbeat. If no response after 3 heartbeats, reconnect.

---

## 6. Testing with the Digital Twin Simulator

Before committing to real hardware, test your manifest with the SoulForge digital twin simulator.

### 6.1 Running the Simulator

```bash
cd soulForge
uv run python -c "
import json
from simulator.toy_simulator import ToySimulator

# Load your manifest
with open('protocol/examples/full_featured.json') as f:
    manifest = json.load(f)

sim = ToySimulator(manifest)

# Send some commands
commands = [
    {'actuator_id': 'neck_yaw', 'command_type': 'position', 'value': 15.0},
    {'actuator_id': 'eyes_led', 'command_type': 'color', 'value': [255, 210, 90]},
]

# Run 100 steps at 50Hz
for i in range(100):
    state = sim.step(commands, dt=0.02)

print(f'Servo positions: {state.servo_positions}')
print(f'Temperatures: {state.servo_temperatures}')
print(f'Battery: {state.battery_soc}%')
"
```

### 6.2 Running the Full Pipeline Demo

The pipeline demo runs all 6 scenario types through your manifest:

```bash
cd soulForge
uv run python demo/pipeline_demo.py
```

Output shows believability scores, safety status, and battery consumption for each scenario. Use this to tune your manifest and identify hardware bottlenecks.

### 6.3 What the Simulator Checks

- **Thermal safety**: Will your servos overheat during continuous use?
- **Battery life**: How long does the toy last under each scenario?
- **Believability score**: How expressive can your hardware be?
- **Safety constraint violations**: Any commands that would exceed joint limits or thermal limits?

---

## 7. Troubleshooting

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| Low believability score (<0.3) | Not enough actuators | Add an RGB LED or a second servo |
| Servo overheating warnings | Too much continuous motion | Increase `thermal_limit_celsius` or add heatsinks |
| Battery drains in <2 hours | High servo current draw | Use smaller servos or reduce motion amplitude |
| Jerky movements | Missing easing in firmware | Implement interpolation with ease_in_out curve |
| No reaction to touch | Touch sensor not in manifest | Add sensor entry to your manifest JSON |
| WebSocket disconnects | Network timeout | Implement heartbeat every 15 seconds |
| Audio stutters during movement | Power supply droop | Add a 470uF capacitor near the servo power input |

---

## 8. Quick Reference: Manifest Validation

Before deploying, validate your manifest against the schema:

```bash
uv run python -c "
import json, jsonschema

with open('protocol/hardware_manifest.schema.json') as f:
    schema = json.load(f)
with open('your_manifest.json') as f:
    manifest = json.load(f)

jsonschema.validate(manifest, schema)
print('Manifest is valid.')
"
```

Required top-level fields: `device_id`, `form_factor`, `actuators`, `sensors`, `power`, `believability_profile`.

---

## 9. Next Steps

1. Start with a mid-tier manifest and the simulator
2. Run `demo/pipeline_demo.py` to see believability scores
3. Iterate on your actuator selection until you hit your target score
4. Flash xiaozhi firmware on your ESP32
5. Connect to the SoulForge Gateway and test with real speech
6. Run `demo/comparison_demo.py` to see how RL-optimized behavior compares to rule-based behavior on your hardware
