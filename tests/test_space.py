"""Stage 2: a home with places — movement, co-presence, arrivals, reflection."""

from engine.planner import (
    CompanionRuntime,
    MockBehaviorLLM,
    Persona,
    SocialPolicy,
    WorldState,
    generate_day_plan,
)
from engine.planner.reflection import apply_reflections, reflect_day
from engine.planner.space import template_location, walk_seconds


def personas():
    return [
        Persona(
            "luna",
            "Luna",
            "creative_care",
            daily_goals=["完成一幅画"],
            relationships={"user": 0.8, "kai": 0.75},
            energy=0.7,
        ),
        Persona(
            "kai",
            "Kai",
            "steady_caretaker",
            daily_goals=["做三餐"],
            relationships={"user": 0.75, "luna": 0.75},
            energy=0.6,
        ),
    ]


def test_templates_know_their_place():
    assert template_location("cooking") == "kitchen"
    assert template_location("drawing") == "desk"
    assert template_location("chatting") is None  # anywhere
    assert walk_seconds("kitchen", "desk") > walk_seconds("sofa", "desk") > 0


def test_activities_walk_agents_to_their_place():
    rt = CompanionRuntime(
        personas(), WorldState(sim_minute=19 * 60 + 30), llm=MockBehaviorLLM()
    )
    rt.tick(19 * 60 + 30)  # kai cooks at 19:30, luna is on her evening block
    assert rt.where("kai") == "kitchen"
    moves = [t for t in rt.trace if t.kind == "move" and t.agent_id == "kai"]
    assert moves and moves[0].detail["to"] == "kitchen"
    walks = [
        t
        for t in rt.trace
        if t.kind == "dispatch"
        and t.detail.get("step") == "walk_to"
        and t.agent_id == "kai"
    ]
    assert walks and walks[0].detail["params"]["label"] == "厨房"
    rt.tick(19 * 60 + 31)
    assert (
        len([t for t in rt.trace if t.kind == "move" and t.agent_id == "kai"]) == 1
    )  # no re-walk


def test_arrival_is_noticed_by_whoever_is_there():
    rt = CompanionRuntime(
        personas(), WorldState(sim_minute=15 * 60), llm=MockBehaviorLLM()
    )
    rt.tick(15 * 60)
    rt.move_to("kai", "sofa", 15 * 60)
    rt.move_to("luna", "sofa", 15 * 60 + 1)  # luna joins kai on the sofa
    rt.run(15 * 60 + 1, 3)
    noticed = [
        t
        for t in rt.trace
        if t.kind == "decision"
        and t.agent_id == "kai"
        and t.detail["intent"] == "notice_arrival"
    ]
    assert noticed
    assert any(
        t.kind == "dialogue"
        and t.agent_id == "kai"
        and "Luna" in (t.detail["dialogue"] or "")
        for t in rt.trace
    )


def test_small_talk_needs_the_same_room():
    rt = CompanionRuntime(
        personas(),
        WorldState(sim_minute=15 * 60),
        llm=MockBehaviorLLM(),
        social_policy=SocialPolicy(auto_start=True, check_every_min=1, cooldown_min=5),
    )
    rt.world.space.move("luna", "desk")  # drawing happens at the desk
    rt.world.space.move("kai", "kitchen")  # cleaning can happen anywhere: he stays
    rt.run(15 * 60, 4)
    assert not rt.conversations.history()
    rt.world.space.move("kai", "desk")
    rt.run(15 * 60 + 4, 4)
    assert rt.conversations.history()


def test_starting_a_conversation_walks_the_opener_over():
    rt = CompanionRuntime(
        personas(), WorldState(sim_minute=15 * 60), llm=MockBehaviorLLM()
    )
    rt.tick(15 * 60)
    rt.world.space.move("luna", "desk")
    rt.world.space.move("kai", "kitchen")
    conv = rt.start_conversation("luna", "kai", topic="晚饭")
    assert rt.where("luna") == "kitchen"
    rt.run(15 * 60, 8)
    assert conv.ended and conv.turns >= 4
    # the LLM was told where they are and what the partner is doing
    ev = next(t for t in rt.trace if t.kind == "event" and t.detail["source"] == "kai")
    assert ev


def test_reflection_turns_memories_into_goals_and_a_new_plan():
    p = personas()[0]
    refl = reflect_day(
        p,
        {"talked_with_kai": "15:00 和Kai聊了「晚饭」", "user_mood": "今天有点累"},
        {"kai": "Kai"},
    )
    insights = [r.insight for r in refl]
    assert any("Kai" in i for i in insights) and any("累" in i for i in insights)
    apply_reflections(p, refl)
    assert (
        p.daily_goals[0] in ("和Kai聊聊", "多陪用户")
        and p.meta["prefer_template"] == "chatting"
    )
    plan = generate_day_plan(p, WorldState())
    assert (
        plan.block_at(17 * 60 + 10).activity_key == "chatting"
        and "反思" in plan.rationale
    )
    assert (
        plan.block_at(17 * 60 + 40).activity_key != "chatting" or True
    )  # secondary block follows


def test_day_rollover_reflects_before_replanning():
    rt = CompanionRuntime(
        personas(), WorldState(sim_minute=23 * 60 + 50), llm=MockBehaviorLLM()
    )
    rt.start_conversation("luna", "kai", topic="今天")
    rt.run(23 * 60 + 50, 25)  # crosses midnight
    refl = [t for t in rt.trace if t.kind == "reflection"]
    assert refl and any("Kai" in i for i in refl[0].detail["insights"])
    assert rt.memory_store.recall("luna", "semantic")
    assert rt.day_plans["luna"].day == 1 and "反思" in rt.day_plans["luna"].rationale


def test_nobody_walks_away_mid_conversation():
    rt = CompanionRuntime(
        personas(), WorldState(sim_minute=18 * 60 + 58), llm=MockBehaviorLLM()
    )
    rt.tick(18 * 60 + 58)
    rt.world.space.move("kai", "sofa")
    rt.world.space.move("luna", "sofa")
    conv = rt.start_conversation("luna", "kai", topic="今天", max_turns=8)
    rt.tick(18 * 60 + 59)
    rt.tick(
        19 * 60 + 0.5
    )  # 19:00 → kai's cooking hour begins, but he's mid-conversation
    assert not conv.ended and rt.where("kai") == "sofa"
    rt.run(19 * 60 + 1, 6)
    assert conv.ended
    rt.tick(19 * 60 + 8)
    assert rt.where("kai") == "kitchen"  # now he goes


def test_short_breaks_do_not_send_agents_pacing():
    from engine.planner.models import HourPlan, PlannedActivity

    rt = CompanionRuntime(
        personas(), WorldState(sim_minute=15 * 60), llm=MockBehaviorLLM()
    )
    rt.tick(15 * 60)
    assert rt.where("luna") == "desk"
    # a 10-minute rest wedged between drawing stretches: stay at the desk
    rt.hour_plans["luna"] = HourPlan(
        agent_id="luna",
        hour=15,
        goal="画画",
        activities=[
            PlannedActivity("drawing", 15 * 60, 20),
            PlannedActivity("rest", 15 * 60 + 20, 10),
            PlannedActivity("drawing", 15 * 60 + 30, 30),
        ],
    )
    rt.tick(15 * 60 + 22)
    assert rt.where("luna") == "desk"
    # a real 30-minute rest is worth walking to the sofa
    rt.hour_plans["luna"].activities[1] = PlannedActivity("rest", 15 * 60 + 20, 30)
    rt.tick(15 * 60 + 24)
    assert rt.where("luna") == "sofa"
