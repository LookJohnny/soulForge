"""Fusion: join vision and audio on time, track entities, attribute speakers,
debounce, and emit stable PerceptionEvents + SceneState.

Deixis ("把那个递给我") resolves against the fused window: pointing gestures and
gaze relations pick the referent entity, and the emitted event carries its
entity_id so downstream action intents are grounded — grounded, not executed:
fusion never fabricates completed manipulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.perception.models import (
    AuditoryObservation,
    DetectedEntity,
    Modality,
    PerceptionEvent,
    SceneState,
    SpatialRelation,
    VisualObservation,
)

_DEICTIC_MARKERS = ("那个", "这个", "那只", "这只", "it", "that", "this")


@dataclass
class EntityTracker:
    """Stable ids across frames via label + IoU-ish proximity."""

    iou_threshold: float = 0.3
    max_age_s: float = 10.0
    _known: dict[str, DetectedEntity] = field(default_factory=dict)
    _counter: int = 0

    def track(self, entities: list[DetectedEntity], ts: float) -> list[DetectedEntity]:
        # Expire before matching so an object absent beyond max_age_s cannot
        # silently resurrect an ancient identity.
        for entity_id in [
            key
            for key, value in self._known.items()
            if ts - value.last_seen_ts > self.max_age_s
        ]:
            del self._known[entity_id]
        resolved: list[DetectedEntity] = []
        # A track may be assigned at most once in a frame.  Without this guard,
        # two simultaneously visible cups can both reuse the same historical id.
        assigned_ids: set[str] = set()
        for entity in entities:
            match = self._match(entity, excluded_ids=assigned_ids)
            if match is not None:
                match.confidence = entity.confidence
                match.bbox = entity.bbox
                match.attributes.update(entity.attributes)
                match.last_seen_ts = ts
                resolved.append(match)
                assigned_ids.add(match.entity_id)
            else:
                self._counter += 1
                tracked = DetectedEntity(
                    entity_id=f"{entity.label}_{self._counter}",
                    label=entity.label,
                    confidence=entity.confidence,
                    bbox=entity.bbox,
                    attributes=dict(entity.attributes),
                    last_seen_ts=ts,
                )
                self._known[tracked.entity_id] = tracked
                resolved.append(tracked)
                assigned_ids.add(tracked.entity_id)
        return resolved

    def _match(
        self, entity: DetectedEntity, excluded_ids: set[str] | None = None
    ) -> DetectedEntity | None:
        excluded_ids = excluded_ids or set()
        candidates = [
            e
            for e in self._known.values()
            if e.label == entity.label and e.entity_id not in excluded_ids
        ]
        if not candidates:
            return None
        if entity.bbox is None:
            # With no spatial evidence, a same-label track is the best available
            # weak match.  The per-frame exclusion above still prevents collapse.
            return candidates[0]
        best, best_iou = None, 0.0
        for candidate in candidates:
            iou = _iou(entity.bbox, candidate.bbox)
            if iou > best_iou:
                best, best_iou = candidate, iou
        # Spatially disjoint objects are new objects, not a fallback match.
        return best if best_iou >= self.iou_threshold else None


def _iou(a, b) -> float:
    if a is None or b is None:
        return 0.5  # same label, unknown boxes: weak match
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass
class PerceptionFusion:
    source_body: str = "perception-0"
    target_agent: str | None = None
    fusion_window_s: float = 3.0  # audio↔vision join window
    min_confidence: float = 0.5  # below this nothing is emitted
    debounce_s: float = 5.0  # per (kind,label) re-emission gap
    tracker: EntityTracker = field(default_factory=EntityTracker)
    scene: SceneState = field(default_factory=SceneState)
    _recent_visual: list[VisualObservation] = field(default_factory=list)
    _last_emit: dict[tuple[str, str], float] = field(default_factory=dict)

    # ------------------------------------------------------------- ingest
    def ingest_visual(self, observation: VisualObservation) -> list[PerceptionEvent]:
        if observation.confidence < self.min_confidence:
            return []  # low confidence never surfaces
        source_entity_ids = [entity.entity_id for entity in observation.entities]
        tracked = self.tracker.track(observation.entities, observation.ts)
        observation.entities = tracked
        tracked_id_by_source = {
            source_id: entity.entity_id
            for source_id, entity in zip(source_entity_ids, tracked, strict=True)
        }
        observation.relations = [
            SpatialRelation(
                subject_id=tracked_id_by_source.get(
                    relation.subject_id, relation.subject_id
                ),
                relation=relation.relation,
                object_id=tracked_id_by_source.get(
                    relation.object_id, relation.object_id
                ),
                confidence=relation.confidence,
            )
            for relation in observation.relations
        ]
        self._recent_visual.append(observation)
        self._recent_visual = [
            v
            for v in self._recent_visual
            if observation.ts - v.ts <= self.fusion_window_s
        ]

        previous_ids = set(self.scene.entities)
        self.scene.entities = {
            e.entity_id: e
            for e in list(self.scene.entities.values()) + tracked
            if observation.ts - e.last_seen_ts <= self.tracker.max_age_s
        }
        self.scene.relations = observation.relations
        self.scene.updated_ts = observation.ts
        if observation.scene_label:
            self.scene.scene_label = observation.scene_label
        self.scene.user_present = any(
            e.label == "person" for e in self.scene.entities.values()
        )

        from engine.perception.models import HAZARD_LABELS

        events: list[PerceptionEvent] = []
        for entity in tracked:
            is_hazard = entity.label in HAZARD_LABELS
            if entity.entity_id in previous_ids and not is_hazard:
                continue  # not novel (hazards keep counting)
            kind = (
                "person_detected"
                if entity.label == "person"
                else "gesture_detected"
                if entity.label == "gesture"
                else "object_detected"
            )
            if not is_hazard and not self._debounced(
                kind, entity.label, observation.ts
            ):
                continue
            events.append(
                PerceptionEvent(
                    kind=kind,
                    modality=Modality.VISION,
                    timestamp=observation.ts,
                    captured_at=observation.ts,
                    source_body=self.source_body,
                    target_agent=self.target_agent,
                    text=f"{entity.label} detected",
                    entities=[entity],
                    spatial_relations=observation.relations,
                    confidence=min(observation.confidence, entity.confidence),
                    media_ref=observation.frame_ref,
                    payload={
                        "scene": observation.scene_label,
                        "ocr_text_untrusted": observation.ocr_text,
                    },
                )
            )
        return events

    def ingest_auditory(
        self, observation: AuditoryObservation
    ) -> list[PerceptionEvent]:
        if observation.confidence < self.min_confidence:
            return []
        if observation.kind == "sound":
            if not self._debounced(
                "sound_event", observation.sound_label, observation.ts
            ):
                return []
            return [
                PerceptionEvent(
                    kind="sound_event",
                    modality=Modality.AUDIO,
                    timestamp=observation.ts,
                    captured_at=observation.ts,
                    source_body=self.source_body,
                    target_agent=self.target_agent,
                    text=observation.sound_label,
                    confidence=observation.confidence,
                    media_ref=observation.audio_ref,
                )
            ]

        speaker = observation.speaker.speaker_id if observation.speaker else "user"
        self.scene.active_speaker = speaker
        fused = self._fuse_with_vision(observation)
        return [fused]

    # --------------------------------------------------------------- fusion
    def _fuse_with_vision(self, speech: AuditoryObservation) -> PerceptionEvent:
        window = [
            v
            for v in self._recent_visual
            if abs(v.ts - speech.ts) <= self.fusion_window_s
        ]
        entities: list[DetectedEntity] = []
        relations: list[SpatialRelation] = []
        referent: DetectedEntity | None = None

        if window:
            for visual in window:
                entities.extend(visual.entities)
                relations.extend(visual.relations)
            if any(marker in speech.transcript for marker in _DEICTIC_MARKERS):
                referent = self._resolve_deixis(entities, relations)

        payload = {"speaker": speech.speaker.speaker_id if speech.speaker else "user"}
        confidence = speech.confidence
        if window:
            # Multimodal confidence is bounded by the strongest complete visual
            # observation that supports the context.  Audio confidence must never
            # launder weak visual evidence into a high-confidence grounded event.
            visual_support = max(
                min(
                    visual.confidence,
                    max(
                        (entity.confidence for entity in visual.entities),
                        default=visual.confidence,
                    ),
                )
                for visual in window
            )
            confidence = min(confidence, visual_support)
        if referent is not None:
            payload["referent_entity_id"] = referent.entity_id
            payload["referent_label"] = referent.label
            referent_support = max(
                (
                    min(visual.confidence, entity.confidence)
                    for visual in window
                    for entity in visual.entities
                    if entity.entity_id == referent.entity_id
                ),
                default=0.0,
            )
            pointing_support = max(
                (
                    relation.confidence
                    for relation in relations
                    if relation.relation == "pointing_at"
                    and relation.object_id == referent.entity_id
                ),
                default=1.0,
            )
            grounding_confidence = min(referent_support, pointing_support)
            payload["grounding_confidence"] = grounding_confidence
            confidence = min(confidence, grounding_confidence)

        return PerceptionEvent(
            kind="user_utterance" if not window else "multimodal_context",
            modality=Modality.AUDIO if not window else Modality.MULTIMODAL,
            timestamp=speech.ts,
            captured_at=speech.ts,
            source_body=self.source_body,
            target_agent=self.target_agent,
            text=speech.transcript,
            entities=list({e.entity_id: e for e in entities}.values()),
            spatial_relations=relations,
            confidence=confidence,
            media_ref=speech.audio_ref,
            payload=payload,
        )

    def _resolve_deixis(
        self, entities: list[DetectedEntity], relations: list[SpatialRelation]
    ) -> DetectedEntity | None:
        by_id = {e.entity_id: e for e in entities}
        # 1) explicit pointing relation wins
        for relation in relations:
            if relation.relation == "pointing_at" and relation.object_id in by_id:
                return by_id[relation.object_id]
        # 2) otherwise the most salient non-person, non-gesture entity
        candidates = [e for e in entities if e.label not in ("person", "gesture")]
        return max(candidates, key=lambda e: e.confidence, default=None)

    def _debounced(self, kind: str, label: str, ts: float) -> bool:
        key = (kind, label)
        last = self._last_emit.get(key, -1e9)
        if ts - last < self.debounce_s:
            return False
        self._last_emit[key] = ts
        return True
