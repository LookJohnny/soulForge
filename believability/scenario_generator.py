"""Scenario Generator — creates training scenarios for RL.

Generates time-ordered event sequences for 5 scenario types:
  1. conversation — dialog exchange with emotion shifts
  2. touch_play — continuous touch interaction
  3. idle — long period with no input (tests idle liveliness)
  4. emotional — gradual emotion transitions
  5. anomaly — sudden loud noise, shake, drop
"""

from __future__ import annotations

import random
import math


def generate(duration_s: float = 60.0, scenario_type: str = "mixed",
             seed: int | None = None) -> list[dict]:
    """Generate a time-sorted event sequence.

    Returns:
        [{"t": float, "type": str, "data": dict}, ...]
    """
    if seed is not None:
        random.seed(seed)

    if scenario_type == "mixed":
        # Mix of all types
        events = []
        segment = duration_s / 5
        events.extend(_gen_conversation(0, segment))
        events.extend(_gen_touch_play(segment, segment))
        events.extend(_gen_idle(segment * 2, segment))
        events.extend(_gen_emotional(segment * 3, segment))
        events.extend(_gen_anomaly(segment * 4, segment))
        events.sort(key=lambda e: e["t"])
        return events

    generators = {
        "conversation": _gen_conversation,
        "touch_play": _gen_touch_play,
        "idle": _gen_idle,
        "emotional": _gen_emotional,
        "anomaly": _gen_anomaly,
    }

    gen = generators.get(scenario_type, _gen_conversation)
    return gen(0, duration_s)


def _gen_conversation(start: float, duration: float) -> list[dict]:
    events = []
    t = start
    emotions = [1, 7, 8, 0, 3]  # JOY, CURIOSITY, AFFECTION, NEUTRAL, SURPRISE

    while t < start + duration:
        # User speaks
        events.append({"t": round(t, 2), "type": "speech", "data": {
            "text": random.choice(["你好", "讲个故事", "今天心情怎么样", "你喜欢什么"]),
            "phonemes": [],
        }})
        t += random.uniform(0.5, 1.5)

        # Emotion shift after response
        events.append({"t": round(t, 2), "type": "emotion_change", "data": {
            "emotion": random.choice(emotions),
            "intensity": round(random.uniform(0.3, 0.9), 2),
        }})
        t += random.uniform(2.0, 5.0)

    return events


def _gen_touch_play(start: float, duration: float) -> list[dict]:
    events = []
    t = start
    sensors = ["touch_head", "touch_belly", "touch_hand"]

    while t < start + duration:
        events.append({"t": round(t, 2), "type": "sensor", "data": {
            random.choice(sensors): round(random.uniform(0.5, 1.0), 2),
        }})
        t += random.uniform(0.5, 3.0)

    return events


def _gen_idle(start: float, duration: float) -> list[dict]:
    """Long idle period — only start/end markers."""
    return [
        {"t": round(start, 2), "type": "idle_start", "data": {}},
        {"t": round(start + duration, 2), "type": "idle_end", "data": {}},
    ]


def _gen_emotional(start: float, duration: float) -> list[dict]:
    events = []
    t = start
    # Gradual emotion arc: neutral → joy → surprise → sadness → calm
    arc = [(0, 0.3), (1, 0.5), (1, 0.8), (3, 0.7), (2, 0.6), (0, 0.3)]

    for i, (emo, intensity) in enumerate(arc):
        et = start + (i / len(arc)) * duration
        events.append({"t": round(et, 2), "type": "emotion_change", "data": {
            "emotion": emo, "intensity": intensity,
        }})

    return events


def _gen_anomaly(start: float, duration: float) -> list[dict]:
    events = []
    t = start + random.uniform(1, duration * 0.3)

    # Loud noise
    events.append({"t": round(t, 2), "type": "sensor", "data": {"loud_noise": 0.9}})
    t += random.uniform(3, 8)

    # Shake
    if t < start + duration:
        events.append({"t": round(t, 2), "type": "sensor", "data": {"imu_shake": 3.0}})
        t += random.uniform(2, 5)

    # Pick up
    if t < start + duration:
        events.append({"t": round(t, 2), "type": "sensor", "data": {"imu_freefall": 1.0}})

    return events
