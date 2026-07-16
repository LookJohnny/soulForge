"""Datamodel for the Multimodal Perception Runtime.

Perception turns the physical/virtual world into STRUCTURED, UNTRUSTED input
for the Character Runtime. Raw media never flows into long-term memory; only
policy-approved structured summaries do (see privacy_class / sanitization).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PERCEPTION_EVENT_KINDS = (
    "user_utterance", "sound_event", "person_detected", "object_detected",
    "gesture_detected", "user_presence", "scene_changed", "multimodal_context",
    "perception_error",
)

PRIVACY_CLASSES = ("public", "household", "sensitive", "ephemeral")

# suspicion labels that must pass the confirmation policy before any severity;
# they are exempt from novelty/debounce suppression so repeats keep counting
HAZARD_LABELS = ("fall_suspected", "fire_suspected", "smoke_suspected")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Modality(str, Enum):
    VISION = "vision"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"


@dataclass
class DetectedEntity:
    entity_id: str                       # stable across frames once tracked
    label: str                           # person / cup / hand ...
    confidence: float
    bbox: tuple[float, float, float, float] | None = None   # x,y,w,h normalized
    attributes: dict[str, Any] = field(default_factory=dict)
    last_seen_ts: float = 0.0


@dataclass
class SpatialRelation:
    subject_id: str
    relation: str                        # on / near / left_of / pointing_at ...
    object_id: str
    confidence: float = 1.0


@dataclass
class VisualObservation:
    ts: float                            # capture timestamp (monotonic seconds)
    frame_ref: str                       # media reference (path/uri) — NOT the bytes
    entities: list[DetectedEntity] = field(default_factory=list)
    relations: list[SpatialRelation] = field(default_factory=list)
    scene_label: str = ""
    ocr_text: str = ""                   # UNTRUSTED — never an instruction channel
    change_score: float = 0.0            # vs previous frame
    provider: str = "mock"
    confidence: float = 1.0


@dataclass
class SpeakerObservation:
    speaker_id: str                      # "user", "speaker_2", agent id for self-voice
    is_self_voice: bool = False          # robot hearing itself
    direction_deg: float | None = None
    confidence: float = 1.0


@dataclass
class AuditoryObservation:
    ts: float
    kind: str                            # speech | sound
    transcript: str = ""                 # UNTRUSTED user speech (ASR)
    sound_label: str = ""                # glass_break / doorbell / footsteps ...
    speaker: SpeakerObservation | None = None
    audio_ref: str = ""                  # media reference — NOT the bytes
    provider: str = "mock"
    confidence: float = 1.0
    is_final: bool = True                # streaming ASR partials are not final


@dataclass
class SceneState:
    """Debounced, tracked, fused view of 'what is around us right now'."""

    updated_ts: float = 0.0
    entities: dict[str, DetectedEntity] = field(default_factory=dict)
    relations: list[SpatialRelation] = field(default_factory=list)
    user_present: bool = False
    active_speaker: str | None = None
    scene_label: str = ""


@dataclass
class PerceptionEvent:
    """The ONLY thing perception hands to the Character Runtime."""

    kind: str                            # one of PERCEPTION_EVENT_KINDS
    modality: Modality
    timestamp: float                     # when the event was emitted
    captured_at: float                   # when the media was captured
    source_body: str = ""
    target_agent: str | None = None
    text: str = ""                       # transcript for utterances; summary otherwise
    entities: list[DetectedEntity] = field(default_factory=list)
    spatial_relations: list[SpatialRelation] = field(default_factory=list)
    confidence: float = 1.0
    payload: dict[str, Any] = field(default_factory=dict)
    media_ref: str = ""                  # reference only; bytes never ride events
    privacy_class: str = "ephemeral"
    expires_at: float | None = None
    event_id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        if isinstance(self.modality, str):
            self.modality = Modality(self.modality)
        if self.kind not in PERCEPTION_EVENT_KINDS:
            raise ValueError(f"unknown perception event kind {self.kind!r}")
        if self.privacy_class not in PRIVACY_CLASSES:
            raise ValueError(f"unknown privacy class {self.privacy_class!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be within [0,1], got {self.confidence}")
