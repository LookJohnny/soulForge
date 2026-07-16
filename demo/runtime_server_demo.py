"""Live demo of Protocol v0: brain server + a fake embodiment over WebSocket.

Spawns SoulForgeRuntimeServer in-process, connects a wheeled-robot body that
embodies Pipo+Kai, then walks the full loop:

  1. registration + capability negotiation (robot can't cook or draw)
  2. action commands streaming in real time
  3. a user interruption event -> HIGH replan broadcast (plan_state)
  4. a failed execution observation -> template recovery command

Run:  uv run python demo/runtime_server_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

from engine.planner import MockBehaviorLLM, Persona
from engine.server import (
    ActionCommand, BodyHello, EmbodimentManifest, Observation,
    SoulForgeRuntimeServer, WireEvent, decode, encode,
)

PORT = 8777


async def fake_robot_body() -> None:
    manifest = EmbodimentManifest(
        body_id="rover-01", backend="robot",
        supported_steps=["scan_leaves", "probe_soil", "water_plant", "speak_line",
                         "look_at_user", "stir_pan", "prep_ingredients", "plate_up"],
        supported_templates=["plant_care", "cooking", "chatting", "rest", "idle"],
        features={"speech": True, "nav": True},
        step_substitutions={"walk_to_plants": "nav.goto plants",
                            "walk_to_kitchen": "nav.goto kitchen"},
    )
    socket = None
    for _ in range(20):
        try:
            socket = await websockets.connect(f"ws://127.0.0.1:{PORT}/body")
            break
        except OSError:
            await asyncio.sleep(0.2)
    assert socket

    await socket.send(encode(BodyHello(body_id="rover-01", backend="robot",
                                       agent_ids=["pipo", "kai"],
                                       manifest=manifest.to_dict())))
    welcome = decode(await socket.recv())
    print(f"\n[body] registered. negotiated steps: {', '.join(welcome.supported_steps[:8])} …")

    first_command: ActionCommand | None = None
    event_sent = False
    failure_sent = False
    deadline = asyncio.get_event_loop().time() + 8.0

    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = decode(await asyncio.wait_for(socket.recv(), timeout=1.0))
        except asyncio.TimeoutError:
            continue
        kind = getattr(frame, "type", "?")
        if isinstance(frame, ActionCommand):
            print(f"[body] <- action  {frame.agent_id:>4} {frame.name:<18} "
                  f"template={frame.template_id or '-':<10} adapter={frame.adapter_command.get('robot', frame.adapter_command.get('unity', '-'))}"
                  + (f'  说:"{frame.dialogue}"' if frame.dialogue else ""))
            if first_command is None and frame.template_id:
                first_command = frame
            if not failure_sent and event_sent and frame.template_id:
                failure_sent = True
                print(f"[body] -> observation FAILED for {frame.name} (joint stall)")
                await socket.send(encode(Observation(command_id=frame.command_id,
                                                     agent_id=frame.agent_id,
                                                     status="failed",
                                                     detail="joint stall")))
        elif kind == "plan_state":
            decision = frame.last_decision or {}
            print(f"[body] <- plan   {frame.agent_id:>4} goal={frame.hour_goal!r}"
                  + (f"  decision=[{decision.get('impact')}] {decision.get('reason', '')[:40]}"
                     if decision else ""))
        elif kind == "tick" and not event_sent and asyncio.get_event_loop().time() > deadline - 6.0:
            event_sent = True
            print('\n[body] -> event  用户: "我今天有点累……"\n')
            await socket.send(encode(WireEvent(kind="user_utterance", source="user",
                                               text="我今天有点累……", target_agent="kai")))
    await socket.close()


async def main() -> None:
    personas = [
        Persona("luna", "Luna", "creative_care", relationships={"user": 0.8}),
        Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.75}),
        Persona("pipo", "Pipo", "utility_robot", relationships={"user": 0.7}),
    ]
    server = SoulForgeRuntimeServer(personas, start_minute=19 * 60,
                                    time_scale=2.0, tick_hz=1.0, llm=MockBehaviorLLM())
    serve_task = asyncio.create_task(server.serve(port=PORT))
    try:
        await fake_robot_body()
    finally:
        server.stop()
        await asyncio.wait_for(serve_task, timeout=5)
    print("\ndemo complete: registration → streaming actions → interruption replan → failure recovery")


if __name__ == "__main__":
    asyncio.run(main())
