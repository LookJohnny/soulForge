"""The home as a small map: places, who is where, who can see whom.

Places come from what the behaviour templates already require (`at:kitchen`,
`at:desk`, …). Each has a floor position the web stage uses to walk bodies
around, the props that live there, and a human label. Being in the same
place is the only sense of "presence" agents have: they notice arrivals,
strike up small talk, and can be addressed only when co-present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soulforge_harness.runtime.templates import TEMPLATE_REGISTRY


@dataclass(frozen=True)
class Place:
    id: str
    label: str
    x: float
    z: float
    props: tuple[str, ...] = ()
    capacity: int = 3


HOME: dict[str, Place] = {
    "sofa": Place("sofa", "客厅沙发", 0.0, 0.3, ("blanket", "cloth")),
    "kitchen": Place("kitchen", "厨房", -1.7, -0.4, ("pan", "stove", "cloth")),
    "desk": Place("desk", "书桌", 1.5, 0.0, ("tablet", "book", "toolbox")),
    "plants": Place("plants", "阳台花架", 1.9, -1.3, ("watering_can",)),
}
DEFAULT_PLACE = "sofa"


def template_location(template_id: str | None) -> str | None:
    """Where a behaviour template has to happen (`at:` precondition), or None = anywhere."""
    template = TEMPLATE_REGISTRY.get(template_id or "")
    if template is None:
        return None
    for condition in template.preconditions:
        key, _, value = condition.partition(":")
        if key == "at" and value:
            return value
    return None


def walk_seconds(a: str, b: str, speed_mps: float = 0.9) -> float:
    pa, pb = HOME.get(a), HOME.get(b)
    if pa is None or pb is None:
        return 2.0
    dist = ((pa.x - pb.x) ** 2 + (pa.z - pb.z) ** 2) ** 0.5
    return round(max(1.0, dist / speed_mps), 1)


@dataclass
class SpaceState:
    """Per-world occupancy. Lives on WorldState so every planner sees one truth."""

    places: dict[str, Place] = field(default_factory=lambda: dict(HOME))
    agent_place: dict[str, str] = field(default_factory=dict)

    def where(self, agent_id: str) -> str:
        return self.agent_place.get(agent_id, DEFAULT_PLACE)

    def others_at(self, agent_id: str) -> list[str]:
        here = self.where(agent_id)
        return [a for a, p in self.agent_place.items() if a != agent_id and p == here]

    def co_present(self, a: str, b: str) -> bool:
        return self.where(a) == self.where(b)

    def move(self, agent_id: str, place_id: str) -> str:
        if place_id not in self.places:
            raise KeyError(place_id)
        self.agent_place[agent_id] = place_id
        return place_id

    def label(self, place_id: str) -> str:
        p = self.places.get(place_id)
        return p.label if p else place_id

    def props_at(self, place_id: str) -> list[str]:
        p = self.places.get(place_id)
        return list(p.props) if p else []

    def snapshot(self) -> dict[str, Any]:
        return {
            "places": {
                k: {"label": p.label, "x": p.x, "z": p.z, "props": list(p.props)}
                for k, p in self.places.items()
            },
            "agents": dict(self.agent_place),
        }
