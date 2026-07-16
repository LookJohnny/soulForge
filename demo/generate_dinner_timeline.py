"""Generate the 30s dinner-demo timeline from the companion planner runtime.

The renderer (demo/vtuber_life_web) and the TTS pipeline both consume the JSON
this script emits, so the video is driven by the event-queue engine instead of
a hand-written script.

Run:  uv run python demo/generate_dinner_timeline.py
Out:  demo/vtuber_life_web/dinner_timeline.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.planner import (
    CompanionRuntime, Event, EventKind, MockBehaviorLLM, WorldState,
)
from engine.planner.characters import load_personas

OUT = Path(__file__).parent / "vtuber_life_web" / "dinner_timeline.json"

PERSONAS = load_personas()   # single source of truth: configs/characters.json

START_MIN = 20 * 60 + 47  # 20:47


def main() -> None:
    world = WorldState(sim_minute=START_MIN, user_present=True,
                       sensors={"plant_humidity_right": 0.22})
    runtime = CompanionRuntime(PERSONAS, world, llm=MockBehaviorLLM())

    # the interruptions that drive the demo
    runtime.push_event(Event(t_min=START_MIN + 1, kind=EventKind.USER_UTTERANCE,
                             source="user", text="我今天有点累……", target_agent="luna"))
    runtime.push_event(Event(t_min=START_MIN + 2, kind=EventKind.ENVIRONMENT,
                             source="plant_sensor", text="右侧盆栽湿度偏低 22%",
                             payload={"humidity": 0.22}, target_agent="pipo"))
    runtime.run(start_min=START_MIN, duration_min=4)

    decisions = {t.agent_id: t.detail for t in runtime.trace if t.kind == "decision"}
    luna_decision = decisions.get("luna", {})

    # Video beats: seconds on the 30s clip timeline. Dialogue for the scripted
    # household beats; the two event beats carry the engine's actual decisions.
    beats = [
        beat(1.0, 4.6, "kai", ["luna"], "kitchen",
             "Luna，你画了一下午啦，晚餐想吃什么口味？", "warm",
             template="cooking", step="stir_pan",
             text_en="Luna, you've been drawing all afternoon — what do you feel like for dinner?"),
        beat(5.0, 8.0, "luna", ["kai"], "desk",
             "清淡一点吧，我想喝热汤。", "soft",
             template="drawing", step="lean_back_review",
             text_en="Something light… and a warm soup, please."),
        # -- user interruption: engine decided HIGH -> rewrite hour to companion mode
        beat(9.6, 14.4, "luna", ["user"], "luna_close",
             "听到啦，今晚不排任务，我们窝在沙发聊聊天。", "warm",
             template="chatting", step="look_at_user",
             text_en="Heard you. No tasks tonight — let's curl up on the couch and just talk.",
             event={"t": 8.4, "source": "user", "text": "我今天有点累……",
                    "impact": luna_decision.get("impact", "HIGH"),
                    "scope": luna_decision.get("scope", "hour"),
                    "decision": "暂停绘画推进 → 切换陪伴模式 → 重写 20:47-21:30"}),
        beat(14.8, 18.4, "kai", ["user", "luna"], "kitchen_close",
             "汤马上就好，晚上的安排我也改轻松一点。", "calm",
             template="cooking", step="plate_up",
             text_en="Soup's almost ready. I'll ease up tonight's plan too."),
        # -- environment event: LOW/insert -> plant care note goes to tomorrow's plan
        beat(19.2, 23.4, "pipo", ["kai", "luna"], "plant",
             "我刚看了植物，右边那盆湿度有点低，我把浇水加进了明早的清单。", "robot",
             template="plant_care", step="scan_leaves",
             text_en="Plant check: the right pot reads a little dry. Watering is on tomorrow's care list.",
             event={"t": 18.6, "source": "plant_sensor", "text": "右侧盆栽湿度 22%",
                    "impact": decisions.get("pipo", {}).get("impact", "LOW"),
                    "scope": decisions.get("pipo", {}).get("scope", "micro"),
                    "decision": "不打断当前活动 → 插入提醒 → 更新明日计划"}),
        beat(23.8, 26.0, "kai", ["pipo"], "two_shot",
             "好，明早我来浇水，你负责提醒我。", "calm",
             template="cooking", step="announce_ready",
             text_en="Deal — I'll water it in the morning, you remind me."),
        beat(26.4, 28.6, "luna", ["kai", "pipo"], "group",
             "谢谢你们，这个家像会自己运转。", "moved",
             template="chatting", step="perform:Clapping",   # 动捕：边道谢边鼓掌
             text_en="Thank you both. This home really feels like it runs itself."),
        beat(28.6, 30.0, "luna", ["user"], "wide_end",
             "", "moved", template="chatting", step="look_at_user"),  # 安静看向镜头 + 机器人 Wave
    ]

    payload = {
        "meta": {
            "title": "SoulForge · Evening Companion Replanning Demo",
            "duration_s": 30.0,
            "sim_clock_start": "20:47",
            "generated_by": "engine.planner CompanionRuntime + MockBehaviorLLM",
            "hour_goal_after_rewrite": runtime.hour_plans["luna"].goal,
        },
        "agents": [
            {
                "id": p.agent_id, "name": p.name, "archetype": p.archetype,
                "voice": p.voice, "role_label": p.meta.get("role_label", ""),
                "color": p.meta.get("color", "#8ecae6"),
                "embodiment": p.meta.get("embodiment", {}),
            }
            for p in PERSONAS
        ],
        "plan_before": ["20:00 画画/做饭/植物巡检", "21:00 一起复盘今天", "22:30 休息"],
        "plan_after": ["20:47 陪伴聊天 · 简单晚餐", "21:30 沙发电影", "明早 07:30 给右侧盆栽浇水"],
        "beats": beats,
        "events": [b["event"] for b in beats if b.get("event")],
        "decision_trace": [
            {"t_min": t.t_min, "agent": t.agent_id, "kind": t.kind, "detail": t.detail}
            for t in runtime.trace if t.kind in ("event", "decision", "plan_change")
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")

    # voice events for demo/synthesize_vtuber_voice_track.mjs (--events-json)
    display = {p.agent_id: p.name for p in PERSONAS}
    voice_events = [
        {"time": b["start"], "agentName": display[b["speaker"]], "dialogue": b["text"],
         "emotion": b["emotion"], "actionTemplateId": b["template"], "cameraShot": b["camera"]}
        for b in beats if b["text"]
    ]
    voice_out = OUT.parent / "dinner_voice_events.json"
    voice_out.write_text(json.dumps({"events": voice_events}, ensure_ascii=False, indent=2), "utf-8")
    print(f"wrote {OUT}")
    print(f"wrote {voice_out}")
    print("decisions:")
    for agent_id, detail in decisions.items():
        print(f"  {agent_id}: [{detail['impact']}] {detail['scope']} :: {detail['reason']}")


def beat(start, end, speaker, targets, camera, text, emotion, template, step, event=None, text_en=""):
    entry = {
        "start": start, "end": end, "speaker": speaker, "targets": targets,
        "camera": camera, "text": text, "text_en": text_en, "emotion": emotion,
        "template": template, "step": step,
    }
    if event:
        entry["event"] = event
    return entry


if __name__ == "__main__":
    main()
