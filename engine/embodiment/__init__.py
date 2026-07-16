"""Embodiment Runtimes: translate canonical Action IR into concrete bodies.

The Character Core never emits motor angles; adapters here own that boundary.
"""

from engine.embodiment.robot_adapter import (
    FaultInjectionBackend,
    RobotEmbodimentAdapter,
    STEP_TO_ROBOT_TEMPLATE,
)
from engine.embodiment.hal import ActuatorHAL, HALBackend

__all__ = [
    "ActuatorHAL",
    "FaultInjectionBackend",
    "HALBackend",
    "RobotEmbodimentAdapter",
    "STEP_TO_ROBOT_TEMPLATE",
]
