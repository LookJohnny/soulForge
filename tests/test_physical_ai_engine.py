import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.legacy.action_units import compile_to_units
from engine.legacy.daily_autonomy import DailyAutonomyPlanner
from engine.legacy.environment_events import (
    EnvironmentEvent,
    ScriptedEnvironmentAdapter,
)
from engine.legacy.intent import Intent, Priority
from engine.legacy.llm_behavior_planner import LLMBehaviorPlanner
from engine.legacy.physical_ai_engine import PhysicalAIEngine
from engine.legacy.physical_executor import RecordingBackend
from engine.legacy.vtuber_model import build_proxy_manifest, load_vtuber_model
from safety.safety_manager import SafetyManager


def test_action_template_compiles_to_interruptible_units():
    intent = Intent.create("reactive", "look_at_user", ttl_ms=0)
    units = compile_to_units(intent)

    assert len(units) == 3
    assert all(unit.duration_s > 0 for unit in units)
    assert units[-1].end_pose["head_yaw"] == 24.0


def test_reactive_intent_preempts_idle_at_unit_boundary():
    manifest = build_proxy_manifest("test")
    backend = RecordingBackend()
    engine = PhysicalAIEngine(manifest, backend, control_hz=10)

    idle = engine.submit_intent("idle", "idle_scan", priority=Priority.IDLE, ttl_ms=0)
    engine.step_unit()
    reactive = engine.submit_intent(
        "reactive", "look_at_user", priority=Priority.REACTIVE, ttl_ms=0
    )
    engine.step_unit()

    event_kinds = [event.kind for event in engine.dispatcher.events]
    assert idle.intent_id != reactive.intent_id
    assert "preempt_requested" in event_kinds
    assert "drop_interrupted" in event_kinds
    assert backend.frames


def test_autonomy_loop_can_simulate_eight_hours_without_render_backend():
    manifest = build_proxy_manifest("longrun")
    backend = RecordingBackend()
    engine = PhysicalAIEngine(manifest, backend, control_hz=1)

    report = engine.run_autonomous(
        8 * 3600,
        plan_interval_s=3600,
        reactive_schedule=[(120, "look_at_user"), (3600, "greeting_wave")],
        max_units=100_000,
    )

    assert report.duration_s >= 8 * 3600
    assert report.safety_status in {"normal", "warning"}
    assert report.intents_submitted >= 8


def test_vtuber_loader_uses_proxy_for_unknown_or_render_asset():
    loaded = load_vtuber_model("example_avatar.vrm")

    assert loaded.mode == "proxy"
    assert "head_yaw_servo" in loaded.mjcf
    assert any(act["id"] == "head_yaw" for act in loaded.manifest["actuators"])


def test_safety_manager_hard_clamps_initial_out_of_range_target():
    manifest = build_proxy_manifest("safety")
    safety = SafetyManager(manifest)

    commands = safety.filter(
        [{"actuator_id": "head_yaw", "command_type": "position", "value": 999.0}],
        dt=0.1,
    )

    assert commands[0]["value"] <= 38.0


def test_llm_behavior_planner_accepts_explicit_safe_template_plan():
    planner = LLMBehaviorPlanner()

    plan = planner.plan(
        {
            "dialogue": "嗯，我看着你。",
            "physical": {
                "action_template_id": "look_at_user",
                "source": "reactive",
                "priority": "REACTIVE",
                "preemptible": False,
                "reason": "voice barge-in",
            },
        }
    )

    assert plan.llm_explicit is True
    assert plan.action_template_id == "look_at_user"
    assert plan.source == "reactive"
    assert plan.priority == Priority.REACTIVE
    assert plan.preemptible is False


def test_llm_behavior_planner_falls_back_from_action_text_and_pad():
    planner = LLMBehaviorPlanner()

    plan = planner.plan(
        {
            "dialogue": "嘿嘿！",
            "action": "开心地左右摇晃了一下",
            "pad": {"p": 0.7, "a": 0.8, "d": 0.1},
        },
        context={"event_type": "proactive"},
    )

    assert plan.llm_explicit is False
    assert plan.action_template_id == "happy_wiggle"
    assert plan.source == "plan"
    assert plan.priority == Priority.PLAN


def test_physical_engine_can_submit_and_execute_llm_response_plan():
    manifest = build_proxy_manifest("llm")
    backend = RecordingBackend()
    engine = PhysicalAIEngine(manifest, backend, control_hz=10)

    intent = engine.submit_llm_response(
        {
            "dialogue": "我听到了。",
            "action": "转头看向用户并轻轻点头",
            "pad": {"p": 0.2, "a": 0.4, "d": 0.0},
        },
        context={"event_type": "user_interrupt"},
    )
    result = engine.step_unit()

    assert intent.action_template_id == "look_at_user"
    assert intent.priority == Priority.REACTIVE
    assert result is not None
    assert backend.frames


def test_daily_autonomy_planner_builds_24h_and_expands_hour_to_minutes():
    planner = DailyAutonomyPlanner()
    plan = planner.build_24h_plan()
    hour_actions = planner.expand_hour(plan, 18)

    assert plan.block_at(0).activity_type == "sleep"
    assert plan.block_at(18 * 60).activity_type == "social"
    assert len(hour_actions) == 60
    assert all(action.action_template_id for action in hour_actions)
    assert any(action.action_template_id == "greeting_wave" for action in hour_actions)


def test_daily_autonomy_engine_accepts_external_environment_events():
    manifest = build_proxy_manifest("daily")
    backend = RecordingBackend()
    engine = PhysicalAIEngine(manifest, backend, control_hz=2)
    environment = ScriptedEnvironmentAdapter(
        [
            EnvironmentEvent(
                t=1.0,
                event_type="user_detected",
                payload={"user_id": "u1"},
            )
        ]
    )

    report = engine.run_daily_autonomy(
        4.0,
        environment=environment,
        start_minute_of_day=18 * 60,
    )
    event_kinds = [event.kind for event in engine.dispatcher.events]

    assert report.duration_s >= 4.0
    assert report.safety_status in {"normal", "warning"}
    assert "preempt_requested" in event_kinds or any(
        event.detail == "reactive" for event in engine.dispatcher.events
    )
