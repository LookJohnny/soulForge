from __future__ import annotations

import random

from campus.agent import Agent
from campus.conversation import Conversation
from campus.planner import Planner
from campus.world import World


class Simulation:
    """End-to-end campus simulation loop."""

    def __init__(self, random_seed: int | None = None) -> None:
        self.random = random.Random(random_seed)
        self.world = World(["Dorm", "Cafeteria", "Library", "Classroom", "Quad"])
        self.planner = Planner()
        self.conversation = Conversation(random_seed=random_seed)
        self.logs: list[str] = []

    @property
    def agents(self) -> list[Agent]:
        return self.world.agents

    def add_default_agents(self) -> None:
        alice = Agent("Alice", "organized, friendly, likes board games", ["organize Game Night"], "Dorm")
        bob = Agent("Bob", "shy, hardworking", ["study for AI exam", "make one new friend"], "Dorm")
        cathy = Agent("Cathy", "social, energetic", ["attend campus activities"], "Dorm")

        alice.relationships = {"Bob": 5, "Cathy": 8}
        bob.relationships = {"Alice": 5, "Cathy": 4}
        cathy.relationships = {"Alice": 8, "Bob": 4}

        for agent in [alice, bob, cathy]:
            self.world.add_agent(agent)

    def get_agent(self, name: str) -> Agent:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise ValueError(f"Unknown agent: {name}")

    def run(self, days: int = 1) -> None:
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        for day_index in range(days):
            day = day_names[day_index % len(day_names)]
            self._run_day(day, day_index + 1)

    def _run_day(self, day: str, day_number: int) -> None:
        for agent in self.agents:
            self.planner.generate_daily_plan(agent, day)

        time_slots = ["08:00", "09:00", "12:00", "14:00", "19:00"]
        for time_slot in time_slots:
            label = f"Day{day_number} {time_slot}"
            for agent in self.agents:
                step = next((item for item in agent.plan if item.time == time_slot), None)
                if step:
                    old_location = agent.location
                    self.world.move_agent(agent, step.location)
                    line = f"{label}: {agent.name} moved from {old_location} to {step.location}."
                    agent.remember(label, line, 4, [agent.name, step.location, "move"])
                    self.logs.append(line)

            self._run_location_conversations(label)

        for agent in self.agents:
            agent.reflect()

    def _run_location_conversations(self, time: str) -> None:
        for location in self.world.locations:
            agents_here = self.world.get_agents_at(location)
            if len(agents_here) >= 2:
                self.random.shuffle(agents_here)
                for first, second in zip(agents_here, agents_here[1:]):
                    logs = self.conversation.run(first, second, time)
                    self.logs.extend(f"{time}: {line}" for line in logs)
