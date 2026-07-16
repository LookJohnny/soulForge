"""Acceptance walkthrough for the SoulForge companion planner.

Runs every acceptance criterion end to end and prints the evidence:

  1. 24h day_plan generation (persona/energy/goals aware)
  2. any hour expanded into hour_plan -> minute_action -> adapter commands
  3. event at an arbitrary minute -> explained continue/pause/resume/rewrite
  4. the four replanning scenarios (greeting / preference / sadness / critical)

Run:  uv run python demo/planner_acceptance_demo.py
Interactive mode (type utterances yourself):
      uv run python demo/planner_acceptance_demo.py --interactive
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.planner import (
    CompanionRuntime, Event, EventKind, MockBehaviorLLM, Persona, WorldState,
    expand_hour, generate_day_plan, plan_minute,
)

SEP = "─" * 78


def personas():
    return [
        Persona("luna", "Luna", "creative_care", traits=["warm", "artistic"],
                energy=0.7, daily_goals=["完成一幅画", "陪用户聊天"],
                relationships={"user": 0.80}),
        Persona("kai", "Kai", "steady_caretaker", traits=["reliable", "calm"],
                energy=0.8, daily_goals=["做三餐", "把家里理顺"],
                relationships={"user": 0.75}),
        Persona("pipo", "Pipo", "utility_robot", traits=["precise", "helpful"],
                energy=0.9, daily_goals=["植物巡检", "环境监测"],
                relationships={"user": 0.70}),
    ]


def fmt_min(m: float) -> str:
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def show_day_plans(world):
    print(SEP)
    print("① 24 小时 day_plan（高层意图，非死板脚本）")
    print(SEP)
    for persona in personas():
        plan = generate_day_plan(persona, world)
        print(f"\n{persona.name} ({persona.archetype}, energy={persona.energy}) — {plan.rationale}")
        for block in plan.blocks:
            print(f"  {fmt_min(block.start_min)}-{fmt_min(block.end_min)}  "
                  f"{block.activity_key:<12} {block.intent}")


def show_hour_and_minute(world):
    print()
    print(SEP)
    print("② 小时级细分 + ③ 分钟级动作（Kai @ 19:00 Dinner）")
    print(SEP)
    kai = personas()[1]
    day = generate_day_plan(kai, world)
    hour = expand_hour(kai, day, 19, world)
    print(f"\nhour_plan goal: {hour.goal}")
    print(f"expected mood delta (valence,arousal): {hour.expected_mood_delta}")
    print(f"non-interruptible templates this hour: {hour.non_interruptible or '(none)'}")
    for activity in hour.activities:
        flag = "可中断" if activity.interruptible else "不可中断"
        print(f"  {fmt_min(activity.start_min)} +{activity.duration_min:>2}min "
              f"{activity.template_id:<10} params={activity.params} [{flag}]")

    print("\nminute_action 抽样（每 15 分钟）→ 模板 micro-step → adapter 命令:")
    for minute in (19 * 60 + 2, 19 * 60 + 17, 19 * 60 + 38, 19 * 60 + 52):
        action = plan_minute(kai, hour, minute)
        step = action.steps[0]
        print(f"  {fmt_min(minute)}  template={action.template_id:<10} step={step.name:<18} "
              f"unity={step.adapter_command.get('unity', '-'):<18} "
              f"mujoco={step.adapter_command.get('mujoco', '-')}")


def run_scenario(title, text, kind=EventKind.USER_UTTERANCE, target="kai", minute=19 * 60 + 12):
    print()
    print(SEP)
    print(title)
    print(SEP)
    dispatched = []
    runtime = CompanionRuntime(
        personas(), WorldState(sim_minute=minute),
        llm=MockBehaviorLLM(),
        adapter=lambda agent_id, act: dispatched.append((agent_id, act)),
    )
    before = [a.template_id for a in runtime_hour(runtime, target, minute).activities]
    runtime.push_event(Event(t_min=minute, kind=kind, source="user" if kind == EventKind.USER_UTTERANCE else "battery",
                             text=text, target_agent=target))
    runtime.run(start_min=minute, duration_min=3)

    print(f"事件: {text!r} @ {fmt_min(minute)}  (当时活动: {before})")
    print(f"决策解释: {runtime.explain_last_decision()}")
    after_hour = runtime.hour_plans[target]
    print(f"事件后 hour_plan goal: {after_hour.goal}")
    print(f"事件后活动序列: {[(a.template_id, a.params) for a in after_hour.activities]}")
    day_tail = runtime.day_plans[target].blocks[-2:]
    print(f"day_plan 尾部: {[(fmt_min(b.start_min), b.activity_key, b.intent) for b in day_tail]}")
    if runtime.memory[target]:
        print(f"memory_update: {runtime.memory[target]}")
    print(f"relationship(user): {runtime.personas[target].relationships.get('user'):.2f}")
    spoken = [a.dialogue for _, a in dispatched if a.dialogue]
    if spoken:
        print(f"插入台词: {spoken}")
    micro = [a.name for _, a in dispatched if a.template_id is None or a.name in
             ("look_at_user", "pause_template", "resume_template", "approach_user",
              "stop_current_activity", "abort_all_templates", "speak_line", "resume_activity")]
    print(f"微动作序列: {micro[:8]}")


def runtime_hour(runtime, agent_id, minute):
    runtime.world.sim_minute = minute
    runtime._ensure_hour_plans(minute)  # noqa: SLF001 - demo introspection
    return runtime.hour_plans[agent_id]


def interactive():
    print("交互模式：输入一句话（如 你好 / 想吃辣一点 / 我今天很难过 / 检测到低电量），Ctrl-D 退出")
    minute = 19 * 60 + 12
    runtime = CompanionRuntime(personas(), WorldState(sim_minute=minute), llm=MockBehaviorLLM())
    runtime.run(start_min=minute, duration_min=1)
    while True:
        try:
            text = input(f"[{fmt_min(minute)}] 用户> ").strip()
        except EOFError:
            break
        if not text:
            continue
        minute += 1
        runtime.push_event(Event(t_min=minute, kind=EventKind.USER_UTTERANCE,
                                 source="user", text=text, target_agent="kai"))
        runtime.run(start_min=minute, duration_min=1)
        print(f"  → {runtime.explain_last_decision()}")
        print(f"  → hour goal: {runtime.hour_plans['kai'].goal}")


if __name__ == "__main__":
    if "--interactive" in sys.argv:
        interactive()
        sys.exit(0)
    world = WorldState(user_present=True)
    show_day_plans(world)
    show_hour_and_minute(world)
    run_scenario("④a LOW — 普通问候：计划继续", "你好呀")
    run_scenario("④b MEDIUM — 用户偏好：cooking 模板参数被改写后恢复", "晚饭想吃清淡一点")
    run_scenario("④c HIGH — 负面情绪：当前小时被重写为陪伴模式", "我今天很难过")
    run_scenario("④d CRITICAL — 机器人低电量：剩余 day_plan 被改写", "检测到低电量警告",
                 kind=EventKind.ROBOT_STATE, target="pipo")
    print()
    print(SEP)
    print("全部验收项跑通。渲染层联动见 demo/generate_dinner_timeline.py（同一 runtime 驱动 30s 视频）")
