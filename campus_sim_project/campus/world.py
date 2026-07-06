from __future__ import annotations

from campus.agent import Agent


class World:
    """Campus world containing locations and agents."""

    def __init__(self, locations: list[str]) -> None:
        self.locations = locations
        self.agents: list[Agent] = []

    def add_agent(self, agent: Agent) -> None:
        if agent.location not in self.locations:
            raise ValueError(f"Unknown starting location: {agent.location}")
        self.agents.append(agent)

    def move_agent(self, agent: Agent, location: str) -> None:
        if location not in self.locations:
            raise ValueError(f"Unknown location: {location}")
        agent.location = location

    def get_agents_at(self, location: str) -> list[Agent]:
        return [agent for agent in self.agents if agent.location == location]
