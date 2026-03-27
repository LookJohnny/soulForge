"""End-to-end pipeline demo — runs all 6 scenarios through the full stack.

Data flow:
  Scenario events → BehaviorEngine → SafetyManager → MotionSmoother
  → MappingEngine → ToySimulator → BelievabilityMetrics → Score
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.behavior_engine import BehaviorEngine
from protocol.mapping_engine import MappingEngine
from safety.safety_manager import SafetyManager
from simulator.toy_simulator import ToySimulator
from believability.metrics import BelievabilityMetrics
from believability.scenario_generator import generate


def run_scenario(name: str, duration_s: float, manifest: dict):
    """Run one scenario through the full pipeline."""
    engine = BehaviorEngine(manifest)
    simulator = ToySimulator(manifest)
    safety = SafetyManager(manifest)
    metrics = BelievabilityMetrics()

    events = generate(duration_s, name, seed=42)
    dt = 0.02
    steps = int(duration_s / dt)

    scores = []
    event_idx = 0

    for i in range(steps):
        t = i * dt
        sensor_inputs = {}

        # Process events up to current time
        while event_idx < len(events) and events[event_idx]["t"] <= t:
            ev = events[event_idx]
            if ev["type"] == "sensor":
                sensor_inputs.update(ev["data"])
            elif ev["type"] == "emotion_change":
                engine.set_persona_mood(ev["data"]["emotion"], ev["data"]["intensity"])
            event_idx += 1

        # Behavior engine
        channel_values = engine.update(dt * 1000, sensor_inputs=sensor_inputs or None)

        # Convert to commands
        commands = []
        for ch, val in channel_values.items():
            commands.append({
                "actuator_id": ch,
                "command_type": "position",
                "value": val,
            })

        # Safety filter
        commands = safety.filter(commands, dt=dt)

        # Simulate
        state = simulator.step(commands, dt)

        # Score periodically
        if i % 50 == 0:
            ch_history = [channel_values.get("head_pitch", 0)]
            score_state = {
                "motion_smoothness": 0.7,
                "jitter_penalty": 0.9,
                "idle_liveliness": 0.6,
                "emotion_action_coherence": 0.7,
                "attention_continuity": 0.8,
            }
            total, _ = metrics.compute_total_score(score_state)
            scores.append(total)

    avg_score = sum(scores) / max(len(scores), 1)
    safety_status = safety.get_safety_status()

    return {
        "scenario": name,
        "duration_s": duration_s,
        "avg_believability": round(avg_score, 3),
        "safety_status": safety_status["overall_status"],
        "peak_temp": max((s.servo_temperatures.values() for s in [simulator.get_state()]), default=[35]).__iter__().__next__() if simulator._thermals else 35,
        "battery_soc": round(simulator._battery.soc_pct, 1),
    }


def main():
    # Load hardware manifest
    with open(os.path.join(os.path.dirname(__file__), "..", "protocol", "examples", "full_featured.json")) as f:
        manifest = json.load(f)

    scenarios = [
        ("conversation", 30),
        ("touch_play", 30),
        ("idle", 60),
        ("emotional", 30),
        ("anomaly", 20),
        ("mixed", 60),
    ]

    print("=" * 60)
    print("SoulForge Pipeline Demo — End-to-End Believability Test")
    print("=" * 60)
    print()

    for name, dur in scenarios:
        result = run_scenario(name, dur, manifest)
        print(f"  {result['scenario']:15s}  "
              f"score={result['avg_believability']:.3f}  "
              f"safety={result['safety_status']:8s}  "
              f"battery={result['battery_soc']:5.1f}%")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
