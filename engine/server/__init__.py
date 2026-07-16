"""SoulForge Protocol v0 + Runtime Server.

One brain (CompanionRuntime), many bodies (Unity / web / robot / MuJoCo) over
JSON-WebSocket. See docs in engine/server/protocol.py for the wire format.
"""

from engine.server.protocol import (
    PROTOCOL_VERSION,
    ActionCommand,
    BodyHello,
    Event as WireEvent,
    Observation,
    PlanState,
    Tick,
    decode,
    encode,
)
from engine.server.capability import EmbodimentManifest
from engine.server.server import SoulForgeRuntimeServer

__all__ = [
    "PROTOCOL_VERSION",
    "ActionCommand",
    "BodyHello",
    "EmbodimentManifest",
    "Observation",
    "PlanState",
    "SoulForgeRuntimeServer",
    "Tick",
    "WireEvent",
    "decode",
    "encode",
]
