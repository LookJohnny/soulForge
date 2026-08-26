"""Web (browser VRM) embodiment — Protocol 0.2 ``backend:"web"``.

The spec (docs/protocol_0.2_spec.md) always allowed a ``web`` body; this is the
first implementation. Unlike the robot adapter it is *not* fail-closed: a
virtual body may claim every step, and anything it cannot animate degrades to
an idle/gaze primitive instead of being rejected — a VRM can always at least
look at the user while "stirring the pan".

Two halves share ONE vocabulary:

* Python (this file): ``STEP_TO_WEB`` — planner micro-step → web primitive.
  Used by tests, by ``web_manifest()`` for the hello frame, and by
  ``WebEmbodimentAdapter.translate`` when a Python process (e.g. the gateway)
  relays ActionCommands to a browser instead of the browser connecting to
  ``/body`` directly.
* JS (studio/web/lib/action_map.js): the same table, consumed by
  ``body_client.js`` in the page. ``tests/test_web_embodiment.py`` pins the two
  copies together.

Primitive kinds
    clip   — play a one-shot VRMA by logical name (Goodbye, Thinking, …)
    gaze   — look at a target: user | away | down | around
    pose   — hold a procedural pose (sit, kneel, lean_back) for duration_s
    idle   — keep the idle cycle running (no-op that still acks)
    speak  — dialogue; the web body defers to the gateway voice path unless it
             was started standalone (features.speech)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.server.protocol import ActionCommand, Observation

# planner micro-steps → web primitive. Keys must match action_map.js exactly.
STEP_TO_WEB: dict[str, dict[str, Any]] = {
    # universal / attention
    "idle_breathing": {"kind": "idle"},
    "idle": {"kind": "idle"},
    "wait": {"kind": "idle"},
    "wait_for_response": {"kind": "gaze", "target": "user"},
    "resume_activity": {"kind": "idle"},
    "look_at_user": {"kind": "gaze", "target": "user"},
    "look_at_target": {"kind": "gaze", "target": "user"},
    "look_around": {"kind": "clip", "clip": "LookAround"},
    "listening_nod": {"kind": "gaze", "target": "user", "nod": True},
    "micro_nod": {"kind": "gaze", "target": "user", "nod": True},
    "speak_line": {"kind": "speak"},
    "chatting": {"kind": "gaze", "target": "user"},
    "invite_user": {"kind": "clip", "clip": "Goodbye"},
    "report": {"kind": "gaze", "target": "user", "nod": True},
    "plate_up": {"kind": "pose", "pose": "busy_hands"},
    # gestures / performances
    "wave": {"kind": "clip", "clip": "Goodbye"},
    "greet": {"kind": "clip", "clip": "Goodbye"},
    "celebrate": {"kind": "clip", "clip": "Clapping"},
    "clap": {"kind": "clip", "clip": "Clapping"},
    "jump": {"kind": "clip", "clip": "Jump"},
    "think": {"kind": "clip", "clip": "Thinking"},
    "stretch": {"kind": "clip", "clip": "Relax"},
    "rest": {"kind": "clip", "clip": "Relax"},
    "sleepy": {"kind": "clip", "clip": "Sleepy"},
    "surprised": {"kind": "clip", "clip": "Surprised"},
    "sad": {"kind": "clip", "clip": "Sad"},
    "angry": {"kind": "clip", "clip": "Angry"},
    "blush": {"kind": "clip", "clip": "Blush"},
    # activity steps: a VRM in a bare studio has no props — hold a pose or gaze
    "stir_pan": {"kind": "pose", "pose": "busy_hands"},
    "prep_ingredients": {"kind": "pose", "pose": "busy_hands"},
    "draw_stroke": {"kind": "pose", "pose": "busy_hands"},
    "take_note": {"kind": "pose", "pose": "busy_hands"},
    "read_page": {"kind": "gaze", "target": "down"},
    "study": {"kind": "gaze", "target": "down"},
    "lean_back_review": {"kind": "pose", "pose": "lean_back"},
    "sit_desk": {"kind": "pose", "pose": "sit"},
    "sit_sofa": {"kind": "pose", "pose": "sit"},
    "kneel_inspect": {"kind": "pose", "pose": "kneel"},
    "scan_leaves": {"kind": "gaze", "target": "around"},
    "probe_soil": {"kind": "gaze", "target": "down"},
    "water_plant": {"kind": "pose", "pose": "busy_hands"},
    "wipe_surface": {"kind": "pose", "pose": "busy_hands"},
    "pick_item": {"kind": "pose", "pose": "busy_hands"},
    "place_item": {"kind": "pose", "pose": "busy_hands"},
    "pack_tools": {"kind": "pose", "pose": "busy_hands"},
    "test_part": {"kind": "pose", "pose": "busy_hands"},
    "turn_wrench": {"kind": "pose", "pose": "busy_hands"},
    "adjust_pose": {"kind": "idle"},
    "cleaning": {"kind": "pose", "pose": "busy_hands"},
    # navigation: no locomotion in the studio → glance the way it would walk
    "walk_to_kitchen": {"kind": "gaze", "target": "away"},
    "walk_to_plants": {"kind": "gaze", "target": "away"},
    "walk_to_sofa": {"kind": "gaze", "target": "away"},
    "walk_to_zone": {"kind": "gaze", "target": "away"},
    "approach_user": {"kind": "gaze", "target": "user"},
    # safety (expressive body: nothing physical to stop)
    "safe_stop": {"kind": "idle"},
    "hold_safe_breakpoint": {"kind": "idle"},
}

# Performances a decision may request via params.performance (studio legacy)
PERFORMANCE_TO_CLIP: dict[str, str] = {
    "wave": "Goodbye",
    "stretch": "Relax",
    "clap": "Clapping",
    "jump": "Jump",
    "think": "Thinking",
    "look_around": "LookAround",
    "bow": "Goodbye",
    "dance": "Jump",
    "spin": "Jump",
}

WEB_FEATURES = {"speech": False, "gaze": True, "nav": False, "props": False}


def web_manifest(body_id: str = "web-vrm", *, speech: bool = False) -> dict:
    """Hello-frame manifest: claim the whole table (virtual bodies may)."""
    return {
        "body_id": body_id,
        "backend": "web",
        "supported_steps": sorted(STEP_TO_WEB),
        "supported_templates": [],
        "features": {**WEB_FEATURES, "speech": speech},
        "step_substitutions": {},
    }


def translate(command: ActionCommand) -> dict[str, Any]:
    """ActionCommand → web primitive dict (never raises, never rejects)."""
    perf = (command.params or {}).get("performance")
    if perf and perf in PERFORMANCE_TO_CLIP:
        prim: dict[str, Any] = {"kind": "clip", "clip": PERFORMANCE_TO_CLIP[perf]}
    else:
        prim = dict(STEP_TO_WEB.get(command.name) or {"kind": "gaze", "target": "user"})
    if command.gaze_target and prim["kind"] in ("idle", "pose"):
        prim["gaze"] = "user" if command.gaze_target == "user" else "around"
    prim.update(
        {
            "command_id": command.command_id,
            "agent_id": command.agent_id,
            "step": command.name,
            "duration_s": float(command.duration_s or 2.0),
            "interruptible": bool(command.interruptible),
            "dialogue": command.dialogue,
            "mapped": command.name in STEP_TO_WEB or bool(perf),
        }
    )
    return prim


@dataclass
class WebEmbodimentAdapter:
    """Python-side relay: translate commands, track them, emit observations.

    ``send`` is any callable that ships a dict to the browser (gateway control
    frame, WS send, test list …).
    """

    send: Any
    body_id: str = "web-vrm"
    inflight: dict[str, dict[str, Any]] = field(default_factory=dict)

    def dispatch(self, command: ActionCommand) -> Observation:
        prim = translate(command)
        self.inflight[command.command_id] = prim
        self.send({"type": "body_action", **prim})
        return Observation(
            command_id=command.command_id,
            agent_id=command.agent_id,
            status="accepted",
            body_id=self.body_id,
            detail=f"web:{prim['kind']}",
            payload={"mapped": prim["mapped"], "primitive": prim["kind"]},
        )

    def complete(
        self, command_id: str, *, ok: bool = True, detail: str = ""
    ) -> Observation | None:
        prim = self.inflight.pop(command_id, None)
        if prim is None:
            return None
        return Observation(
            command_id=command_id,
            agent_id=prim["agent_id"],
            status="done" if ok else "failed",
            body_id=self.body_id,
            detail=detail,
            error_code=None if ok else "E_WEB_ANIM",
        )

    def interrupt_all(self) -> list[Observation]:
        out = []
        for cid, prim in list(self.inflight.items()):
            out.append(
                Observation(
                    command_id=cid,
                    agent_id=prim["agent_id"],
                    status="interrupted",
                    body_id=self.body_id,
                )
            )
        self.inflight.clear()
        return out
