"""Phase-3 acceptance: planner IR -> RobotEmbodimentAdapter -> PhysicalExecutor
-> Observation, with fault injection and fail-closed behavior."""

from engine.embodiment import FaultInjectionBackend, RobotEmbodimentAdapter
from engine.physical_ai_engine import PhysicalAIEngine
from engine.physical_executor import RecordingBackend
from engine.server.protocol import ActionCommand
from engine.vtuber_model import build_proxy_manifest


def make_adapter(backend=None, **kwargs):
    backend = backend or RecordingBackend()
    engine = PhysicalAIEngine(build_proxy_manifest("test"), backend, control_hz=10)
    return RobotEmbodimentAdapter(engine=engine, body_id="rover-01", **kwargs), backend


def command(name="look_at_user", **kwargs):
    return ActionCommand(agent_id="pipo", name=name, template_id="plant_care", **kwargs)


def test_ir_to_executor_closed_loop_done():
    adapter, backend = make_adapter()
    obs = adapter.execute(command("look_at_user"))
    assert obs.status == "done"
    assert obs.body_id == "rover-01"
    assert obs.agent_id == "pipo"
    assert any(f["commands"] for f in backend.frames), (
        "servo commands must actually reach the backend"
    )
    assert obs.finished_at is not None


def test_unknown_step_is_rejected_not_guessed():
    adapter, _ = make_adapter()
    obs = adapter.execute(command("compile_kernel"))
    assert obs.status == "rejected"
    assert obs.error_code == "E_CAPABILITY"
    assert adapter.fault_latched is False  # rejection is not a fault


def test_expired_deadline_rejected():
    adapter, _ = make_adapter(sim_minute=lambda: 100.0)
    obs = adapter.execute(command(deadline=99.0))
    assert obs.status == "rejected" and obs.error_code == "E_EXPIRED"


def test_comm_loss_fails_latches_and_requires_manual_reset():
    fib = FaultInjectionBackend(RecordingBackend())
    adapter, _ = make_adapter(backend=fib)
    fib.inject("comm_loss")
    obs = adapter.execute(command())
    assert obs.status == "failed" and obs.error_code == "E_COMM_LOSS"
    assert obs.recoverable is False
    assert adapter.fault_latched

    # latched: everything is rejected until a human resets
    fib.inject("none")
    obs2 = adapter.execute(command())
    assert obs2.status == "rejected" and obs2.error_code == "E_FAULT_LATCHED"

    assert adapter.reset_faults(operator="") is False  # anonymous reset refused
    assert adapter.reset_faults(operator="lovelyjoy")
    obs3 = adapter.execute(command())
    assert obs3.status == "done"


def test_stall_swallows_motion_but_reports_execution_metadata():
    fib = FaultInjectionBackend(RecordingBackend())
    adapter, _ = make_adapter(backend=fib)
    fib.inject("stall")
    obs = adapter.execute(command())
    # a stall at this level manifests as commands never reaching servos;
    # execution still completes units (time passes) and reports safety status
    assert obs.status in ("done", "failed")
    assert fib.sent_batches > 0
    assert all(not f["commands"] for f in fib.inner.frames), (
        "stall must swallow all servo commands"
    )


def test_sensor_snapshot_reaches_observation_and_safety():
    fib = FaultInjectionBackend(RecordingBackend())
    adapter, _ = make_adapter(backend=fib)
    fib.inject("low_battery", voltage=3.9)
    obs = adapter.execute(command())
    # the reading reaches both the safety layer and the outgoing observation;
    # sub-minimum battery makes safety go critical -> failed E_SAFETY + latch
    assert obs.sensor_snapshot.get("battery_voltage") == 3.9
    assert obs.status == "failed" and obs.error_code == "E_SAFETY"
    assert adapter.fault_latched


def test_illegal_joint_values_are_clamped_by_safety():
    """Planner/template-side extremes are clamped by SafetyManager BEFORE the
    backend; corruption injected after the filter is the HAL's problem (that
    boundary is what FaultInjectionBackend's illegal_joint documents)."""
    adapter, backend = make_adapter()
    filtered = adapter.engine.executor._filter_pose({"head_yaw": 10_000.0}, dt=0.1)
    values = [c["value"] for c in filtered if isinstance(c.get("value"), (int, float))]
    assert values and max(abs(v) for v in values) < 1000, (
        f"safety must clamp extreme joint targets, got {values}"
    )

    # post-filter corruption bypasses SafetyManager by construction — the wire
    # DOES carry the bad value, proving firmware/HAL limits are also required
    fib = FaultInjectionBackend(RecordingBackend())
    adapter2, _ = make_adapter(backend=fib)
    fib.inject("illegal_joint")
    adapter2.execute(command())
    leaked = [
        c["value"]
        for f in fib.inner.frames
        for c in f["commands"]
        if isinstance(c.get("value"), (int, float))
    ]
    assert leaked and max(leaked) == 10_000.0


def test_watchdog_trips_and_enters_safe_pose():
    slow_wall = iter([0.0, 0.0, 100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0])
    adapter, _ = make_adapter(
        watchdog_wall_s=5.0, wall_clock=lambda: next(slow_wall, 200.0)
    )
    obs = adapter.execute(command())
    assert obs.status == "failed" and obs.error_code == "E_WATCHDOG"
    assert adapter.fault_latched


def test_planner_to_robot_end_to_end():
    """Full loop: CompanionRuntime minute action -> IR -> robot -> Observation."""
    from engine.planner import CompanionRuntime, MockBehaviorLLM, Persona, WorldState

    runtime = CompanionRuntime(
        [Persona("pipo", "Pipo", "utility_robot", relationships={"user": 0.7})],
        WorldState(sim_minute=19 * 60),
        llm=MockBehaviorLLM(),
    )
    dispatched = []
    runtime.adapter = lambda agent_id, action: dispatched.append((agent_id, action))
    runtime.run(start_min=19 * 60, duration_min=2)
    assert dispatched

    adapter, backend = make_adapter()
    statuses = []
    for agent_id, action in dispatched[:4]:
        ir = ActionCommand(
            agent_id=agent_id,
            name=action.name,
            template_id=action.template_id,
            params=action.params,
            duration_s=action.duration_s,
        )
        statuses.append(adapter.execute(ir).status)
    assert "done" in statuses
    assert all(s in ("done", "rejected") for s in statuses)
    assert any(f["commands"] for f in backend.frames), (
        "planner intent produced real servo traffic"
    )
