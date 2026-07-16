"""Capture sources. Real devices only get HAL contracts — no fake drivers.

Test/offline implementations read fixtures: FileCameraSource walks image files
(with optional JSON sidecars describing ground truth for the mock provider);
RecordedAudioSource yields pre-recorded utterances/sounds the same way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol, runtime_checkable


@dataclass
class Frame:
    ts: float
    ref: str                              # path/uri of the frame
    data: bytes | None = None             # present for local providers only
    sidecar: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioChunk:
    ts: float
    ref: str
    pcm: bytes | None = None              # 16k mono s16le when present
    format: str = "pcm_s16le_16k"
    sidecar: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CameraSource(Protocol):
    def frames(self) -> Iterator[Frame]:
        """Yield frames in capture order. May be finite (fixtures) or endless."""

    def close(self) -> None: ...


@runtime_checkable
class MicrophoneSource(Protocol):
    def chunks(self) -> Iterator[AudioChunk]: ...
    def close(self) -> None: ...


# ------------------------------------------------------------------ fixtures
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
_AUDIO_SUFFIXES = (".wav", ".opus", ".pcm", ".ogg")


def _load_sidecar(path: Path) -> dict[str, Any]:
    sidecar = path.with_suffix(path.suffix + ".json")
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text("utf-8"))
        except json.JSONDecodeError:
            return {"sidecar_error": "invalid json"}
    return {}


@dataclass
class FileCameraSource:
    """Deterministic camera: images (sorted) from a fixture directory."""

    directory: str | Path
    fps: float = 1.0

    def frames(self) -> Iterator[Frame]:
        base = Path(self.directory)
        ts = 0.0
        for path in sorted(base.iterdir()) if base.exists() else []:
            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            yield Frame(ts=ts, ref=str(path), data=path.read_bytes(),
                        sidecar=_load_sidecar(path))
            ts += 1.0 / max(self.fps, 1e-6)

    def close(self) -> None:
        return None


@dataclass
class RecordedAudioSource:
    """Deterministic microphone: audio files (sorted) from a fixture directory."""

    directory: str | Path

    def chunks(self) -> Iterator[AudioChunk]:
        base = Path(self.directory)
        ts = 0.0
        for path in sorted(base.iterdir()) if base.exists() else []:
            if path.suffix.lower() not in _AUDIO_SUFFIXES:
                continue
            yield AudioChunk(ts=ts, ref=str(path), pcm=path.read_bytes(),
                             sidecar=_load_sidecar(path))
            ts += 1.0

    def close(self) -> None:
        return None


@dataclass
class MuJoCoStateSource:
    """Digital-twin input: simulator state dicts become deterministic
    'visual' observations without any rendering or VLM guessing."""

    states: list[dict[str, Any]] = field(default_factory=list)

    def frames(self) -> Iterator[Frame]:
        for index, state in enumerate(self.states):
            yield Frame(ts=float(state.get("ts", index)), ref=f"mujoco://state/{index}",
                        data=None, sidecar={"mujoco_state": state})

    def close(self) -> None:
        return None


# ------------------------------------------------------------------ real HAL
@runtime_checkable
class CameraHAL(Protocol):
    """Contract for a real camera driver (V4L2/AVFoundation/CSI...).
    No implementation ships here; bench-validate against hardware."""

    def open(self, device: str, width: int, height: int, fps: float) -> None: ...
    def read_frame(self) -> Frame: ...
    def close(self) -> None: ...


@runtime_checkable
class MicrophoneHAL(Protocol):
    """Contract for a real microphone driver (ALSA/CoreAudio/I2S...)."""

    def open(self, device: str, sample_rate: int, channels: int) -> None: ...
    def read_chunk(self, max_ms: int) -> AudioChunk: ...
    def close(self) -> None: ...
