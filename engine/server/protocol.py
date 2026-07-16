"""SoulForge Protocol v0 — JSON over WebSocket.

One schema drives every embodiment (Unity, browser, robot, MuJoCo, plain CLI).
Every frame on the wire is a JSON object with a `type` field:

body -> brain
  hello        body registers itself + its embodiment manifest
  observation  execution feedback for a previously dispatched command
  event        anything the body senses (user speech, sensor, robot state)

brain -> body
  welcome      registration ack (+ negotiated capabilities)
  action       one dispatchable command (template step / dialogue / gaze)
  plan_state   plan snapshot + latest decision, for HUDs and debugging
  tick         sim-clock heartbeat

JSON was chosen over protobuf for v0 so a browser, a C# client and a Python
robot bridge can all speak it with zero codegen. The dataclasses here are the
single source of truth; protobuf can mirror them in v1.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

PROTOCOL_VERSION = "0.2"

# ActionCommand.safety_class values, most to least conservative
SAFETY_CLASSES = ("safety_critical", "physical", "expressive", "virtual")
# Observation.status lifecycle
OBSERVATION_STATUSES = ("accepted", "running", "done", "failed", "interrupted", "rejected")
# ActionCommand.ack_policy
ACK_POLICIES = ("none", "on_start", "on_complete", "full")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class BodyHello:
    """body -> brain, first frame after connecting."""

    body_id: str
    backend: str                                  # "unity" | "web" | "robot" | "mujoco" | ...
    agent_ids: list[str]                          # which planner agents this body embodies
    manifest: dict[str, Any] = field(default_factory=dict)   # EmbodimentManifest.to_dict()
    protocol: str = PROTOCOL_VERSION
    type: str = "hello"


@dataclass
class ActionCommand:
    """brain -> body: the canonical Action IR (protocol 0.2).

    This is the ONLY action contract new code may depend on. Embodiment
    adapters translate it to Unity animation, robot Intents/ActionUnits, web
    animation or MuJoCo controls; the planner never emits motor angles.
    All 0.2 fields default sensibly so 0.1 peers keep decoding."""

    agent_id: str
    name: str                                     # micro-step / primitive: stir_pan, look_at_user ...
    template_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    adapter_command: dict[str, Any] = field(default_factory=dict)  # per-backend hints
    dialogue: str | None = None
    gaze_target: str | None = None
    duration_s: float = 2.0                       # expected duration
    sim_minute: float = 0.0
    command_id: str = field(default_factory=_new_id)
    # --- canonical IR envelope (0.2) ---
    protocol_version: str = PROTOCOL_VERSION
    correlation_id: str | None = None             # groups steps of one intent/plan beat
    sequence: int = 0                             # per-body monotonic, for dedupe on reconnect
    target_body: str | None = None                # None = any body embodying the agent
    priority: int = 50                            # 10 idle / 50 plan / 90 reactive
    issued_at: float = 0.0                        # sim_minute when issued
    deadline: float | None = None                 # sim_minute after which execution is pointless
    ttl_s: float = 30.0                           # wall-clock validity window
    interruptible: bool = True                    # deterministic — enforced by executors
    safety_class: str = "expressive"              # see SAFETY_CLASSES
    ack_policy: str = "on_complete"               # see ACK_POLICIES
    trace_context: dict[str, Any] = field(default_factory=dict)   # correlation for tracing
    type: str = "action"


@dataclass
class Observation:
    """body -> brain, execution feedback for a command (canonical, 0.2).

    status: accepted | running | done | failed | interrupted | rejected"""

    command_id: str
    agent_id: str
    status: str
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    # --- canonical envelope (0.2) ---
    body_id: str = ""
    started_at: float | None = None               # sim_minute
    finished_at: float | None = None
    error_code: str | None = None                 # machine-readable: E_STALL, E_TIMEOUT ...
    sensor_snapshot: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True
    type: str = "observation"

    def __post_init__(self) -> None:
        if self.status not in OBSERVATION_STATUSES:
            raise ValueError(f"unknown observation status {self.status!r}")


@dataclass
class Event:
    """body -> brain, sensed world event (mirrors planner.models.Event)."""

    kind: str                                     # user_utterance | environment | robot_state | ...
    source: str
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    target_agent: str | None = None
    type: str = "event"


@dataclass
class PlanState:
    """brain -> body/HUD, plan snapshot after a change or on request."""

    agent_id: str
    clock: str
    hour_goal: str
    activities: list[dict[str, Any]] = field(default_factory=list)
    day_blocks: list[dict[str, Any]] = field(default_factory=list)
    last_decision: dict[str, Any] = field(default_factory=dict)
    type: str = "plan_state"


@dataclass
class Tick:
    """brain -> body heartbeat with the simulated clock."""

    sim_minute: float
    clock: str
    type: str = "tick"


@dataclass
class Welcome:
    """brain -> body registration ack."""

    body_id: str
    accepted_agents: list[str]
    supported_steps: list[str]                    # after capability negotiation
    protocol: str = PROTOCOL_VERSION
    type: str = "welcome"


_TYPES = {
    "hello": BodyHello,
    "action": ActionCommand,
    "observation": Observation,
    "event": Event,
    "plan_state": PlanState,
    "tick": Tick,
    "welcome": Welcome,
}


def encode(message: Any) -> str:
    return json.dumps(asdict(message), ensure_ascii=False)


def decode(raw: str | bytes) -> Any:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"frame must be a JSON object, got {type(data).__name__}")
    kind = data.get("type")
    cls = _TYPES.get(kind)
    if cls is None:
        raise ValueError(f"unknown message type: {kind!r}")
    data.pop("type", None)
    fields = {f for f in cls.__dataclass_fields__ if f != "type"}  # tolerate extra keys
    return cls(**{k: v for k, v in data.items() if k in fields})
