"""Unit tests for PlaybackChannel — the single owner of the device playback
protocol dance (start/sentence/sentence_start/frames/stop + pacing + barge-in)."""

import json
from types import SimpleNamespace

import pytest

from gateway.playback import (
    FRAME_SECS,
    MIN_DRAIN_SECS,
    PRE_BUFFER_FRAMES,
    PlaybackChannel,
)
from gateway.protocols.base import MessageType


class FakeWs:
    def __init__(self):
        self.texts: list[dict] = []
        self.frames: list[bytes] = []

    async def send_text(self, data):
        self.texts.append(json.loads(data))

    async def send_bytes(self, data):
        self.frames.append(data)


class FakeAdapter:
    """Encodes like the xiaozhi adapter: TEXT → JSON, AUDIO → list of frames."""

    async def encode(self, msg):
        if msg.type == MessageType.AUDIO:
            return [msg.payload[i : i + 2] for i in range(0, len(msg.payload), 2)]
        return json.dumps({"text": msg.payload, **(msg.metadata or {})})


def make_session():
    return SimpleNamespace(_playing=False, _interrupted=False, _interrupt_count=0)


def states(ws):
    return [t.get("state") for t in ws.texts]


async def test_claims_and_releases_playing_state():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session):
        assert session._playing is True
    assert session._playing is False
    assert session._interrupted is False


async def test_release_even_on_error():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    with pytest.raises(RuntimeError):
        async with PlaybackChannel(ws, adapter, session):
            raise RuntimeError("boom")
    assert session._playing is False


async def test_claim_false_leaves_session_alone():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session, claim=False):
        assert session._playing is False


async def test_protocol_dance_order():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session) as pb:
        await pb.send_start()
        await pb.send_sentence("你好")
        await pb.send_clip(b"abcdef")
        await pb.finish(wait_drain=False)
    assert states(ws) == ["start", "sentence", "sentence_start", "stop"]
    assert ws.texts[1]["text"] == "你好"
    assert len(ws.frames) == 3  # 6 bytes / 2-byte fake frames


async def test_interrupt_aborts_frames():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session) as pb:
        session._interrupted = True
        ok = await pb.send_frames([b"f1", b"f2"])
        assert ok is False
        assert ws.frames == []
        assert pb.interrupted


async def test_check_interrupt_false_ignores_flag():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session, check_interrupt=False) as pb:
        session._interrupted = True
        ok = await pb.send_frames([b"f1", b"f2"])
        assert ok is True
        assert len(ws.frames) == 2


async def test_frame_accounting_and_first_frame():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session, pace=False) as pb:
        assert pb.first_frame_ms(0.0) is None
        await pb.send_frames([b"a", b"b", b"c"])
        assert pb.total_frames == 3
        assert pb.first_frame_at is not None
        assert pb.first_frame_ms(pb.first_frame_at) == 0.0


async def test_drain_secs_formula():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    pb = PlaybackChannel(ws, adapter, session)
    pb.total_frames = 100
    assert pb.drain_secs() == pytest.approx(100 * FRAME_SECS - 2.0)
    pb.total_frames = 1
    assert pb.drain_secs() == MIN_DRAIN_SECS


async def test_prebuffer_counter_is_global_across_clips():
    """The prebuffer allowance must not reset per sentence — the device's
    buffer is already primed after the first clip."""
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session) as pb:
        await pb.send_frames([b"x"] * PRE_BUFFER_FRAMES)
        assert pb._frames_sent == PRE_BUFFER_FRAMES


async def test_interrupted_finish_skips_drain():
    ws, adapter, session = FakeWs(), FakeAdapter(), make_session()
    async with PlaybackChannel(ws, adapter, session) as pb:
        pb.total_frames = 1000  # would be a ~58s drain wait
        session._interrupted = True
        await pb.finish()  # must return promptly (0.2s settle, no drain)
    assert states(ws) == ["stop"]
