"""Acceptance tests for the hierarchical companion planner."""

from engine.planner import (
    CompanionRuntime,
    Event,
    EventKind,
    MockBehaviorLLM,
    Persona,
    TEMPLATE_REGISTRY,
    WorldState,
    expand_hour,
    generate_day_plan,
    plan_minute,
)


def make_personas():
    return [
        Persona("luna", "Luna", "creative_care", traits=["warm", "artistic"],
                daily_goals=["完成一幅画", "陪用户聊天"], relationships={"user": 0.8}),
        Persona("kai", "Kai", "steady_caretaker", traits=["reliable", "calm"],
                daily_goals=["做三餐", "把家里理顺"], relationships={"user": 0.75}),
        Persona("pipo", "Pipo", "utility_robot", traits=["precise", "helpful"],
                daily_goals=["植物巡检", "环境监测"], relationships={"user": 0.7}),
    ]


def test_day_plan_covers_24h_and_reflects_archetype():
    world = WorldState(user_present=True)
    for persona in make_personas():
        plan = generate_day_plan(persona, world)
        assert plan.blocks[0].start_min == 0          # full-day coverage incl. night rest
        assert plan.blocks[-1].end_min == 24 * 60
        # contiguous, no gaps
        for a, b in zip(plan.blocks, plan.blocks[1:]):
            assert a.end_min == b.start_min
    kai = generate_day_plan(make_personas()[1], world)
    assert kai.block_at(19 * 60 + 30).activity_key == "cooking"
    pipo = generate_day_plan(make_personas()[2], world)
    assert pipo.block_at(19 * 60 + 30).activity_key == "plant_care"


def test_hour_expansion_and_minute_resolution():
    world = WorldState()
    persona = make_personas()[1]
    day = generate_day_plan(persona, world)
    hour = expand_hour(persona, day, 19, world)
    assert hour.activities, "hour plan must contain phased activities"
    assert all(a.template_id in TEMPLATE_REGISTRY for a in hour.activities)
    minute = plan_minute(persona, hour, 19 * 60 + 12)
    assert minute.template_id == "cooking"
    assert minute.steps and minute.steps[0].adapter_command, "minute action must map to adapter commands"


def test_templates_declare_full_contract():
    for template in TEMPLATE_REGISTRY.values():
        assert template.duration_range_s[0] < template.duration_range_s[1]
        assert template.animation_clips, template.template_id
        assert template.recovery, template.template_id
        assert template.unity_command
    assert TEMPLATE_REGISTRY["repair"].interruptible is False
    assert not TEMPLATE_REGISTRY["cooking"].check_preconditions(["pan", "stove"], "kitchen")
    assert TEMPLATE_REGISTRY["cooking"].check_preconditions([], "sofa")


def run_scenario(text, kind=EventKind.USER_UTTERANCE):
    runtime = CompanionRuntime(make_personas(), WorldState(sim_minute=19 * 60), llm=MockBehaviorLLM())
    runtime.push_event(Event(t_min=19 * 60 + 2, kind=kind, source="user", text=text, target_agent="kai"))
    runtime.run(start_min=19 * 60, duration_min=5)
    decisions = [t for t in runtime.trace if t.kind == "decision"]
    assert decisions, "event must produce an explainable decision"
    return runtime, decisions[-1].detail


def test_low_impact_greeting_keeps_plan():
    runtime, decision = run_scenario("你好呀")
    assert decision["impact"] == "LOW"
    assert decision["scope"] == "micro"
    # plan unchanged: cooking still scheduled this hour
    assert any(a.template_id == "cooking" for a in runtime.hour_plans["kai"].activities)
    assert "plan unchanged" in decision["reason"] or "micro" in decision["reason"]


def test_medium_impact_preference_patches_template_params():
    runtime, decision = run_scenario("晚饭想吃清淡一点")
    assert decision["impact"] == "MEDIUM"
    assert decision["scope"] == "insert"
    cooking = [a for a in runtime.hour_plans["kai"].activities if a.template_id == "cooking"]
    assert any(a.params.get("flavor") == "light" for a in cooking), "cooking template must be re-parameterized"


def test_high_impact_negative_emotion_rewrites_hour_to_companion_mode():
    runtime, decision = run_scenario("我今天很难过")
    assert decision["impact"] == "HIGH"
    assert decision["scope"] == "hour"
    plan = runtime.hour_plans["kai"]
    assert "陪伴" in plan.goal
    assert plan.activities[0].template_id == "chatting"
    assert runtime.memory["kai"].get("evening_mode") == "companion"
    assert runtime.personas["kai"].relationships["user"] > 0.75, "comforting should strengthen relationship"


def test_critical_event_rewrites_remaining_day():
    runtime, decision = run_scenario("检测到低电量警告", kind=EventKind.ROBOT_STATE)
    assert decision["impact"] == "CRITICAL"
    assert decision["scope"] == "day"
    blocks = runtime.day_plans["kai"].blocks
    assert any("紧急" in b.intent for b in blocks)
    assert blocks[-1].end_min == 24 * 60


def test_explainability():
    runtime, _ = run_scenario("我今天很难过")
    explanation = runtime.explain_last_decision()
    assert "HIGH" in explanation and "hour" in explanation
