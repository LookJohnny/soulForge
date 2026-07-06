from campus.simulation import Simulation


def main() -> None:
    sim = Simulation(random_seed=42)
    sim.add_default_agents()
    sim.get_agent("Alice").known_events.add("Game Night")
    sim.run(days=5)

    print("=== CampusSim Logs ===")
    for log in sim.logs:
        print(log)

    print("\n=== Final Agent States ===")
    for agent in sim.agents:
        events = ", ".join(sorted(agent.known_events)) or "none"
        print(f"{agent.name} knows: {events}")
        if agent.reflections:
            for reflection in agent.reflections:
                print(f"  Reflection: {reflection}")


if __name__ == "__main__":
    main()
