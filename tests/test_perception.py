"""Phase-6 acceptance: multimodal perception -> Character Runtime closed loop.

All tests are fully offline (file/audio fixtures + mock providers). Nothing
here claims real-camera or real-robot validation.
"""

from pathlib import Path

import pytest

from engine.perception import (
    BargeInController,
    FileCameraSource,
    MockASRProvider,
    MockVAD,
    MockVisionProvider,
    PerceptionFusion,
    PerceptionRuntime,
    RecordedAudioSource,
    to_wire_event,
)
from engine.perception.models import PerceptionEvent
from engine.perception.sources import Frame
from engine.planner import (
    CompanionRuntime,
    Event,
    EventKind,
    ImpactLevel,
    MockBehaviorLLM,
    Persona,
    WorldState,
)
from engine.planner.llm_interface import BehaviorDecision

FIXTURES = Path(__file__).parent / "fixtures" / "perception"


def persona(agent_id="kai"):
    return Persona(
        agent_id, agent_id.title(), "steady_caretaker", relationships={"user": 0.75}
    )


def make_runtime(llm=None):
    dispatched = []
    runtime = CompanionRuntime(
        [persona()], WorldState(sim_minute=19 * 60), llm=llm or MockBehaviorLLM()
    )
    runtime.adapter = lambda agent_id, action: dispatched.append(action)
    return runtime, dispatched


def planner_event_from(perception_event: PerceptionEvent, t_min: float) -> Event:
    wire = to_wire_event(perception_event)
    return Event(
        t_min=t_min,
        kind=EventKind(wire.kind),
        source=wire.source,
        text=wire.text,
        payload=wire.payload,
        target_agent="kai",
    )


def make_perception(**kwargs):
    fusion = PerceptionFusion(
        source_body="test-cam", target_agent="kai", debounce_s=0.0, **kwargs
    )
    return PerceptionRuntime(fusion=fusion, vision_provider=MockVisionProvider())


# 1 ─ 录音 → ASR → user_utterance → look/search 动作 + 台词 ------------------
def test_audio_fixture_to_look_action_and_dialogue():
    perception = make_perception()
    events = perception.run_microphone(
        RecordedAudioSource(FIXTURES / "audio"), vad=MockVAD(), asr=MockASRProvider()
    )
    utterance = next(e for e in events if "杯子" in e.text)

    runtime, dispatched = make_runtime()
    runtime.push_event(planner_event_from(utterance, 19 * 60 + 1))
    runtime.run(start_min=19 * 60, duration_min=3)

    names = [a.name for a in dispatched]
    assert "look_at_user" in names, "observation request must produce a look action"
    spoken = [a.dialogue for a in dispatched if a.dialogue]
    assert spoken and any("看" in s for s in spoken), "and a spoken acknowledgement"
    decisions = [t.detail for t in runtime.trace if t.kind == "decision"]
    assert decisions[-1]["intent"] == "observe_and_assist"


# 2 ─ 图片 → person/object 事件 → 注视 + 语音 --------------------------------
def test_image_fixture_to_person_events_and_greeting():
    perception = make_perception()
    events = perception.run_camera(FileCameraSource(FIXTURES / "vision"))
    kinds = {e.kind for e in events}
    assert "person_detected" in kinds and "object_detected" in kinds

    runtime, dispatched = make_runtime()
    person = next(e for e in events if e.kind == "person_detected")
    runtime.push_event(planner_event_from(person, 19 * 60 + 1))
    runtime.run(start_min=19 * 60, duration_min=2)
    assert any(a.name == "look_at_user" for a in dispatched)
    assert any(a.dialogue for a in dispatched), "greeting line expected"
    # micro only: the hour plan is untouched
    assert any(a.template_id == "cooking" for a in runtime.hour_plans["kai"].activities)


# 3 ─ 视听融合：指向 + “把那个递给我” → referent 实体，动作仅预览 -------------
def test_fusion_resolves_deixis_to_entity_and_previews_action():
    perception = make_perception()
    perception.run_camera(FileCameraSource(FIXTURES / "vision"))
    audio_events = perception.run_microphone(
        RecordedAudioSource(FIXTURES / "audio"), vad=MockVAD(), asr=MockASRProvider()
    )
    fused = next(e for e in audio_events if "递给我" in e.text)
    assert fused.kind == "multimodal_context"
    assert fused.payload.get("referent_label") == "cup"
    referent_id = fused.payload.get("referent_entity_id")
    assert referent_id and referent_id.startswith("cup")

    runtime, dispatched = make_runtime()
    runtime.push_event(planner_event_from(fused, 19 * 60 + 1))
    runtime.run(start_min=19 * 60, duration_min=3)
    decisions = [t.detail for t in runtime.trace if t.kind == "decision"]
    assert decisions[-1]["intent"] == "observe_and_assist"
    resumes = [a for a in dispatched if a.name == "resume_template"]
    assert resumes and resumes[0].params.get("referent_entity_id") == referent_id
    # PREVIEW only — nothing may claim a completed grasp
    assert resumes[0].params.get("action_preview") == "hand_over"
    assert not any(
        "grasp" in (a.name or "") or "完成" in (a.dialogue or "") for a in dispatched
    )


# 4 ─ barge-in：说话中检测到用户语音 → 停 TTS + 暂停动作 + 重新决策 ----------
def test_barge_in_stops_tts_and_pauses_motion():
    stopped, paused = [], []
    controller = BargeInController(
        stop_tts=lambda: stopped.append(True),
        pause_motion=lambda reason: paused.append(reason),
    )
    controller.self_voice.on_tts_start("我正在给你讲今天的计划")

    perception = make_perception()
    events = perception.run_microphone(
        RecordedAudioSource(FIXTURES / "audio"),
        vad=MockVAD(),
        asr=MockASRProvider(),
        barge_in=controller,
    )
    assert stopped and paused == ["user_barge_in"]
    assert controller.triggered_count == 1  # second utterance: TTS already off
    # the interrupting utterance still reaches the runtime for a fresh decision
    assert any("杯子" in e.text for e in events)

    # self-voice/echo never triggers barge-in
    controller2 = BargeInController(
        stop_tts=lambda: stopped.append("x"), pause_motion=lambda r: paused.append(r)
    )
    controller2.self_voice.on_tts_start("你好呀")
    from engine.perception.models import AuditoryObservation, SpeakerObservation

    echo = AuditoryObservation(
        ts=0,
        kind="speech",
        transcript="你好呀",
        speaker=SpeakerObservation("kai", is_self_voice=True),
    )
    assert controller2.on_speech_detected(echo) is False


# 5 ─ 低置信度视觉：不产生危险 physical Action -------------------------------
def test_low_confidence_vision_cannot_escalate():
    # below fusion threshold: dropped before the planner ever sees it
    perception = make_perception()
    events = perception.run_camera(FileCameraSource(FIXTURES / "vision_lowconf"))
    assert events == []

    # above fusion threshold but weak: deterministically clamped in the planner
    class ParanoidLLM(MockBehaviorLLM):
        def decide(self, event, persona_, world, current_template, interruptible):
            decision = super().decide(
                event, persona_, world, current_template, interruptible
            )
            decision.impact = ImpactLevel.CRITICAL  # a hostile/hallucinating LLM
            decision.plan_delta = "day"
            return decision

    runtime, dispatched = make_runtime(llm=ParanoidLLM())
    weak = PerceptionEvent(
        kind="person_detected",
        modality="vision",
        timestamp=0,
        captured_at=0,
        source_body="cam",
        text="person detected",
        confidence=0.55,
    )
    runtime.push_event(planner_event_from(weak, 19 * 60 + 1))
    runtime.run(start_min=19 * 60, duration_min=2)
    clamped = [t.detail for t in runtime.trace if t.kind == "decision"]
    assert clamped and clamped[-1]["scope"] == "clamped"
    assert not any(a.name in ("safe_stop", "abort_all_templates") for a in dispatched)
    assert runtime.day_plans["kai"].blocks[-1].end_min == 24 * 60  # day intact


# 5b ─ hazard 确认策略：单帧疑似不上报，三帧确认才 CRITICAL ------------------
def test_hazard_requires_confirmation_then_safe_stop(monkeypatch):
    monkeypatch.setenv(
        "SOULFORGE_PERCEPTION_ATTESTATION_KEY",
        "perception-test-secret-that-is-long-enough",
    )
    perception = make_perception()
    frames = list(FileCameraSource(FIXTURES / "vision_hazard").frames())
    first = perception.process_frame(frames[0], now=frames[0].ts)
    assert first == [], "single suspected-fall frame must not surface"
    events = []
    for frame in frames[1:]:
        events.extend(perception.process_frame(frame, now=frame.ts))
    confirmed = [e for e in events if e.payload.get("hazard_confirmed")]
    assert confirmed and confirmed[0].payload["severity"] == "critical"
    assert confirmed[0].payload["hazard_confirmation_hits"] >= 3

    runtime, dispatched = make_runtime()
    runtime.push_event(planner_event_from(confirmed[0], 19 * 60 + 1))
    runtime.run(start_min=19 * 60, duration_min=2)
    names = [a.name for a in dispatched]
    assert "safe_stop" in names and "hold_safe_breakpoint" in names, (
        "confirmed hazard goes through the deterministic safe-stop flow"
    )


# 6 ─ provider 超时：不阻塞、出 perception_error ------------------------------
def test_vision_provider_timeout_yields_error_event_not_a_hang():
    import time as _time

    class SlowProvider:
        name = "slow"

        def analyze(self, frame):
            _time.sleep(3.0)
            raise AssertionError("unreachable")

    perception = make_perception()
    perception.vision_provider = SlowProvider()
    perception.provider_timeout_s = 0.2
    frame = Frame(
        ts=0.0, ref="x.png", data=(FIXTURES / "vision" / "frame_001.png").read_bytes()
    )
    started = _time.monotonic()
    events = perception.process_frame(frame, now=0.0)
    assert _time.monotonic() - started < 1.5
    assert [e.kind for e in events] == ["perception_error"]
    assert perception.metrics.provider_timeouts == 1


# 7 ─ 同一句话不被 Gateway LLM 与 Planner LLM 双重处理 ------------------------
@pytest.mark.asyncio
async def test_gateway_single_decision_path_bypasses_legacy_chat():
    import sys

    sys.path.insert(
        0, str(Path(__file__).parent.parent / "packages" / "gateway" / "src")
    )
    gateway = pytest.importorskip("gateway.pipeline.orchestrator")

    class FakeBridge:
        def __init__(self):
            self.calls = []

        async def process_utterance(self, text, payload=None):
            self.calls.append(text)
            return {"text": "我来看看。", "correlation_id": "c1", "commands": []}

    class ExplodingClient:
        async def post(self, *a, **k):
            raise AssertionError("legacy ai-core chat path must NOT be called")

    orchestrator = gateway.PipelineOrchestrator.__new__(gateway.PipelineOrchestrator)
    orchestrator.client = ExplodingClient()
    orchestrator._character_bridge = FakeBridge()

    class S:  # minimal session
        character_id = "kai"
        end_user_id = device_id = session_id = "t"
        brand_id = None

    gateway.settings.character_runtime_url = "ws://127.0.0.1:1"
    try:
        result = await gateway.PipelineOrchestrator.process_text(
            orchestrator, S(), "你好"
        )
        assert result["text"] == "我来看看。"
        assert orchestrator._character_bridge.calls == ["你好"]
    finally:
        gateway.settings.character_runtime_url = ""


# 8 ─ 原始媒体不进长期记忆 ----------------------------------------------------
def test_raw_media_never_enters_long_term_memory():
    class LeakyLLM(MockBehaviorLLM):
        def decide(self, event, persona_, world, current_template, interruptible):
            return BehaviorDecision(
                selected_intent="remember",
                emotional_read="",
                plan_delta="insert",
                impact=ImpactLevel.MEDIUM,
                template_to_call=current_template,
                dialogue=[{"agent": "kai", "text": "记下了。", "emotion": "calm"}],
                memory_update={
                    "summary": "user showed me a cup",
                    "media_ref": "/frames/f1.png",
                    "frame": "data:image/png;base64,AAAA",
                    "audio_ref": "/audio/u1.wav",
                    "huge_blob": "x" * 4096,
                },
                reason="test",
            )

    runtime, _ = make_runtime(llm=LeakyLLM())
    runtime.push_event(
        Event(
            t_min=19 * 60 + 1,
            kind=EventKind.USER_UTTERANCE,
            source="user",
            text="看看这个",
            target_agent="kai",
        )
    )
    runtime.run(start_min=19 * 60, duration_min=2)
    episodic = runtime.memory_store.recall("kai", "episodic")
    assert episodic.get("summary") == "user showed me a cup"
    for banned in ("media_ref", "frame", "audio_ref", "huge_blob"):
        assert banned not in episodic, f"{banned} leaked into long-term memory"


# 9 ─ 协议扩展兼容 ------------------------------------------------------------
def test_new_event_kinds_ride_the_wire():
    from engine.server.protocol import decode, encode

    perception_event = PerceptionEvent(
        kind="object_detected",
        modality="vision",
        timestamp=1.0,
        captured_at=1.0,
        source_body="cam",
        text="cup detected",
        confidence=0.9,
        media_ref="f.png",
    )
    wire = to_wire_event(perception_event)
    back = decode(encode(wire))
    assert back.kind == "object_detected"
    assert back.payload["perception"] is True
    assert back.payload["event_id"] == perception_event.event_id
    assert EventKind(back.kind) is EventKind.OBJECT_DETECTED
