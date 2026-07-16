"""Fully-offline multimodal perception demo — fixed image + audio fixtures only.

    Camera fixtures ─┐
                     ├─> PerceptionRuntime ─> PerceptionEvent ─> CompanionRuntime
    Audio fixtures ──┘        (mock providers)                        │
                                              ActionCommand-level steps + dialogue

No camera, microphone, network or GPU involved. What you see is a *preview* of
grounded action intents — nothing here claims a robot actually grasped a cup.

Run:  uv run python demo/perception_offline_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.perception import (
    FileCameraSource, MockASRProvider, MockVAD, MockVisionProvider,
    PerceptionFusion, PerceptionRuntime, RecordedAudioSource, to_wire_event,
)
from engine.planner import CompanionRuntime, Event, EventKind, MockBehaviorLLM, Persona, WorldState

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "perception"
SEP = "─" * 74


def main() -> None:
    perception = PerceptionRuntime(
        fusion=PerceptionFusion(source_body="fixture-cam", target_agent="kai",
                                debounce_s=0.0),
        vision_provider=MockVisionProvider(),
    )
    perception.start()

    print(SEP + "\n① 视觉 fixtures → 结构化事件")
    visual_events = perception.run_camera(FileCameraSource(FIXTURES / "vision"))
    for event in visual_events:
        print(f"  [{event.kind:16s}] {event.text:<24s} conf={event.confidence:.2f} "
              f"entities={[e.entity_id for e in event.entities]}")

    print(SEP + "\n② 听觉 fixtures → ASR → 事件（含与视觉窗口的融合）")
    audio_events = perception.run_microphone(
        RecordedAudioSource(FIXTURES / "audio"), vad=MockVAD(), asr=MockASRProvider())
    for event in audio_events:
        referent = event.payload.get("referent_entity_id", "-")
        print(f"  [{event.kind:16s}] “{event.text}” referent={referent}")

    print(SEP + "\n③ Character Runtime 决策 → 动作步骤 + 台词（唯一大脑）")
    dispatched = []
    runtime = CompanionRuntime(
        [Persona("kai", "Kai", "steady_caretaker", relationships={"user": 0.75})],
        WorldState(sim_minute=19 * 60), llm=MockBehaviorLLM(),
        adapter=lambda agent_id, action: dispatched.append(action))
    minute = 19 * 60 + 1
    for event in visual_events + audio_events:
        wire = to_wire_event(event)
        runtime.push_event(Event(t_min=minute, kind=EventKind(wire.kind),
                                 source=wire.source, text=wire.text,
                                 payload=wire.payload, target_agent="kai"))
        minute += 1
    runtime.run(start_min=19 * 60 + 1, duration_min=len(visual_events) + len(audio_events) + 1)

    for action in dispatched:
        if action.dialogue:
            print(f"  🗣  说: “{action.dialogue}”  (correlation={action.correlation_id})")
        elif action.name in ("look_at_user", "pause_template", "resume_template"):
            preview = action.params.get("action_preview")
            extra = f" action_preview={preview} referent={action.params.get('referent_entity_id')}" if preview else ""
            print(f"  🤖 动作: {action.name}{extra}  (correlation={action.correlation_id})")

    print(SEP + "\n④ 感知健康指标")
    for key, value in perception.health().items():
        print(f"  {key}: {value}")
    perception.stop()
    print(SEP)
    print("离线闭环完成：fixtures → 感知 → 事件 → 决策 → 动作/台词（动作为预览，未声称已执行机械操作）")


if __name__ == "__main__":
    main()
