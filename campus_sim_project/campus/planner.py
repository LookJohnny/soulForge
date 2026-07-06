from __future__ import annotations

from dataclasses import dataclass

from campus.agent import Agent


@dataclass(frozen=True)
class PlanStep:
    time: str
    action: str
    location: str


class Planner:
    """Rule-based daily planner for student agents."""

    def generate_daily_plan(self, agent: Agent, day: str) -> list[PlanStep]:
        plan = [
            PlanStep("08:00", "go_to", "Cafeteria"),
            PlanStep("09:00", "go_to", "Classroom"),
            PlanStep("12:00", "go_to", "Cafeteria"),
        ]

        goals_text = " ".join(agent.goals).lower()
        personality = agent.personality.lower()

        if "study" in goals_text or "exam" in goals_text or "hardworking" in personality:
            plan.append(PlanStep("14:00", "go_to", "Library"))
        else:
            plan.append(PlanStep("14:00", "go_to", "Quad"))

        if day.lower() == "friday" and "Game Night" in agent.known_events:
            plan.append(PlanStep("19:00", "go_to", "Quad"))
        elif "social" in personality or "event" in goals_text:
            plan.append(PlanStep("19:00", "go_to", "Cafeteria"))
        else:
            plan.append(PlanStep("19:00", "go_to", "Dorm"))

        agent.plan = plan
        return plan
