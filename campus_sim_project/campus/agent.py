from __future__ import annotations

from collections import Counter

from campus.memory import MemoryStream


class Agent:
    """A lightweight student agent with goals, memory, and relationships."""

    def __init__(self, name: str, personality: str, goals: list[str], location: str) -> None:
        self.name = name
        self.personality = personality
        self.goals = goals
        self.location = location
        self.memory = MemoryStream()
        self.plan = []
        self.relationships: dict[str, int] = {}
        self.known_events: set[str] = set()
        self.reflections: list[str] = []

    def remember(self, time: str, description: str, importance: int = 5, tags: list[str] | None = None) -> None:
        self.memory.add(time, description, importance, tags or [])

    def reflect(self) -> list[str]:
        """Create simple high-level reflections from repeated memory tags."""
        tag_counts: Counter[str] = Counter()
        for memory in self.memory.items:
            tag_counts.update(tag.lower() for tag in memory.tags)

        new_reflections: list[str] = []
        if tag_counts["exam"] >= 2:
            new_reflections.append("Bob may be stressed about the upcoming exam.")
        if tag_counts["event"] >= 2 or tag_counts["game"] >= 2:
            new_reflections.append("Campus events are becoming socially important.")
        if tag_counts["cathy"] >= 2:
            new_reflections.append("Cathy is likely to help spread campus news.")

        for reflection in new_reflections:
            if reflection not in self.reflections:
                self.reflections.append(reflection)
                self.memory.add(
                    time="reflection",
                    description=f"Reflection: {reflection}",
                    importance=8,
                    tags=["reflection"],
                )

        return new_reflections

    def choose_invitee(self, candidates: list[Agent]) -> Agent | None:
        if not candidates:
            return None
        return max(candidates, key=lambda agent: self.relationships.get(agent.name, 0))
