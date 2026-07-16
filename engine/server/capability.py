"""Embodiment manifests and capability negotiation.

A body declares what it can physically do; the server filters or degrades
commands so the planner never asks a wheeled robot to "walk" or a screenless
device to render a sketch pad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.planner.templates import TEMPLATE_REGISTRY

# micro-steps every body gets for free (pure timing/no-op on minimal hardware)
_UNIVERSAL_STEPS = {"idle_breathing", "wait", "look_around", "resume_activity",
                    "pause_template", "resume_template", "stop_current_activity",
                    "abort_all_templates", "report"}


@dataclass
class EmbodimentManifest:
    body_id: str
    backend: str
    supported_steps: list[str] = field(default_factory=list)   # micro-step names
    supported_templates: list[str] = field(default_factory=list)
    features: dict[str, bool] = field(default_factory=dict)    # speech, gaze, nav, arms ...
    step_substitutions: dict[str, str] = field(default_factory=dict)  # walk_to_kitchen -> nav.goto

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_id": self.body_id,
            "backend": self.backend,
            "supported_steps": self.supported_steps,
            "supported_templates": self.supported_templates,
            "features": self.features,
            "step_substitutions": self.step_substitutions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbodimentManifest":
        return cls(
            body_id=data.get("body_id", "anonymous"),
            backend=data.get("backend", "unknown"),
            supported_steps=list(data.get("supported_steps", [])),
            supported_templates=list(data.get("supported_templates", [])),
            features={k: bool(v) for k, v in data.get("features", {}).items()},
            step_substitutions=dict(data.get("step_substitutions", {})),
        )

    def is_fail_closed(self) -> bool:
        """Real hardware never gets implicit capabilities."""
        return self.backend in ("robot", "hardware")

    # -- negotiation -------------------------------------------------------
    def accepts_step(self, step_name: str) -> bool:
        if self.features.get("speech_only", False):
            return step_name in self.supported_steps
        if step_name in _UNIVERSAL_STEPS:
            return True
        if not self.supported_steps:
            # virtual bodies may claim everything; physical robots FAIL CLOSED —
            # an empty manifest means "can do nothing beyond universal steps"
            return not self.is_fail_closed()
        if step_name in self.supported_steps or step_name in self.step_substitutions:
            return True
        # accepting a template implies accepting its recovery clip
        return any(
            TEMPLATE_REGISTRY[t].recovery == step_name
            for t in (self.supported_templates or TEMPLATE_REGISTRY)
            if t in TEMPLATE_REGISTRY
        )

    def resolve_step(self, step_name: str) -> str:
        """Substitute a step the body implements differently (walk -> wheel nav)."""
        return self.step_substitutions.get(step_name, step_name)

    def accepts_template(self, template_id: str | None) -> bool:
        if template_id is None:
            return True
        if not self.supported_templates:
            # physical robots: only the do-nothing template without explicit claims
            return template_id == "idle" if self.is_fail_closed() else True
        return template_id in self.supported_templates

    def wants_dialogue(self) -> bool:
        return self.features.get("speech", True)

    def negotiated_steps(self) -> list[str]:
        """Full step vocabulary this body will receive, for the welcome frame."""
        known: set[str] = set(_UNIVERSAL_STEPS)
        for template in TEMPLATE_REGISTRY.values():
            for step in template.micro_steps:
                if self.accepts_step(step):
                    known.add(self.resolve_step(step))
        extra = {"look_at_user", "speak_line", "approach_user"}
        known.update(s for s in extra if self.accepts_step(s))
        return sorted(known)
