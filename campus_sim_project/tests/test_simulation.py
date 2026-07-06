import pytest

from campus.agent import Agent
from campus.simulation import Simulation
from campus.world import World


def test_agent_can_move_between_locations():
    world = World(locations=["Dorm", "Library"])
    alice = Agent(name="Alice", personality="friendly", goals=[], location="Dorm")

    world.add_agent(alice)
    world.move_agent(alice, "Library")

    assert alice.location == "Library"
    assert alice in world.get_agents_at("Library")


def test_agent_cannot_move_to_unknown_location():
    world = World(locations=["Dorm", "Library"])
    alice = Agent(name="Alice", personality="friendly", goals=[], location="Dorm")

    world.add_agent(alice)

    with pytest.raises(ValueError):
        world.move_agent(alice, "Mars")


def test_reflection_summarizes_repeated_theme():
    alice = Agent("Alice", "observant", [], "Dorm")

    alice.memory.add("Day1 09:00", "Bob said he is worried about the AI exam.", 7, ["Bob", "exam", "worried"])
    alice.memory.add("Day1 10:00", "Bob went to the library to study for the exam.", 6, ["Bob", "exam", "study"])
    alice.memory.add("Day1 11:00", "Bob skipped lunch because of exam preparation.", 6, ["Bob", "exam", "stress"])

    reflections = alice.reflect()

    assert any("Bob" in reflection and "exam" in reflection for reflection in reflections)


def test_simulation_event_spreads_to_multiple_agents():
    sim = Simulation(random_seed=42)

    sim.add_default_agents()
    sim.get_agent("Alice").known_events.add("Game Night")

    sim.run(days=1)

    agents_who_know = [
        agent.name for agent in sim.agents
        if "Game Night" in agent.known_events
    ]

    assert len(agents_who_know) >= 2


def test_simulation_generates_logs():
    sim = Simulation(random_seed=42)
    sim.add_default_agents()

    sim.run(days=1)

    assert len(sim.logs) > 0
    assert any("moved" in log or "talked" in log or "told" in log for log in sim.logs)


def test_different_random_seeds_create_different_logs():
    sim1 = Simulation(random_seed=1)
    sim1.add_default_agents()
    sim1.run(days=1)

    sim2 = Simulation(random_seed=2)
    sim2.add_default_agents()
    sim2.run(days=1)

    assert sim1.logs != sim2.logs
