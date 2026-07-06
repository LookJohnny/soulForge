from campus.agent import Agent
from campus.planner import Planner


def test_planner_sends_studious_agent_to_library():
    bob = Agent(
        name="Bob",
        personality="hardworking",
        goals=["study for AI exam"],
        location="Dorm",
    )

    planner = Planner()
    plan = planner.generate_daily_plan(bob, day="Monday")

    locations = [step.location for step in plan]

    assert "Library" in locations


def test_planner_adds_known_event_to_schedule():
    cathy = Agent(
        name="Cathy",
        personality="social",
        goals=["attend campus activities"],
        location="Dorm",
    )
    cathy.known_events.add("Game Night")

    planner = Planner()
    plan = planner.generate_daily_plan(cathy, day="Friday")

    evening_steps = [step for step in plan if step.time in ["18:00", "19:00", "20:00"]]

    assert any(step.location == "Quad" for step in evening_steps)
