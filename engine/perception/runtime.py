"""PerceptionRuntime: sources -> gate -> providers -> fusion -> Character Runtime.

Lifecycle-owned, bounded queues, provider timeouts, health/metrics/trace.
Everything perception emits is UNTRUSTED input; hazard suspicions go through a
confirmation policy before they may carry any severity, and low-confidence
events can never trigger dangerous physical action (deterministically enforced
again inside the planner runtime).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from engine.perception.fusion import PerceptionFusion
from engine.perception.models import Modality, PerceptionEvent
from engine.perception.sources import CameraSource, Frame, MicrophoneSource
from engine.perception.vision import (
    ChangeDetector, InvalidImageError, VisionGate, VisionProvider,
    analyze_with_timeout, validate_image,
)
from engine.perception import audio as audio_mod
from engine.perception.models import HAZARD_LABELS


@dataclass
class HazardConfirmationPolicy:
    """Single frames never declare an emergency: a hazard label must repeat
    `required_hits` times within `window_s` before an event may carry
    severity=critical — and even then execution still passes the planner's
    deterministic safe-stop path, never a free-form LLM improvisation."""

    required_hits: int = 3
    window_s: float = 5.0
    _hits: dict[str, deque] = field(default_factory=dict)

    def observe(self, label: str, ts: float) -> bool:
        """Returns True only when the hazard is CONFIRMED."""
        bucket = self._hits.setdefault(label, deque())
        bucket.append(ts)
        while bucket and ts - bucket[0] > self.window_s:
            bucket.popleft()
        return len(bucket) >= self.required_hits

    def evidence(self, label: str, ts: float) -> dict[str, float | int]:
        """Return auditable evidence for a decision made at ``ts``."""
        bucket = self._hits.get(label, deque())
        hits = [hit for hit in bucket if ts - hit <= self.window_s]
        return {
            "hazard_confirmation_hits": len(hits),
            "hazard_confirmation_required_hits": self.required_hits,
            "hazard_confirmation_window_s": self.window_s,
        }


@dataclass
class PerceptionMetrics:
    frames_seen: int = 0
    frames_analyzed: int = 0
    frames_gated_out: int = 0
    invalid_frames: int = 0
    provider_timeouts: int = 0
    events_emitted: int = 0
    events_dropped_backpressure: int = 0
    events_dropped_expired: int = 0
    audio_chunks: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class PerceptionRuntime:
    fusion: PerceptionFusion = field(default_factory=PerceptionFusion)
    vision_provider: VisionProvider | None = None
    vision_gate: VisionGate = field(default_factory=lambda: VisionGate(
        change=ChangeDetector(), min_interval_s=1.0))
    provider_timeout_s: float = 5.0
    queue_limit: int = 128
    emit: Callable[[PerceptionEvent], None] | None = None   # -> Character Runtime
    hazards: HazardConfirmationPolicy = field(default_factory=HazardConfirmationPolicy)
    metrics: PerceptionMetrics = field(default_factory=PerceptionMetrics)
    trace: deque = field(default_factory=lambda: deque(maxlen=2000))
    _queue: deque = field(default_factory=deque)
    _running: bool = False

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._running = True
        self._log("lifecycle", {"state": "started"})

    def stop(self) -> None:
        self._running = False
        self._log("lifecycle", {"state": "stopped"})

    def health(self) -> dict[str, Any]:
        return {"running": self._running, "queue_depth": len(self._queue),
                **self.metrics.as_dict()}

    # --------------------------------------------------------------- vision
    def process_frame(self, frame: Frame, *, now: float | None = None) -> list[PerceptionEvent]:
        self.metrics.frames_seen += 1
        try:
            validate_image(frame)
        except InvalidImageError as exc:
            self.metrics.invalid_frames += 1
            return self._emit_all([self._error_event(f"invalid image: {exc}", frame.ref)])

        if not self.vision_gate.should_analyze(frame, now=now):
            self.metrics.frames_gated_out += 1
            return []

        provider = self.vision_provider
        if provider is None:
            return []
        observation = analyze_with_timeout(provider, frame, self.provider_timeout_s)
        if observation is None:
            self.metrics.provider_timeouts += 1
            return self._emit_all([self._error_event("vision provider timeout/failure",
                                                     frame.ref)])
        self.metrics.frames_analyzed += 1
        events = self.fusion.ingest_visual(observation)
        events = [self._apply_hazard_policy(e) for e in events]
        return self._emit_all([e for e in events if e is not None])

    # ---------------------------------------------------------------- audio
    def process_audio(self, observation) -> list[PerceptionEvent]:
        self.metrics.audio_chunks += 1
        events = self.fusion.ingest_auditory(observation)
        return self._emit_all(events)

    def run_camera(self, camera: CameraSource) -> list[PerceptionEvent]:
        """Drain a (finite fixture) camera source synchronously."""
        out: list[PerceptionEvent] = []
        for frame in camera.frames():
            out.extend(self.process_frame(frame, now=frame.ts))
        return out

    def run_microphone(self, microphone: MicrophoneSource,
                       vad=None, asr=None, sounds=None,
                       barge_in: audio_mod.BargeInController | None = None,
                       ) -> list[PerceptionEvent]:
        vad = vad or audio_mod.MockVAD()
        asr = asr or audio_mod.MockASRProvider()
        sounds = sounds if sounds is not None else audio_mod.MockSoundEvents()
        out: list[PerceptionEvent] = []
        for observation in audio_mod.run_audio_pipeline(
                microphone.chunks(), vad, asr, sounds, barge_in=barge_in):
            out.extend(self.process_audio(observation))
        return out

    # ------------------------------------------------------------- internals
    def _apply_hazard_policy(self, event: PerceptionEvent) -> PerceptionEvent | None:
        hazard_labels = [e.label for e in event.entities if e.label in HAZARD_LABELS]
        if not hazard_labels:
            return event
        label = hazard_labels[0]
        confirmed = self.hazards.observe(label, event.timestamp)
        if not confirmed:
            self._log("hazard_pending", {"label": label, "ts": event.timestamp})
            return None                      # unconfirmed suspicion: not surfaced
        event.kind = "scene_changed"
        event.payload["severity"] = "critical"
        event.payload["hazard_confirmed"] = label
        event.payload.update(self.hazards.evidence(label, event.timestamp))
        return event

    def _error_event(self, detail: str, media_ref: str) -> PerceptionEvent:
        return PerceptionEvent(
            kind="perception_error", modality=Modality.VISION,
            timestamp=time.monotonic(), captured_at=time.monotonic(),
            source_body=self.fusion.source_body, text=detail,
            confidence=1.0, media_ref=media_ref, privacy_class="ephemeral",
        )

    def _emit_all(self, events: list[PerceptionEvent]) -> list[PerceptionEvent]:
        # Retry anything a previous push consumer left at the head before
        # accepting new input.  In the normal synchronous path this is empty.
        delivered = self.drain(consumer=self.emit)
        for event in events:
            if event.expires_at is not None and event.expires_at <= time.monotonic():
                self.metrics.events_dropped_expired += 1
                self._log("expired_drop", {"kind": event.kind, "event_id": event.event_id})
                continue
            if len(self._queue) >= self.queue_limit:
                self.metrics.events_dropped_backpressure += 1
                self._log("backpressure_drop", {"kind": event.kind})
                continue
            self._queue.append(event)
            self.metrics.events_emitted += 1
            self._log("emit", {"kind": event.kind, "text": event.text[:60],
                               "confidence": event.confidence})
            delivered.extend(self.drain(max_events=1, consumer=self.emit))
        # process_* is a synchronous API: its returned list is the pull
        # consumer.  A configured callback is the equivalent push consumer.
        # Either way accepted events leave the bounded queue exactly once.
        return delivered

    def drain(self, max_events: int | None = None,
              *, consumer: Callable[[PerceptionEvent], None] | None = None,
              ) -> list[PerceptionEvent]:
        """Consume queued events in FIFO order.

        ``process_frame``/``process_audio`` call this automatically, preserving
        their existing returned-list API.  The public method also makes retry
        semantics explicit: if a push consumer raises, the failing event remains
        at the head of the queue for a later drain.
        """
        if max_events is not None and max_events < 0:
            raise ValueError("max_events must be non-negative or None")
        delivered: list[PerceptionEvent] = []
        remaining = len(self._queue) if max_events is None else max_events
        while self._queue and remaining > 0:
            event = self._queue[0]
            if consumer is not None:
                consumer(event)
            delivered.append(self._queue.popleft())
            remaining -= 1
        return delivered

    def _log(self, kind: str, detail: dict[str, Any]) -> None:
        self.trace.append({"ts": time.monotonic(), "kind": kind, **detail})
