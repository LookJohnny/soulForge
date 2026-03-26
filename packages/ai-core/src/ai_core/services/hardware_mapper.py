"""PAD → Hardware Command Mapper.

Maps continuous PAD (Pleasure-Arousal-Dominance) emotion values to
concrete hardware instructions for physical toys:
  - LED expression (eye shape, color)
  - Motor actions (head tilt, nod, sway)
  - Vibration patterns

Design: PAD values directly drive hardware. Action text is for companion app only.
Uses hysteresis on PAD boundaries to prevent emotion flickering.
"""

from dataclasses import dataclass

# ── Expression labels aligned with frontend 8-emotion system ──
# happy, sad, shy, angry, playful, curious, worried, calm
EXPRESSIONS = ("happy", "sad", "shy", "angry", "playful", "curious", "worried", "calm")


@dataclass
class LEDCommand:
    expression: str = "calm"
    color: tuple[int, int, int] = (200, 200, 220)
    brightness: float = 0.6

    def to_dict(self) -> dict:
        r, g, b = (max(0, min(255, c)) for c in self.color)
        return {"expression": self.expression, "color": [r, g, b], "brightness": round(max(0.1, min(1.0, self.brightness)), 2)}


@dataclass
class MotorCommand:
    action: str = "none"    # nod/shake/tilt_left/tilt_right/sway/bounce/none
    speed: float = 0.0      # 0.0-1.0
    intensity: float = 0.0  # 0.0-1.0

    def to_dict(self) -> dict:
        return {"action": self.action, "speed": round(self.speed, 2), "intensity": round(self.intensity, 2)}


@dataclass
class VibrationCommand:
    pattern: str = "none"   # pulse/steady/double/heartbeat/none
    intensity: float = 0.0
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "intensity": round(self.intensity, 2), "duration_ms": self.duration_ms}


@dataclass
class HardwareCommand:
    led: LEDCommand
    motor: MotorCommand
    vibration: VibrationCommand

    def to_dict(self) -> dict:
        return {"led": self.led.to_dict(), "motor": self.motor.to_dict(), "vibration": self.vibration.to_dict()}


# ── Expression color palette (warm/cool tones) ───

_EXPRESSION_CONFIG: dict[str, dict] = {
    #                     RGB color          base_brightness
    "happy":    {"color": (255, 210, 90),   "brightness": 0.85},  # warm gold
    "sad":      {"color": (100, 140, 210),  "brightness": 0.40},  # muted blue
    "shy":      {"color": (255, 160, 190),  "brightness": 0.55},  # pink blush
    "angry":    {"color": (240, 80, 80),    "brightness": 0.75},  # red
    "playful":  {"color": (180, 255, 140),  "brightness": 0.80},  # lime green
    "curious":  {"color": (140, 200, 255),  "brightness": 0.70},  # sky blue
    "worried":  {"color": (190, 170, 220),  "brightness": 0.50},  # lavender
    "calm":     {"color": (200, 210, 230),  "brightness": 0.50},  # soft white-blue
}


# ── LED: PAD → expression with hysteresis ─────────

def _map_led(p: float, a: float, d: float) -> LEDCommand:
    """Map PAD to LED expression, color, and brightness.

    Uses scoring instead of hard thresholds to avoid boundary flickering.
    Each expression has a "fit score" — highest score wins.
    """
    scores: dict[str, float] = {
        "happy":   p * 1.5 + a * 0.3 - abs(d) * 0.1,          # high P, any A
        "sad":     -p * 1.5 - a * 0.5 - d * 0.3,              # low P, low A, low D
        "shy":     -d * 1.2 + p * 0.3 - a * 0.3,              # low D (submissive)
        "angry":   -p * 1.0 + a * 1.2 + d * 0.5,              # low P, high A, high D
        "playful": p * 0.8 + a * 1.0 + d * 0.3,               # positive P, high A
        "curious": a * 0.8 + abs(p) * 0.2 - abs(d) * 0.2,     # moderate-high A, neutral P
        "worried": -p * 0.6 + a * 0.4 - d * 0.6,              # negative P, submissive
        "calm":    -abs(a) * 1.0 - abs(p) * 0.3,               # low everything
    }

    # Bias calm up so it wins when everything is near zero
    scores["calm"] += 0.3

    expr = max(scores, key=scores.get)
    cfg = _EXPRESSION_CONFIG[expr]

    # Brightness: base + arousal boost + pleasure boost
    brightness = cfg["brightness"] + a * 0.15 + max(0, p) * 0.1 - max(0, -d) * 0.05

    return LEDCommand(expression=expr, color=cfg["color"], brightness=brightness)


# ── Motor: PAD → physical movement ────────────────

def _map_motor(p: float, a: float, d: float) -> MotorCommand:
    """Map PAD to motor action. Low arousal → no movement."""

    # Arousal threshold: below this, stay still
    if abs(a) < 0.15 and abs(p) < 0.3:
        return MotorCommand()

    # Score each action
    candidates = {
        "bounce":     p * 0.8 + a * 0.8,                   # happy + excited
        "nod":        p * 0.6 + a * 0.2,                   # happy + mild
        "sway":       a * 0.5 + abs(p) * 0.2,              # general arousal
        "tilt_left":  -d * 0.8 + p * 0.2,                  # shy / cute
        "shake":      -p * 0.5 + a * 0.5,                  # disagree / upset
    }

    action = max(candidates, key=candidates.get)
    best_score = candidates[action]

    # Don't move if best score is very low
    if best_score < 0.15:
        return MotorCommand()

    speed = max(0.2, min(1.0, 0.3 + abs(a) * 0.5))
    intensity = max(0.15, min(1.0, abs(a) * 0.5 + abs(p) * 0.3))

    return MotorCommand(action=action, speed=speed, intensity=intensity)


# ── Vibration: PAD → haptic feedback ──────────────

def _map_vibration(p: float, a: float, d: float) -> VibrationCommand:
    """Map PAD to vibration. Gradient intensity, not binary on/off."""

    # Emotion intensity = how far from neutral
    intensity_score = (abs(p) * 0.5 + abs(a) * 0.4 + abs(d) * 0.1)

    # Gentle feedback starts at 0.2, strong at 0.6+
    if intensity_score < 0.15:
        return VibrationCommand()

    if p > 0.3 and a > 0.3:
        pattern = "double"      # joy burst
        duration = 400
    elif p < -0.3 and a < 0:
        pattern = "heartbeat"   # sadness: slow, rhythmic
        duration = 800
    elif a > 0.4:
        pattern = "pulse"       # excitement: quick tap
        duration = 250
    else:
        pattern = "steady"      # general awareness
        duration = 350

    vib_intensity = max(0.1, min(0.8, intensity_score * 0.7))

    return VibrationCommand(pattern=pattern, intensity=vib_intensity, duration_ms=duration)


# ── Public API ───────────────────────────────────

def pad_to_hardware(p: float, a: float, d: float) -> HardwareCommand:
    """Convert PAD emotion values to hardware commands.

    Args:
        p: Pleasure  -1.0 to 1.0  (happy ↔ sad)
        a: Arousal   -1.0 to 1.0  (calm ↔ excited)
        d: Dominance -1.0 to 1.0  (shy ↔ confident)

    Returns:
        HardwareCommand with led, motor, vibration instructions.
    """
    p = max(-1.0, min(1.0, p))
    a = max(-1.0, min(1.0, a))
    d = max(-1.0, min(1.0, d))

    return HardwareCommand(
        led=_map_led(p, a, d),
        motor=_map_motor(p, a, d),
        vibration=_map_vibration(p, a, d),
    )
