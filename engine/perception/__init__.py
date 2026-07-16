"""Multimodal Perception Runtime: camera/mic -> structured events -> Character Runtime."""

from engine.perception.models import (
    AuditoryObservation,
    DetectedEntity,
    Modality,
    PerceptionEvent,
    SceneState,
    SpatialRelation,
    SpeakerObservation,
    VisualObservation,
    PERCEPTION_EVENT_KINDS,
)
from engine.perception.sources import (
    AudioChunk,
    CameraHAL,
    CameraSource,
    FileCameraSource,
    Frame,
    MicrophoneHAL,
    MicrophoneSource,
    MuJoCoStateSource,
    RecordedAudioSource,
)
from engine.perception.vision import (
    ChangeDetector,
    InvalidImageError,
    LocalVisionProvider,
    MockVisionProvider,
    RemoteVLMProvider,
    VisionGate,
    VisionProvider,
    validate_image,
)
from engine.perception.audio import (
    ASRProvider,
    BargeInController,
    InvalidAudioError,
    MockASRProvider,
    MockSoundEvents,
    MockVAD,
    SelfVoiceFilter,
    normalize_chunk,
    run_audio_pipeline,
)
from engine.perception.fusion import EntityTracker, PerceptionFusion
from engine.perception.runtime import (
    HazardConfirmationPolicy,
    PerceptionMetrics,
    PerceptionRuntime,
)
from engine.perception.attestation import sign_hazard_claim, verify_hazard_claim
from engine.perception.sink import RuntimePerceptionSink


def to_wire_event(event: PerceptionEvent):
    """PerceptionEvent -> protocol WireEvent. Media stays a reference; the
    payload is marked perception=True so the planner's deterministic guards
    (confidence clamp, memory sanitization) recognize it."""
    from engine.server.protocol import Event as WireEvent

    source = event.source_body or "perception"
    payload = {
        # Provider extras are untrusted and therefore come first; canonical
        # envelope fields below cannot be overwritten by a provider.
        **event.payload,
        "perception": True,
        "event_id": event.event_id,
        "modality": event.modality.value,
        "captured_at": event.captured_at,
        "confidence": event.confidence,
        "entities": [
            {"entity_id": e.entity_id, "label": e.label, "confidence": e.confidence}
            for e in event.entities
        ],
        "relations": [
            {"subject": r.subject_id, "relation": r.relation, "object": r.object_id}
            for r in event.spatial_relations
        ],
        "media_ref": event.media_ref,  # transient; never enters memory
        "privacy_class": event.privacy_class,
        "expires_at": event.expires_at,
    }
    # Never forward a caller-supplied signature.  Only the trusted producer can
    # mint one, and absence of a configured key intentionally fails closed.
    payload.pop("hazard_attestation", None)
    attestation = sign_hazard_claim(payload, source, event.target_agent)
    if attestation is not None:
        payload["hazard_attestation"] = attestation
    return WireEvent(
        kind=event.kind,
        source=source,
        text=event.text,
        target_agent=event.target_agent,
        payload=payload,
    )


__all__ = [
    "ASRProvider",
    "AudioChunk",
    "AuditoryObservation",
    "BargeInController",
    "CameraHAL",
    "CameraSource",
    "ChangeDetector",
    "DetectedEntity",
    "EntityTracker",
    "FileCameraSource",
    "Frame",
    "HazardConfirmationPolicy",
    "InvalidAudioError",
    "InvalidImageError",
    "LocalVisionProvider",
    "MicrophoneHAL",
    "MicrophoneSource",
    "MockASRProvider",
    "MockSoundEvents",
    "MockVAD",
    "MockVisionProvider",
    "Modality",
    "MuJoCoStateSource",
    "PERCEPTION_EVENT_KINDS",
    "PerceptionEvent",
    "PerceptionFusion",
    "PerceptionMetrics",
    "PerceptionRuntime",
    "RecordedAudioSource",
    "RemoteVLMProvider",
    "RuntimePerceptionSink",
    "SceneState",
    "SelfVoiceFilter",
    "SpatialRelation",
    "SpeakerObservation",
    "VisionGate",
    "VisionProvider",
    "VisualObservation",
    "normalize_chunk",
    "run_audio_pipeline",
    "sign_hazard_claim",
    "to_wire_event",
    "validate_image",
    "verify_hazard_claim",
]
