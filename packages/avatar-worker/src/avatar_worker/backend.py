"""Adapter for the exact upstream FlashHead streaming inference implementation.

No models are downloaded here. A worker serves one source image on one CUDA GPU.
The upstream inference module reads its YAML relative to cwd; this dedicated
process switches to the pinned checkout before importing it.
"""

from collections import deque
from dataclasses import dataclass
import base64
import importlib
import io
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image

from avatar_worker import FLASHHEAD_REVISION


@dataclass(frozen=True)
class Geometry:
    sample_rate: int = 16000
    fps: int = 25
    frame_num: int = 33
    motion_frames: int = 5
    cached_audio_seconds: int = 8

    @property
    def frames_per_chunk(self):
        return self.frame_num - self.motion_frames

    @property
    def block_samples(self):
        return self.frames_per_chunk * self.sample_rate // self.fps

    @classmethod
    def for_model(cls, model_type):
        return cls(motion_frames=9 if model_type == "lite" else 5)


@dataclass(frozen=True)
class Settings:
    token: str = ""
    source_image: str = ""
    repo: str = ""
    model_dir: str = ""
    wav2vec_dir: str = ""
    model_type: str = "pro"
    seed: int = 42
    jpeg_quality: int = 85

    @classmethod
    def from_env(cls):
        return cls(token=os.environ.get("AVATAR_WORKER_TOKEN", "").strip(),
                   source_image=os.environ.get("AVATAR_SOURCE_IMAGE", ""),
                   repo=os.environ.get("FLASHHEAD_REPO", ""),
                   model_dir=os.environ.get("MODEL_DIR", ""),
                   wav2vec_dir=os.environ.get("WAV2VEC_DIR", ""),
                   model_type=os.environ.get("MODEL_TYPE", "pro").strip().lower())

    def configured(self):
        return bool(self.token and self.source_image and self.repo and self.model_dir
                    and self.wav2vec_dir and self.model_type in {"pro", "lite"})


class BackendUnavailable(RuntimeError):
    """A fixed, non-sensitive reason code suitable for the health response."""


class FlashHeadBackend:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.geometry = Geometry.for_model(settings.model_type)
        self.cuda_available = None
        self.pipeline = None
        self.api = None
        self.audio = None

    def setup(self):
        if not self.settings.configured():
            raise BackendUnavailable("missing_configuration")
        if os.environ.get("WORLD_SIZE", "1") != "1":
            raise BackendUnavailable("multi_gpu_worker_not_supported")
        try:
            torch = importlib.import_module("torch")
        except ImportError:
            self.cuda_available = False
            raise BackendUnavailable("pytorch_not_installed") from None
        self.cuda_available = torch.cuda.is_available()
        if not self.cuda_available:
            raise BackendUnavailable("cuda_unavailable")
        if not torch.cuda.is_bf16_supported():
            raise BackendUnavailable("cuda_bfloat16_not_supported")

        # Resolve before chdir; model paths are always local and must exist.
        repo = Path(self.settings.repo).expanduser().resolve()
        model = Path(self.settings.model_dir).expanduser().resolve()
        wav2vec = Path(self.settings.wav2vec_dir).expanduser().resolve()
        source = Path(self.settings.source_image).expanduser().resolve()
        if not repo.is_dir() or not model.is_dir() or not wav2vec.is_dir() or not source.is_file():
            raise BackendUnavailable("local_assets_missing")
        try:
            revision = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, timeout=10).stdout.strip()
            clean = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", "flash_head"],
                capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            raise BackendUnavailable("source_revision_unverified") from None
        if revision != FLASHHEAD_REVISION or not clean:
            raise BackendUnavailable("source_revision_mismatch")

        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.chdir(repo)
        sys.path.insert(0, str(repo))
        self.api = importlib.import_module("flash_head.inference")
        if not Path(self.api.__file__).resolve().is_relative_to(repo):
            raise BackendUnavailable("source_import_mismatch")
        self.pipeline = self.api.get_pipeline(world_size=1, ckpt_dir=str(model),
            model_type=self.settings.model_type, wav2vec_dir=str(wav2vec))
        self.api.get_base_data(self.pipeline, cond_image_path_or_dir=str(source),
                              base_seed=self.settings.seed, use_face_crop=False)
        params = self.api.get_infer_params()
        actual = Geometry(sample_rate=params["sample_rate"], fps=params["tgt_fps"],
            frame_num=params["frame_num"], motion_frames=params["motion_frames_num"],
            cached_audio_seconds=params["cached_audio_duration"])
        if actual != self.geometry:
            raise BackendUnavailable("upstream_geometry_mismatch")
        self.reset()

    def reset(self):
        # The official reset clears latent motion while preserving the encoded
        # reference image; reseed and clear audio to isolate different requests.
        self.pipeline.reset_person_name()
        self.pipeline.generator.manual_seed(self.settings.seed)
        length = self.geometry.cached_audio_seconds * self.geometry.sample_rate
        self.audio = deque([0.0] * length, maxlen=length)

    def render_block(self, pcm: bytes) -> list[str]:
        geometry = self.geometry
        if len(pcm) != geometry.block_samples * 2:
            raise ValueError("Incorrect PCM block size")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        self.audio.extend(samples.tolist())
        end = geometry.cached_audio_seconds * geometry.fps
        embedding = self.api.get_audio_embedding(self.pipeline,
            np.asarray(self.audio, dtype=np.float32), end - geometry.frame_num, end)
        frames = self.api.run_pipeline(self.pipeline, embedding)
        if tuple(frames.shape) != (geometry.frame_num, 512, 512, 3):
            raise RuntimeError("Unexpected upstream frame geometry")
        # In streaming mode even the FIRST block drops the historical overlap.
        # Pro: 33 - 5 = 28 frames. Lite: 33 - 9 = 24 frames.
        frames = frames[geometry.motion_frames:].cpu().numpy().astype(np.uint8)
        result = []
        for frame in frames:
            buffer = io.BytesIO()
            Image.fromarray(frame).save(buffer, format="JPEG", quality=self.settings.jpeg_quality)
            result.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        return result
