"""Protocol v0 + Runtime Server acceptance tests."""

import asyncio
import json

import pytest
import websockets

from engine.planner import MockBehaviorLLM, Persona
from engine.server import (
    ActionCommand,
    BodyHello,
    EmbodimentManifest,
    Observation,
    SoulForgeRuntimeServer,
    WireEvent,
    decode,
    encode,
)


def make_personas():
    return [
        Persona("luna", "Luna", "creative_care", relationships={"user": 0.8}),
        Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.75}),
        Persona("pipo", "Pipo", "utility_robot", relationships={"user": 0.7}),
    ]


# ---------------------------------------------------------------- protocol
def test_protocol_roundtrip():
    command = ActionCommand(
        agent_id="kai",
        name="stir_pan",
        template_id="cooking",
        adapter_command={"unity": "Anim(stir_pan)"},
        dialogue=None,
        duration_s=3.0,
        sim_minute=1152.0,
    )
    decoded = decode(encode(command))
    assert isinstance(decoded, ActionCommand)
    assert decoded.command_id == command.command_id
    assert decoded.adapter_command["unity"] == "Anim(stir_pan)"

    event = decode(
        json.dumps(
            {
                "type": "event",
                "kind": "user_utterance",
                "source": "user",
                "text": "你好",
                "future_field_from_v2": True,
            }
        )
    )
    assert isinstance(event, WireEvent)  # tolerates unknown keys
    assert event.text == "你好"

    with pytest.raises(ValueError):
        decode(json.dumps({"type": "warp_drive"}))

    with pytest.raises(ValueError):
        Observation(command_id="c1", agent_id="kai", status="cancelled")


# ---------------------------------------------------------------- capability
def test_capability_negotiation_filters_and_substitutes():
    wheeled = EmbodimentManifest(
        body_id="rover",
        backend="robot",
        supported_steps=["scan_leaves", "water_plant", "speak_line", "look_at_user"],
        supported_templates=["plant_care", "chatting", "idle"],
        features={"speech": True},
        step_substitutions={"walk_to_plants": "nav.goto plants"},
    )
    assert wheeled.accepts_step("scan_leaves")
    assert wheeled.accepts_step("walk_to_plants")  # via substitution
    assert wheeled.resolve_step("walk_to_plants") == "nav.goto plants"
    assert not wheeled.accepts_step("draw_stroke")
    assert not wheeled.accepts_template("cooking")
    assert wheeled.accepts_step("idle_breathing")  # universal
    mute = EmbodimentManifest(body_id="m", backend="web", features={"speech": False})
    assert not mute.wants_dialogue()


# ---------------------------------------------------------------- server e2e
async def _connect_body(port, body_id, agent_ids, manifest=None):
    socket = None
    for attempt in range(20):  # ride out server startup
        try:
            socket = await websockets.connect(f"ws://127.0.0.1:{port}/body")
            break
        except OSError:
            await asyncio.sleep(0.2)
    assert socket is not None, f"server on :{port} never came up"
    await socket.send(
        encode(
            BodyHello(
                body_id=body_id,
                backend="test",
                agent_ids=agent_ids,
                manifest=manifest.to_dict() if manifest else {},
            )
        )
    )
    welcome = decode(await socket.recv())
    return socket, welcome


async def _collect(socket, seconds, bucket):
    """Collect frames until a wall-clock deadline (heartbeat ticks never stop,
    so a per-frame timeout would loop forever)."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        try:
            frame = await asyncio.wait_for(
                socket.recv(), timeout=max(0.05, deadline - loop.time())
            )
            bucket.append(decode(frame))
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            break


@pytest.mark.asyncio
async def test_server_end_to_end_dispatch_event_replan_and_recovery():
    server = SoulForgeRuntimeServer(
        make_personas(),
        start_minute=19 * 60,
        time_scale=1.0,
        tick_hz=8.0,
        llm=MockBehaviorLLM(),
    )
    serve_task = asyncio.create_task(server.serve(port=0))  # ephemeral port
    await asyncio.wait_for(server.ready.wait(), timeout=5)
    port = server.bound_port

    try:
        socket, welcome = await _connect_body(port, "unity-1", ["kai", "pipo"])
        assert welcome.type == "welcome" and welcome.accepted_agents == ["kai", "pipo"]
        assert "stir_pan" in welcome.supported_steps

        frames = []
        # 1) commands flow to the body
        await _collect(socket, 0.8, frames)
        actions = [f for f in frames if isinstance(f, ActionCommand)]
        assert actions, "body must receive action commands from the tick loop"
        assert all(a.agent_id in ("kai", "pipo") for a in actions), (
            "only embodied agents"
        )

        # 2) event -> replanning broadcast with decision attached
        await socket.send(
            encode(
                WireEvent(
                    kind="user_utterance",
                    source="user",
                    text="我今天很难过",
                    target_agent="kai",
                )
            )
        )
        frames.clear()
        await _collect(socket, 1.2, frames)
        plans = [
            f
            for f in frames
            if getattr(f, "type", "") == "plan_state" and f.agent_id == "kai"
        ]
        assert plans, "plan_state must broadcast after an event"
        assert any("陪伴" in p.hour_goal for p in plans), (
            "hour rewritten to companion mode"
        )
        assert any(p.last_decision.get("impact") == "HIGH" for p in plans)

        # 3) failed observation -> recovery command from the template contract
        cooking_cmd = next((a for a in actions if a.template_id), actions[0])
        await socket.send(
            encode(
                Observation(
                    command_id=cooking_cmd.command_id,
                    agent_id=cooking_cmd.agent_id,
                    status="failed",
                    detail="joint stall",
                )
            )
        )
        frames.clear()
        await _collect(socket, 1.0, frames)
        recoveries = [
            f
            for f in frames
            if isinstance(f, ActionCommand)
            and f.params.get("recovering_from") == cooking_cmd.name
        ]
        assert recoveries, "failed observation must trigger the template recovery clip"

        await socket.close()
    finally:
        server.stop()
        await asyncio.wait_for(serve_task, timeout=5)


@pytest.mark.asyncio
async def test_capability_filtering_on_the_wire():
    server = SoulForgeRuntimeServer(
        make_personas(),
        start_minute=19 * 60,
        time_scale=1.0,
        tick_hz=8.0,
        llm=MockBehaviorLLM(),
    )
    serve_task = asyncio.create_task(server.serve(port=0))  # ephemeral port
    await asyncio.wait_for(server.ready.wait(), timeout=5)
    port = server.bound_port
    try:
        manifest = EmbodimentManifest(
            body_id="rover",
            backend="robot",
            supported_steps=["scan_leaves", "water_plant", "probe_soil", "speak_line"],
            supported_templates=["plant_care", "chatting", "idle"],
        )
        socket, welcome = await _connect_body(port, "rover", ["pipo", "kai"], manifest)
        assert "draw_stroke" not in welcome.supported_steps

        frames = []
        await _collect(socket, 1.0, frames)
        actions = [f for f in frames if isinstance(f, ActionCommand)]
        assert actions
        # kai is cooking at 19:00 but this body cannot cook -> never sees it
        assert all(a.template_id != "cooking" for a in actions)
        await socket.close()
    finally:
        server.stop()
        await asyncio.wait_for(serve_task, timeout=5)
