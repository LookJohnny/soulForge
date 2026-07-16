"""engine.legacy — Gen1 "physical AI engine" (RETIRED from active development).

This is the original flat behavior/servo stack (behavior engine, dispatcher,
physical executor, intent queue, mujoco/vtuber backends) plus its top-level
companions motion/, safety/, simulator/. It remains the only implementation
that can drive real servo hardware, so the Gen2 robot embodiment adapter
(engine/embodiment/robot_adapter.py) still executes THROUGH it.

Do NOT build new features here. The authoritative character stack is:

    engine/planner/    — three-layer planning + replanning (the brain)
    engine/server/     — Protocol 0.2 runtime server (JSON over WS)
    engine/perception/ — multi-modal perception
    engine/embodiment/ — IR -> body adapters (the only sanctioned caller)

See docs/engine_architecture.md and docs/protocol_0.2_spec.md.
"""
