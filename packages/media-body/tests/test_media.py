import asyncio
import base64
import io

import av
import numpy as np
from PIL import Image
import pytest

from media_body.media import Playout, VoiceActivity, decode_audio


def jpeg(color=(40, 120, 160)):
    stream = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(stream, format="JPEG")
    return base64.b64encode(stream.getvalue()).decode()


async def test_cancel_invalidates_waiting_producer_and_frames():
    output = Playout()
    try:
        await output.reset(1)
        frames = [jpeg()] * 80
        pending = asyncio.create_task(output.enqueue(1, b"\1\1" * 640 * 80, frames))
        await asyncio.sleep(.1)
        await output.reset(2)
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.sleep(.04)
        audio = await output.audio.recv()
        assert not np.any(audio.to_ndarray())
        assert output.video.queue.empty()
        assert not output.cells
    finally:
        await output.close()


async def test_audio_video_pts_share_clock_and_survive_interrupt():
    output = Playout()
    try:
        await output.reset(1)
        await output.enqueue(1, b"\1\1" * 640, [jpeg()])
        video = await asyncio.wait_for(output.video.recv(), 1)
        audio = await output.audio.recv()
        while not np.any(audio.to_ndarray()):
            audio = await output.audio.recv()
        assert video.pts * video.time_base == audio.pts * audio.time_base
        old_pts = video.pts
        await output.reset(2)
        await output.enqueue(2, b"\2\2" * 640, [jpeg((200, 10, 20))])
        new = await asyncio.wait_for(output.video.recv(), 1)
        assert new.pts > old_pts
        assert new.to_ndarray(format="rgb24")[20, 20, 0] > 180
    finally:
        await output.close()


def test_vad_keeps_onset_and_never_sends_silence_to_asr():
    vad = VoiceActivity()
    silence = bytes(640)
    voice = (np.ones(320, dtype=np.int16) * 3000).tobytes()
    assert all(vad.feed(silence) == (False, None) for _ in range(50))
    events = [vad.feed(voice) for _ in range(15)]
    assert sum(start for start, _ in events) == 1
    events.extend(vad.feed(silence) for _ in range(30))
    utterance = next(result for _, result in events if result)
    assert utterance.count(voice) == 15
    assert len(utterance) <= 57 * 640


def test_audio_resample_reuses_real_samples():
    stream = io.BytesIO()
    with av.open(stream, mode="w", format="wav") as container:
        audio = container.add_stream("pcm_s16le", rate=16000)
        audio.layout = "mono"
        frame = av.AudioFrame.from_ndarray(np.full((1, 3200), 1234, dtype=np.int16), format="s16", layout="mono")
        frame.sample_rate = 16000
        for packet in audio.encode(frame):
            container.mux(packet)
        for packet in audio.encode(None):
            container.mux(packet)
    decoded = decode_audio(base64.b64encode(stream.getvalue()).decode(), "wav")
    assert np.frombuffer(decoded, dtype=np.int16).tolist() == [1234] * 3200
