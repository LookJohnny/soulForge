"""One PCM clock for audio and generated video; bounded, cancellable playout."""
from __future__ import annotations

import asyncio
import base64
from collections import deque
from fractions import Fraction
import io
import time

import av
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
import numpy as np
from PIL import Image

RATE = 16000
FPS = 25
SAMPLES_PER_FRAME = RATE // FPS


def decode_audio(encoded: str, fmt: str) -> bytes:
    """Decode precisely the audio later passed to both GPU and RTC output."""
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 8_000_000:
        raise ValueError("audio too large")
    if fmt == "pcm16":
        if len(raw) % 2:
            raise ValueError("unaligned PCM")
        return raw
    if fmt not in {"mp3", "wav", "ogg"}:
        raise ValueError("unsupported audio format")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    parts = []
    with av.open(io.BytesIO(raw), format=fmt) as container:
        for frame in container.decode(audio=0):
            for normalized in resampler.resample(frame):
                parts.append(normalized.to_ndarray().tobytes())
    for normalized in resampler.resample(None):
        parts.append(normalized.to_ndarray().tobytes())
    pcm = b"".join(parts)
    if not pcm or len(pcm) > RATE * 2 * 120:
        raise ValueError("empty or excessive decoded audio")
    return pcm


def decode_image(encoded: str) -> np.ndarray:
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 4_000_000:
        raise ValueError("frame too large")
    with Image.open(io.BytesIO(raw)) as picture:
        if picture.width > 2048 or picture.height > 2048:
            raise ValueError("frame dimensions too large")
        return np.asarray(picture.convert("RGB"))


class OutputTrack(MediaStreamTrack):
    def __init__(self, owner: Playout, kind: str):
        super().__init__()
        self.kind = kind
        self.owner = owner
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=4)

    async def recv(self):
        while self.readyState == "live":
            item = await self.queue.get()
            if item is None:
                raise MediaStreamError
            epoch, frame = item
            if epoch == self.owner.epoch:
                return frame
        raise MediaStreamError

    def push(self, frame):
        if self.queue.full():
            self.queue.get_nowait()
            self.owner.dropped_packets += 1
        self.queue.put_nowait((self.owner.epoch, frame))

    def clear(self):
        while not self.queue.empty():
            self.queue.get_nowait()

    def stop(self):
        super().stop()
        self.clear()
        self.queue.put_nowait(None)


class Playout:
    """Pace both tracks from 16 kHz PCM; never play audio ahead of its video.

    This measures sender delivery only. It cannot prove browser playback.
    Idle emits silence, holding the last real generated video frame.
    """
    def __init__(self, on_start=None):
        self.epoch = 0
        self.audio = OutputTrack(self, "audio")
        self.video = OutputTrack(self, "video")
        self.cells = deque()
        self.condition = asyncio.Condition()
        self.current = None
        self.samples = 0
        self.dropped_packets = 0
        self.closed = False
        self.on_start = on_start
        self.started_epoch = -1
        self.task = asyncio.create_task(self._pace())

    async def enqueue(self, epoch: int, pcm: bytes, frames: list[str]):
        if len(pcm) > len(frames) * SAMPLES_PER_FRAME * 2:
            raise ValueError("video does not cover audio")
        # Decode one frame at a time so the bounded queue also bounds RGB memory.
        for index, encoded in enumerate(frames):
            part = pcm[index * 1280:(index + 1) * 1280]
            if not part:
                break  # discard model padding, not the user's real audio
            picture = await asyncio.to_thread(decode_image, encoded)
            async with self.condition:
                await self.condition.wait_for(lambda: len(self.cells) < 50 or epoch != self.epoch or self.closed)
                if epoch != self.epoch or self.closed:
                    raise asyncio.CancelledError
                self.cells.append((part.ljust(1280, b"\0"), picture))

    async def reset(self, epoch: int):
        async with self.condition:
            self.epoch = epoch
            self.cells.clear()
            self.current = None
            self.audio.clear()
            self.video.clear()
            self.condition.notify_all()

    async def drain(self, epoch: int):
        async with self.condition:
            await self.condition.wait_for(lambda: (not self.cells and self.current is None) or self.epoch != epoch or self.closed)
        if epoch != self.epoch or self.closed:
            raise asyncio.CancelledError

    async def _pace(self):
        deadline = time.monotonic()
        try:
            while True:
                await asyncio.sleep(max(0, deadline - time.monotonic()))
                # A slow event loop must not produce a burst of stale speech.
                deadline = max(deadline + .02, time.monotonic())
                async with self.condition:
                    if self.current is None and self.cells:
                        pcm, rgb = self.cells.popleft()
                        frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
                        frame.pts = self.samples * 90000 // RATE
                        frame.time_base = Fraction(1, 90000)
                        self.video.push(frame)
                        self.current = pcm
                        if self.started_epoch != self.epoch:
                            self.started_epoch = self.epoch
                            if self.on_start:
                                self.on_start()
                    if self.current:
                        piece, self.current = self.current[:640], self.current[640:] or None
                    else:
                        piece = b"\0" * 640
                    frame = av.AudioFrame.from_ndarray(np.frombuffer(piece, dtype=np.int16).reshape(1, -1), format="s16", layout="mono")
                    frame.sample_rate = RATE
                    frame.pts = self.samples
                    frame.time_base = Fraction(1, RATE)
                    self.samples += 320
                    self.audio.push(frame)
                    self.condition.notify_all()
        except asyncio.CancelledError:
            pass

    async def close(self):
        self.closed = True
        await self.reset(self.epoch + 1)
        self.task.cancel()
        await self.task
        self.audio.stop()
        self.video.stop()


class VoiceActivity:
    """First local baseline: energy VAD, with onset retention and bounded turns.

    It deliberately makes no learned/noise-robust endpointing claim.
    Input frames must be 20 ms PCM16 at 16 kHz.
    """
    def __init__(self, threshold: float = .018):
        self.threshold = threshold
        self.preroll = deque(maxlen=12)
        self.parts: list[bytes] = []
        self.active = False
        self.voiced = 0
        self.quiet = 0
        self.onset = 0

    def feed(self, pcm: bytes):
        if len(pcm) != 640:
            raise ValueError("VAD requires 20ms frames")
        rms = float(np.sqrt(np.mean((np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768) ** 2)))
        talking = rms >= self.threshold
        started = False
        completed = None
        if not self.active:
            self.preroll.append(pcm)
            self.onset = self.onset + 1 if talking else 0
            if self.onset >= 3:
                self.active = started = True
                self.parts = list(self.preroll)
                self.voiced = self.onset
                self.quiet = 0
                self.preroll.clear()
        else:
            self.parts.append(pcm)
            self.voiced += int(talking)
            self.quiet = 0 if talking else self.quiet + 1
            if self.quiet >= 30 or len(self.parts) >= 1500:
                if self.voiced >= 8:
                    completed = b"".join(self.parts)
                self.active = False
                self.parts = []
                self.onset = 0
        return started, completed
