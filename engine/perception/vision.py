"""Vision pipeline: validation, frame gating, pluggable providers.

Cloud VLMs are never called per-frame. A frame reaches a provider only when
the gate opens: significant change, novel entity, gesture, an explicit
planner request, or a local detector that is not confident enough.
"""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
import pickle
import time
import urllib.request
from urllib.parse import urlparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from engine.perception.models import DetectedEntity, SpatialRelation, VisualObservation
from engine.perception.sources import Frame

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VLM_RESPONSE_BYTES = 2 * 1024 * 1024
_MAGIC = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg", b"RIFF": "webp"}

# Wire contract requested from a remote VLM.  Validation below is deliberately
# implemented without a heavyweight jsonschema runtime dependency.
REMOTE_VLM_SCHEMA_VERSION = "soulforge.visual.v1"
REMOTE_VLM_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "entities", "relations"],
    "properties": {
        "schema_version": {"const": REMOTE_VLM_SCHEMA_VERSION},
        "scene": {"type": "string"},
        "ocr_text": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "confidence"],
                "properties": {
                    "entity_id": {"type": "string"},
                    "label": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "bbox": {
                        "type": ["array", "null"],
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "attributes": {"type": "object"},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["subject", "relation", "object", "confidence"],
            },
        },
    },
}


class InvalidImageError(ValueError):
    pass


def validate_image(frame: Frame) -> str:
    """Size + magic-byte format check. Returns the detected format."""
    if frame.data is None:
        return "reference-only"
    if len(frame.data) == 0:
        raise InvalidImageError("empty image")
    if len(frame.data) > MAX_IMAGE_BYTES:
        raise InvalidImageError(f"image too large: {len(frame.data)} bytes")
    for magic, fmt in _MAGIC.items():
        if frame.data.startswith(magic):
            return fmt
    raise InvalidImageError("unrecognized image format (png/jpeg/webp expected)")


@dataclass
class ChangeDetector:
    """Cheap byte-sample frame distance in [0,1].

    This is deliberately not a cryptographic digest: digest avalanche turns a
    one-byte camera/codec fluctuation into an apparent 100% scene change.
    """

    threshold: float = 0.08
    sample_size: int = 512
    _last_sample: tuple[int, ...] | None = None
    _last_size: int | None = None

    def _sample(self, data: bytes) -> tuple[int, ...]:
        count = min(max(self.sample_size, 1), len(data))
        if count == 1:
            return (data[0],)
        last = len(data) - 1
        return tuple(data[(index * last) // (count - 1)] for index in range(count))

    def score(self, frame: Frame) -> float:
        if frame.data is None:
            return 1.0  # state-based frames: caller gates
        sample = self._sample(frame.data)
        size = len(frame.data)
        if self._last_sample is None:
            self._last_sample = sample
            self._last_size = size
            return 1.0
        previous = self._last_sample
        paired = min(len(sample), len(previous))
        content_diff = (
            sum(sample[index] != previous[index] for index in range(paired)) / paired
            if paired
            else 1.0
        )
        previous_size = self._last_size or 0
        size_diff = abs(size - previous_size) / max(size, previous_size, 1)
        self._last_sample = sample
        self._last_size = size
        return min(1.0, max(content_diff, size_diff))

    def changed(self, frame: Frame) -> bool:
        return self.score(frame) >= self.threshold


@runtime_checkable
class VisionProvider(Protocol):
    name: str

    def analyze(self, frame: Frame) -> VisualObservation:
        """Turn one frame into a structured observation. May raise/time out."""


class MockVisionProvider:
    """Deterministic provider for tests/offline demos: reads ground truth from
    the fixture's JSON sidecar ({entities:[{label,confidence,bbox?,attributes?}],
    relations:[...], scene, ocr_text, gesture})."""

    name = "mock"

    def analyze(self, frame: Frame) -> VisualObservation:
        return _observation_from_payload(frame.sidecar or {}, frame, self.name)


class LocalVisionProvider:
    """Adapter for an injected on-device detector.

    The detector receives a validated :class:`Frame` and returns either the
    canonical mapping used by the mock/remote providers or a VisualObservation.
    Model loading remains the application's responsibility, so this adapter has
    no hidden framework dependency.
    """

    name = "local"

    def __init__(
        self, detector: Callable[[Frame], Mapping[str, Any] | VisualObservation]
    ):
        if not callable(detector):
            raise TypeError("LocalVisionProvider detector must be callable")
        self.detector = detector

    def analyze(self, frame: Frame) -> VisualObservation:
        validate_image(frame)
        result = self.detector(frame)
        if isinstance(result, VisualObservation):
            result.ts = frame.ts
            result.frame_ref = frame.ref
            result.provider = self.name
            return result
        return _observation_from_payload(result, frame, self.name)


class RemoteVLMProvider:
    """Credential-gated HTTP+JSON cloud VLM adapter.

    The endpoint is expected to accept the request schema sent under
    ``response_format.json_schema`` and return ``soulforge.visual.v1`` JSON.
    Invalid configuration, non-JSON responses and schema violations fail
    closed by raising; PerceptionRuntime converts those failures into a
    perception_error event.
    """

    name = "remote-vlm"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "",
        model: str = "",
        timeout_s: float = 8.0,
        transport: Callable[
            [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
        ]
        | None = None,
    ):
        api_key = api_key or os.environ.get("VLM_API_KEY", "")
        if not api_key:
            raise RuntimeError("RemoteVLMProvider requires VLM_API_KEY")
        base_url = base_url or os.environ.get("VLM_BASE_URL", "")
        model = model or os.environ.get("VLM_MODEL", "")
        if not base_url:
            raise RuntimeError("RemoteVLMProvider requires VLM_BASE_URL")
        if not model:
            raise RuntimeError("RemoteVLMProvider requires VLM_MODEL")
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError("RemoteVLMProvider base_url must be an HTTP(S) URL")
        if timeout_s <= 0:
            raise ValueError("RemoteVLMProvider timeout_s must be positive")
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout_s = timeout_s
        self.transport = transport or _post_json

    def analyze(self, frame: Frame) -> VisualObservation:
        media_type = validate_image(frame)
        image: dict[str, Any] = {"ref": frame.ref, "media_type": media_type}
        if frame.data is not None:
            image["data_base64"] = base64.b64encode(frame.data).decode("ascii")
        request_payload = {
            "model": self.model,
            "input": {"image": image},
            "response_format": {
                "type": "json_schema",
                "json_schema": REMOTE_VLM_RESPONSE_SCHEMA,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        response = self.transport(
            self.base_url,
            headers,
            request_payload,
            self.timeout_s,
        )
        return _observation_from_payload(
            response,
            frame,
            self.name,
            require_schema_version=True,
        )


def _confidence(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number")
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{field_name} must be within [0,1]")
    return confidence


def _observation_from_payload(
    payload: Mapping[str, Any],
    frame: Frame,
    provider_name: str,
    *,
    require_schema_version: bool = False,
) -> VisualObservation:
    if not isinstance(payload, Mapping):
        raise ValueError("vision provider response must be a JSON object")
    if (
        require_schema_version
        and payload.get("schema_version") != REMOTE_VLM_SCHEMA_VERSION
    ):
        raise ValueError(
            f"vision response schema_version must be {REMOTE_VLM_SCHEMA_VERSION!r}"
        )
    if require_schema_version and (
        "entities" not in payload or "relations" not in payload
    ):
        raise ValueError("vision response must include entities and relations")

    raw_entities = payload.get("entities", [])
    raw_relations = payload.get("relations", [])
    if not isinstance(raw_entities, list) or not isinstance(raw_relations, list):
        raise ValueError("vision response entities and relations must be arrays")

    entities: list[DetectedEntity] = []
    for index, raw in enumerate(raw_entities):
        if not isinstance(raw, Mapping):
            raise ValueError(f"entities[{index}] must be an object")
        label = raw.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"entities[{index}].label must be a non-empty string")
        if require_schema_version and "confidence" not in raw:
            raise ValueError(f"entities[{index}].confidence is required")
        entity_id = raw.get("entity_id", f"e{index}")
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError(f"entities[{index}].entity_id must be a string")
        bbox = raw.get("bbox")
        if bbox is not None:
            if (
                not isinstance(bbox, (list, tuple))
                or len(bbox) != 4
                or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in bbox
                )
            ):
                raise ValueError(f"entities[{index}].bbox must contain four numbers")
            bbox = tuple(float(value) for value in bbox)
            if any(value < 0.0 or value > 1.0 for value in bbox):
                raise ValueError(f"entities[{index}].bbox must be normalized to [0,1]")
        attributes = raw.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise ValueError(f"entities[{index}].attributes must be an object")
        entities.append(
            DetectedEntity(
                entity_id=entity_id,
                label=label,
                confidence=_confidence(
                    raw.get("confidence", 0.9), f"entities[{index}].confidence"
                ),
                bbox=bbox,
                attributes=dict(attributes),
                last_seen_ts=frame.ts,
            )
        )

    relations: list[SpatialRelation] = []
    for index, raw in enumerate(raw_relations):
        if not isinstance(raw, Mapping):
            raise ValueError(f"relations[{index}] must be an object")
        values = [raw.get("subject"), raw.get("relation"), raw.get("object")]
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(
                f"relations[{index}] subject/relation/object must be non-empty strings"
            )
        if require_schema_version and "confidence" not in raw:
            raise ValueError(f"relations[{index}].confidence is required")
        relations.append(
            SpatialRelation(
                values[0],
                values[1],
                values[2],
                _confidence(
                    raw.get("confidence", 0.9), f"relations[{index}].confidence"
                ),
            )
        )

    scene = payload.get("scene", "")
    ocr_text = payload.get("ocr_text", "")
    if not isinstance(scene, str) or not isinstance(ocr_text, str):
        raise ValueError("vision response scene and ocr_text must be strings")
    default_confidence = min((entity.confidence for entity in entities), default=1.0)
    return VisualObservation(
        ts=frame.ts,
        frame_ref=frame.ref,
        entities=entities,
        relations=relations,
        scene_label=scene,
        ocr_text=ocr_text,
        provider=provider_name,
        confidence=_confidence(
            payload.get("confidence", default_confidence), "confidence"
        ),
    )


def _post_json(
    url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout_s: float
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        raw = response.read(MAX_VLM_RESPONSE_BYTES + 1)
        if len(raw) > MAX_VLM_RESPONSE_BYTES:
            raise ValueError("remote VLM response is too large")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("remote VLM response must be UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("remote VLM response must be a JSON object")
    return decoded


@dataclass
class VisionGate:
    """Decides whether a frame deserves (expensive) semantic analysis."""

    change: ChangeDetector = field(default_factory=ChangeDetector)
    min_interval_s: float = 1.0  # provider rate limit
    _last_call_ts: float = -1e9
    planner_request: bool = False  # planner asked "look now"

    def request_observation(self) -> None:
        self.planner_request = True

    def should_analyze(
        self,
        frame: Frame,
        *,
        novel_entity: bool = False,
        gesture: bool = False,
        low_local_confidence: bool = False,
        now: float | None = None,
    ) -> bool:
        now = time.monotonic() if now is None else now
        if now - self._last_call_ts < self.min_interval_s:
            return False
        trigger = (
            self.planner_request
            or novel_entity
            or gesture
            or low_local_confidence
            or self.change.changed(frame)
        )
        if trigger:
            self._last_call_ts = now
            self.planner_request = False
        return trigger


def analyze_with_timeout(
    provider: VisionProvider, frame: Frame, timeout_s: float = 5.0
) -> VisualObservation | None:
    """Run a provider in an isolated process with a hard timeout.

    Threads cannot be killed in Python: cancelling a running Future merely
    hides it while the worker keeps the interpreter alive.  A short-lived
    process costs a little more but can be terminated deterministically when a
    remote SDK or native model hangs.  None means failure/timeout.

    Providers must be serializable so a safe spawn/fork-server process can own
    them.  An unpicklable closure fails closed instead of falling back to an
    unkillable thread or unsafe fork from a multi-threaded runtime.
    """
    try:
        pickle.dumps((provider, frame))
    except Exception:
        return None
    methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context(
        "forkserver" if "forkserver" in methods else "spawn"
    )
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_provider_process_entry, args=(provider, frame, send), daemon=True
    )
    started = False
    try:
        process.start()
        started = True
        send.close()
        if receive.poll(max(0.0, timeout_s)):
            status, payload = receive.recv()
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)
            return payload if status == "ok" else None
        return None
    except Exception:
        return None
    finally:
        receive.close()
        send.close()
        if started:
            if process.is_alive():
                process.terminate()
            process.join(timeout=0.5)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=0.5)


def _provider_process_entry(provider: VisionProvider, frame: Frame, connection) -> None:
    """Child-process entrypoint kept at module scope for spawn compatibility."""
    try:
        connection.send(("ok", provider.analyze(frame)))
    except BaseException as exc:  # provider failures are data, not child crashes
        try:
            connection.send(("error", f"{type(exc).__name__}: {exc}"))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()
