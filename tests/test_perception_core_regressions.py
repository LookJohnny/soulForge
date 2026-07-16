"""Regression coverage for the Phase-6 perception-core acceptance blockers."""

from __future__ import annotations

import multiprocessing
import time

import pytest

from engine.perception.fusion import EntityTracker, PerceptionFusion
from engine.perception.models import (
    AuditoryObservation,
    DetectedEntity,
    SpeakerObservation,
    SpatialRelation,
    VisualObservation,
)
from engine.perception.runtime import HazardConfirmationPolicy, PerceptionRuntime
from engine.perception.sources import Frame
from engine.perception.vision import (
    ChangeDetector,
    LocalVisionProvider,
    MockVisionProvider,
    REMOTE_VLM_SCHEMA_VERSION,
    RemoteVLMProvider,
    analyze_with_timeout,
)


class _HangingProvider:
    name = "hangs"

    def analyze(self, frame):
        time.sleep(5.0)
        raise AssertionError("provider should have been terminated")


class _FastProvider:
    name = "fast"

    def analyze(self, frame):
        return VisualObservation(ts=frame.ts, frame_ref=frame.ref, provider=self.name)


def _entity(label: str, bbox, confidence: float = 0.9) -> DetectedEntity:
    return DetectedEntity("input", label, confidence, bbox=bbox)


def test_tracker_keeps_spatially_distinct_same_label_objects_separate():
    tracker = EntityTracker(iou_threshold=0.3)
    first = tracker.track(
        [
            _entity("cup", (0.05, 0.1, 0.1, 0.1)),
            _entity("cup", (0.80, 0.1, 0.1, 0.1)),
        ],
        ts=0.0,
    )
    assert len({entity.entity_id for entity in first}) == 2

    repeated = tracker.track(
        [
            _entity("cup", (0.06, 0.1, 0.1, 0.1)),
            _entity("cup", (0.79, 0.1, 0.1, 0.1)),
        ],
        ts=1.0,
    )
    assert [entity.entity_id for entity in repeated] == [
        entity.entity_id for entity in first
    ]

    new_location = tracker.track(
        [_entity("cup", (0.40, 0.75, 0.1, 0.1))],
        ts=2.0,
    )
    assert new_location[0].entity_id not in {entity.entity_id for entity in first}


def test_deictic_fusion_confidence_is_bounded_by_visual_grounding():
    fusion = PerceptionFusion(min_confidence=0.5, debounce_s=0.0)
    visual = VisualObservation(
        ts=1.0,
        frame_ref="weak.png",
        entities=[_entity("cup", (0.5, 0.5, 0.1, 0.1), confidence=0.51)],
        confidence=0.51,
    )
    fusion.ingest_visual(visual)
    event = fusion.ingest_auditory(
        AuditoryObservation(
            ts=1.1,
            kind="speech",
            transcript="把那个递给我",
            speaker=SpeakerObservation("user"),
            confidence=0.99,
        )
    )[0]

    assert event.payload["referent_label"] == "cup"
    assert event.payload["grounding_confidence"] == pytest.approx(0.51)
    assert event.confidence == pytest.approx(0.51)


def test_tracker_remaps_provider_relation_ids_before_deictic_resolution():
    fusion = PerceptionFusion(min_confidence=0.5, debounce_s=0.0)
    fusion.ingest_visual(
        VisualObservation(
            ts=1.0,
            frame_ref="two-cups.png",
            entities=[
                DetectedEntity("provider-left", "cup", 0.9, bbox=(0.05, 0.2, 0.1, 0.1)),
                DetectedEntity("provider-right", "cup", 0.8, bbox=(0.8, 0.2, 0.1, 0.1)),
            ],
            relations=[
                SpatialRelation(
                    "user-hand",
                    "pointing_at",
                    "provider-right",
                    confidence=0.85,
                )
            ],
            confidence=0.9,
        )
    )

    event = fusion.ingest_auditory(
        AuditoryObservation(
            ts=1.1,
            kind="speech",
            transcript="把那个递给我",
            speaker=SpeakerObservation("user"),
            confidence=0.95,
        )
    )[0]
    tracked_ids = [entity.entity_id for entity in event.entities]
    assert len(set(tracked_ids)) == 2
    assert event.payload["referent_entity_id"] == tracked_ids[1]
    assert event.payload["grounding_confidence"] == pytest.approx(0.8)


def test_synchronous_pull_mode_does_not_fill_bounded_queue():
    runtime = PerceptionRuntime(queue_limit=3)
    speaker = SpeakerObservation("user")

    for index in range(10_000):
        events = runtime.process_audio(
            AuditoryObservation(
                ts=float(index),
                kind="speech",
                transcript=f"event {index}",
                speaker=speaker,
                confidence=0.9,
            )
        )
        assert len(events) == 1

    assert runtime.health()["queue_depth"] == 0
    assert runtime.metrics.events_emitted == 10_000
    assert runtime.metrics.events_dropped_backpressure == 0


def test_expired_ephemeral_event_is_not_delivered():
    runtime = PerceptionRuntime()
    observation = AuditoryObservation(
        ts=0.0,
        kind="speech",
        transcript="stale",
        speaker=SpeakerObservation("user"),
        confidence=0.9,
    )
    event = runtime.fusion.ingest_auditory(observation)[0]
    event.expires_at = time.monotonic() - 1

    assert runtime._emit_all([event]) == []
    assert runtime.metrics.events_dropped_expired == 1


def test_failed_push_consumer_leaves_one_retryable_fifo_event():
    runtime = PerceptionRuntime(queue_limit=3)

    def fail(_event):
        raise RuntimeError("sink offline")

    runtime.emit = fail
    observation = AuditoryObservation(
        ts=0.0,
        kind="speech",
        transcript="hello",
        speaker=SpeakerObservation("user"),
        confidence=0.9,
    )
    with pytest.raises(RuntimeError, match="sink offline"):
        runtime.process_audio(observation)

    assert runtime.health()["queue_depth"] == 1
    runtime.emit = None
    drained = runtime.drain()
    assert [event.text for event in drained] == ["hello"]
    assert runtime.health()["queue_depth"] == 0


def test_change_detector_ignores_one_byte_noise_but_sees_broad_change():
    detector = ChangeDetector(threshold=0.12, sample_size=512)
    original = bytearray(b"\x89PNG" + b"\x00" * 2044)
    noisy = bytearray(original)
    noisy[1024] = 1
    changed = bytearray(b"\x89PNG" + b"\xff" * 2044)

    assert detector.score(Frame(0.0, "a.png", bytes(original))) == 1.0
    assert detector.score(Frame(1.0, "b.png", bytes(noisy))) < detector.threshold
    assert detector.changed(Frame(2.0, "c.png", bytes(changed)))


def test_runtime_default_vision_gate_has_rate_limit():
    runtime = PerceptionRuntime()
    assert runtime.vision_gate.min_interval_s >= 1.0


def test_provider_timeout_is_hard_and_leaves_no_children():
    baseline = {child.pid for child in multiprocessing.active_children()}
    frame = Frame(0.0, "frame://timeout", data=None)
    started = time.monotonic()

    for _ in range(4):
        assert analyze_with_timeout(_HangingProvider(), frame, timeout_s=0.03) is None

    elapsed = time.monotonic() - started
    leaked = {child.pid for child in multiprocessing.active_children()} - baseline
    assert elapsed < 1.5
    assert leaked == set()


def test_provider_process_returns_successful_observation():
    frame = Frame(2.0, "frame://fast", data=None)
    observation = analyze_with_timeout(_FastProvider(), frame, timeout_s=1.0)
    assert observation is not None
    assert observation.frame_ref == frame.ref


def test_local_provider_adapts_injected_detector_to_canonical_observation():
    calls = []

    def detector(frame):
        calls.append(frame.ref)
        return {
            "scene": "workbench",
            "entities": [
                {
                    "entity_id": "detector-cup",
                    "label": "cup",
                    "confidence": 0.87,
                    "bbox": [0.1, 0.2, 0.3, 0.4],
                }
            ],
            "relations": [],
        }

    provider = LocalVisionProvider(detector)
    frame = Frame(7.0, "camera://frame-7", data=b"\x89PNGfixture")
    observation = provider.analyze(frame)

    assert calls == [frame.ref]
    assert observation.provider == "local"
    assert observation.scene_label == "workbench"
    assert observation.entities[0].entity_id == "detector-cup"


def test_remote_provider_uses_bounded_json_contract_without_network():
    captured = {}

    def fake_transport(url, headers, payload, timeout_s):
        captured.update(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_s": timeout_s,
            }
        )
        return {
            "schema_version": REMOTE_VLM_SCHEMA_VERSION,
            "scene": "kitchen",
            "confidence": 0.84,
            "entities": [
                {
                    "label": "cup",
                    "confidence": 0.84,
                    "bbox": [0.5, 0.4, 0.1, 0.2],
                }
            ],
            "relations": [],
        }

    provider = RemoteVLMProvider(
        api_key="test-secret",
        base_url="https://vlm.invalid/analyze",
        model="fixture-vlm",
        timeout_s=0.75,
        transport=fake_transport,
    )
    frame = Frame(8.0, "camera://frame-8", data=b"\x89PNGfixture")
    observation = provider.analyze(frame)

    assert captured["url"] == "https://vlm.invalid/analyze"
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
    assert captured["timeout_s"] == 0.75
    assert captured["payload"]["model"] == "fixture-vlm"
    assert captured["payload"]["input"]["image"]["data_base64"]
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert observation.provider == "remote-vlm"
    assert observation.scene_label == "kitchen"
    assert observation.entities[0].label == "cup"


def test_remote_provider_fails_closed_on_config_and_schema(monkeypatch):
    for key in ("VLM_API_KEY", "VLM_BASE_URL", "VLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="VLM_API_KEY"):
        RemoteVLMProvider()

    provider = RemoteVLMProvider(
        api_key="test-secret",
        base_url="https://vlm.invalid/analyze",
        model="fixture-vlm",
        transport=lambda *_args: {
            "schema_version": "wrong-version",
            "entities": [],
            "relations": [],
        },
    )
    with pytest.raises(ValueError, match="schema_version"):
        provider.analyze(Frame(0.0, "camera://bad", data=b"\x89PNGfixture"))


def test_confirmed_hazard_carries_auditable_evidence():
    runtime = PerceptionRuntime(
        vision_provider=MockVisionProvider(),
        hazards=HazardConfirmationPolicy(required_hits=2, window_s=3.0),
    )
    sidecar = {
        "entities": [{"label": "fire_suspected", "confidence": 0.95}],
    }
    frame0 = Frame(0.0, "fixture://hazard-0", data=None, sidecar=sidecar)
    frame1 = Frame(1.0, "fixture://hazard-1", data=None, sidecar=sidecar)

    assert runtime.process_frame(frame0, now=0.0) == []
    confirmed = runtime.process_frame(frame1, now=1.0)
    assert len(confirmed) == 1
    payload = confirmed[0].payload
    assert payload["severity"] == "critical"
    assert payload["hazard_confirmed"] == "fire_suspected"
    assert payload["hazard_confirmation_hits"] == 2
    assert payload["hazard_confirmation_required_hits"] == 2
    assert payload["hazard_confirmation_window_s"] == 3.0
