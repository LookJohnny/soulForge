"""Phase-1/2 server acceptance: reconnection, forgery, scoping, IR compat."""

import asyncio
import json
import time

import pytest
import websockets

from engine.planner import MockBehaviorLLM, Persona
from engine.server import (
    ActionCommand, BodyHello, EmbodimentManifest, Observation,
    SoulForgeRuntimeServer, WireEvent, decode, encode,
)
from engine.server.protocol import PROTOCOL_VERSION


def personas():
    return [
        Persona("luna", "Luna", "creative_care", relationships={"user": 0.8}),
        Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.75}),
    ]


async def start_server(**kwargs):
    server = SoulForgeRuntimeServer(
        personas(), start_minute=19 * 60, time_scale=1.0, tick_hz=8.0,
        llm=kwargs.pop("llm", MockBehaviorLLM()), **kwargs)
    task = asyncio.create_task(server.serve(port=0))
    await asyncio.wait_for(server.ready.wait(), timeout=5)
    return server, task


async def connect_body(port, body_id, agent_ids, manifest=None, backend="test"):
    socket = await websockets.connect(f"ws://127.0.0.1:{port}/body")
    await socket.send(encode(BodyHello(body_id=body_id, backend=backend,
                                       agent_ids=agent_ids,
                                       manifest=manifest.to_dict() if manifest else {})))
    welcome = decode(await socket.recv())
    return socket, welcome


async def collect(socket, seconds):
    frames = []
    loop = asyncio.get_event_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        try:
            frames.append(decode(await asyncio.wait_for(
                socket.recv(), timeout=max(0.05, deadline - loop.time()))))
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            break
    return frames


# ------------------------------------------------------------- param validation
def test_server_rejects_invalid_parameters():
    for bad in ({"tick_hz": 0}, {"tick_hz": -1}, {"tick_hz": float("nan")},
                {"time_scale": 0}, {"time_scale": float("inf")},
                {"start_minute": float("nan")}, {"start_minute": -5}):
        with pytest.raises(ValueError):
            SoulForgeRuntimeServer(personas(), llm=MockBehaviorLLM(), **bad)


# ---------------------------------------------------------------- reconnection
@pytest.mark.asyncio
async def test_same_body_id_reconnect_replaces_old_connection():
    server, task = await start_server()
    try:
        first, _ = await connect_body(server.bound_port, "unity-1", ["kai"])
        second, welcome = await connect_body(server.bound_port, "unity-1", ["kai"])
        assert welcome.accepted_agents == ["kai"]
        await asyncio.sleep(0.4)                      # let the old socket teardown run
        assert "unity-1" in server.bodies
        assert server.bodies["unity-1"].socket is not first
        # the NEW connection still receives commands after the old one died
        frames = await collect(second, 0.6)
        assert any(isinstance(f, ActionCommand) for f in frames)
        await second.close()
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=5)


# -------------------------------------------------------- observation forgery
@pytest.mark.asyncio
async def test_forged_agent_observation_is_rejected():
    server, task = await start_server()
    try:
        socket, _ = await connect_body(server.bound_port, "b1", ["kai", "luna"])
        frames = await collect(socket, 0.7)
        command = next(f for f in frames if isinstance(f, ActionCommand)
                       and f.template_id and f.agent_id == "kai")
        # forge: claim the receipt belongs to luna
        await socket.send(encode(Observation(command_id=command.command_id,
                                             agent_id="luna", status="failed",
                                             detail="forged", body_id="b1")))
        await asyncio.sleep(0.5)
        rejected = [t for t in server.runtime.trace if t.kind == "observation_rejected"]
        assert any(t.detail.get("reason") == "agent_id mismatch" for t in rejected)
        # and no recovery was issued for luna
        recoveries = [t for t in server.runtime.trace if t.kind == "plan_change"
                      and t.detail.get("level") == "recovery"]
        assert not any(t.agent_id == "luna" for t in recoveries)
        await socket.close()
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=5)


# ----------------------------------------------------------- plan_state scoping
@pytest.mark.asyncio
async def test_plan_state_only_reaches_subscribed_bodies():
    server, task = await start_server()
    try:
        kai_only, _ = await connect_body(server.bound_port, "kai-body", ["kai"])
        both, _ = await connect_body(server.bound_port, "hud", ["kai", "luna"])
        await both.send(encode(WireEvent(kind="user_utterance", source="user",
                                         text="我今天很难过", target_agent="luna")))
        kai_frames, both_frames = await asyncio.gather(
            collect(kai_only, 1.2), collect(both, 1.2))
        kai_plans = [f for f in kai_frames if getattr(f, "type", "") == "plan_state"]
        assert kai_plans and all(p.agent_id == "kai" for p in kai_plans), \
            "a body subscribed to kai must never receive luna's plan_state"
        both_agents = {f.agent_id for f in both_frames
                       if getattr(f, "type", "") == "plan_state"}
        assert "luna" in both_agents
        # per-agent last_decision isolation: kai snapshots never carry luna's decision
        for p in kai_plans:
            assert "难过" not in json.dumps(p.last_decision, ensure_ascii=False)
        await kai_only.close(); await both.close()
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=5)


# ------------------------------------------------- two bodies, independent acks
@pytest.mark.asyncio
async def test_two_bodies_same_agent_receive_filtered_streams_and_ack_independently():
    server, task = await start_server()
    try:
        web, w1 = await connect_body(server.bound_port, "web-1", ["kai"])
        robot_manifest = EmbodimentManifest(
            body_id="rover", backend="robot",
            supported_steps=["stir_pan", "prep_ingredients", "plate_up", "speak_line"],
            supported_templates=["cooking", "idle"])
        robot, w2 = await connect_body(server.bound_port, "rover", ["kai"],
                                       robot_manifest, backend="robot")
        web_frames, robot_frames = await asyncio.gather(
            collect(web, 0.8), collect(robot, 0.8))
        web_cmds = [f for f in web_frames if isinstance(f, ActionCommand)]
        robot_cmds = [f for f in robot_frames if isinstance(f, ActionCommand)]
        assert web_cmds and robot_cmds
        # sequences are per-body monotonic
        assert [c.sequence for c in robot_cmds] == sorted(c.sequence for c in robot_cmds)
        assert robot_cmds[0].target_body == "rover"
        assert all(c.safety_class == "physical" for c in robot_cmds)
        # independent acks: each body acks its own command_id
        await web.send(encode(Observation(command_id=web_cmds[0].command_id,
                                          agent_id="kai", status="done", body_id="web-1")))
        await robot.send(encode(Observation(command_id=robot_cmds[0].command_id,
                                            agent_id="kai", status="done", body_id="rover")))
        await asyncio.sleep(0.4)
        observed = [t for t in server.runtime.trace if t.kind == "observation"]
        assert len(observed) >= 2
        await web.close(); await robot.close()
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=5)


# ------------------------------------------------------------ garbage & robot FC
@pytest.mark.asyncio
async def test_garbage_frames_do_not_kill_connection():
    server, task = await start_server()
    try:
        socket, _ = await connect_body(server.bound_port, "b1", ["kai"])
        for garbage in ("[]", "null", "{}", '{"type":"warp"}', "not json", '{"no_type":1}'):
            await socket.send(garbage)
        frames = await collect(socket, 0.6)
        assert any(isinstance(f, ActionCommand) for f in frames), \
            "connection must survive malformed frames and keep streaming"
        await socket.close()
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=5)


def test_robot_fail_closed_capabilities():
    empty_robot = EmbodimentManifest(body_id="r", backend="robot")
    assert not empty_robot.accepts_step("stir_pan")
    assert empty_robot.accepts_step("idle_breathing")     # universal only
    assert not empty_robot.accepts_template("cooking")
    assert empty_robot.accepts_template("idle")
    empty_web = EmbodimentManifest(body_id="w", backend="web")
    assert empty_web.accepts_step("stir_pan")             # virtual stays permissive


# ------------------------------------------------------------ LLM isolation e2e
class Slow30sLLM:
    def decide(self, *a, **k):
        time.sleep(30)
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_slow_llm_does_not_stall_ticks_or_actions():
    server, task = await start_server(llm=Slow30sLLM(), llm_timeout_s=0.5)
    try:
        socket, _ = await connect_body(server.bound_port, "b1", ["kai"])
        await socket.send(encode(WireEvent(kind="user_utterance", source="user",
                                           text="你好", target_agent="kai")))
        frames = await collect(socket, 1.5)
        ticks = [f for f in frames if getattr(f, "type", "") == "tick"]
        actions = [f for f in frames if isinstance(f, ActionCommand)]
        assert len(ticks) >= 6, "heartbeat must continue while the LLM hangs"
        assert actions, "action stream must continue while the LLM hangs"
        await socket.close()
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=5)


# ------------------------------------------------------------- IR compatibility
def test_ir_v01_frames_still_decode_and_v02_roundtrips():
    legacy = json.dumps({"type": "action", "agent_id": "kai", "name": "stir_pan"})
    cmd = decode(legacy)
    assert isinstance(cmd, ActionCommand)
    assert cmd.protocol_version == PROTOCOL_VERSION   # defaulted
    assert cmd.interruptible is True and cmd.priority == 50

    full = ActionCommand(agent_id="kai", name="stir_pan", template_id="cooking",
                         sequence=7, priority=90, deadline=1200.5, ttl_s=10,
                         interruptible=False, safety_class="physical",
                         ack_policy="full", trace_context={"span": "abc"},
                         correlation_id="beat-3", target_body="rover")
    back = decode(encode(full))
    assert back.sequence == 7 and back.safety_class == "physical"
    assert back.trace_context == {"span": "abc"} and back.interruptible is False

    obs = Observation(command_id="c1", agent_id="kai", status="rejected",
                      body_id="rover", error_code="E_CAPABILITY",
                      sensor_snapshot={"temp_c": 41.5}, recoverable=False,
                      started_at=100.0, finished_at=100.5)
    back_obs = decode(encode(obs))
    assert back_obs.error_code == "E_CAPABILITY" and back_obs.recoverable is False
