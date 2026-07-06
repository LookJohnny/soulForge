# CampusSim: Generative Agents Campus Project

A small PyCharm-ready Python project inspired by **Generative Agents: Interactive Simulacra of Human Behavior**.

The project simulates a tiny campus where student agents observe the world, store memories, retrieve relevant memories, reflect on repeated themes, plan their day, talk to each other, and spread event information such as **Game Night**.

## Project Structure

```text
campus_sim_project/
├── main.py
├── requirements.txt
├── campus/
│   ├── __init__.py
│   ├── agent.py
│   ├── conversation.py
│   ├── memory.py
│   ├── planner.py
│   ├── simulation.py
│   └── world.py
└── tests/
    ├── test_conversation.py
    ├── test_memory.py
    ├── test_planner.py
    └── test_simulation.py
```

## Open in PyCharm

1. Open PyCharm.
2. Choose **Open**.
3. Select the `campus_sim_project` folder.
4. Configure a Python interpreter.
5. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the simulation

```bash
python main.py
```

## Run tests

```bash
pytest
```

## Suggested Assignment Tasks

- Add more agents with different personalities.
- Add new campus locations.
- Improve memory retrieval scoring.
- Make reflection influence future plans.
- Add a simple web UI or map visualization.
- Compare simulation behavior with and without memory/reflection.
