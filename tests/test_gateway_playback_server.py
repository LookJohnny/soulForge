"""Gateway playback loop must commit receipts only at the playback boundary."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

GATEWAY_SRC = Path(__file__).resolve().parents[1] / "packages" / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

# The root project's lean test environment intentionally does not install the
# gateway's real-time audio stack. This module runs in the gateway package CI;
# root-suite collection skips it rather than replacing production codecs with
# fake modules.
pytest.importorskip("opuslib")
pytest.importorskip("silero_vad")
pytest.importorskip("dashscope")

import gateway.server as gateway_server  # noqa: E402
from gateway.pipeline.orchestrator import StreamChunk  # noqa: E402
from gateway.protocols.base import MessageType  # noqa: E402


class _Orchestrator:
    def __init__(self, trace):
        self.trace = trace
        self.unsolicited_calls = 0
        self.confirmed = asyncio.Event()

    async def process_text_stream(self, session, text):
        yield StreamChunk(
            text="我在。",
            audio_data=b"audio",
            index=0,
            playback_receipt="receipt-1",
        )
        yield StreamChunk(
            text="",
            audio_data=None,
            index=1,
            kind="done",
            is_done=True,
            full_text="我在。",
            playback_receipt="receipt-1",
        )

    async def confirm_playback(self, receipt, *, played, detail=""):
        self.trace.append(("confirm", receipt, played, detail))
        self.confirmed.set()
        return True

    async def process_next_runtime_dialogue(self, session):
        self.unsolicited_calls += 1
        if self.unsolicited_calls > 1:
            await asyncio.Future()
        return StreamChunk(
            text="视觉触发台词",
            audio_data=b"audio",
            index=0,
            playback_receipt="runtime-receipt",
        )


class _Adapter:
    async def encode(self, message):
        if message.type == MessageType.AUDIO:
            return [b"opus-frame"]
        return "control-frame"


class _Socket:
    def __init__(self, trace, *, fail_audio=False):
        self.trace = trace
        self.fail_audio = fail_audio

    async def send_text(self, frame):
        self.trace.append(("send_text", frame))

    async def send_bytes(self, frame):
        self.trace.append(("send_audio", frame))
        if self.fail_audio:
            raise ConnectionError("device disconnected")


class _Sessions:
    async def add_to_history(self, *args):
        return None


def _server(trace):
    server = object.__new__(gateway_server.WebSocketServer)
    server.orchestrator = _Orchestrator(trace)
    server.session_manager = _Sessions()
    return server


def _session():
    return SimpleNamespace(session_id="s1", character_id="kai", brand_id=None)


@pytest.mark.asyncio
async def test_text_playback_confirms_done_only_after_wait(monkeypatch):
    trace = []

    async def fake_sleep(seconds):
        trace.append(("playback_wait", seconds))

    monkeypatch.setattr(gateway_server.asyncio, "sleep", fake_sleep)
    await _server(trace)._process_text_and_respond(
        _Socket(trace),
        _Adapter(),
        _session(),
        "你好",
    )

    send_index = next(i for i, item in enumerate(trace) if item[0] == "send_audio")
    wait_index = next(i for i, item in enumerate(trace) if item[0] == "playback_wait")
    confirm_index = next(i for i, item in enumerate(trace) if item[0] == "confirm")
    assert send_index < wait_index < confirm_index
    assert trace[confirm_index] == ("confirm", "receipt-1", True, "")


@pytest.mark.asyncio
async def test_device_send_failure_marks_playback_interrupted(monkeypatch):
    trace = []

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(gateway_server.asyncio, "sleep", no_sleep)
    await _server(trace)._process_text_and_respond(
        _Socket(trace, fail_audio=True),
        _Adapter(),
        _session(),
        "你好",
    )

    assert ("confirm", "receipt-1", False, "gateway text playback error") in trace


@pytest.mark.asyncio
async def test_unsolicited_runtime_dialogue_is_played_then_confirmed():
    trace = []
    server = _server(trace)
    session = _session()
    session._playing = False
    session._interrupted = False
    task = asyncio.create_task(
        server._runtime_dialogue_loop(_Socket(trace), _Adapter(), session),
    )
    try:
        await asyncio.wait_for(server.orchestrator.confirmed.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    send_index = next(i for i, item in enumerate(trace) if item[0] == "send_audio")
    confirm_index = next(i for i, item in enumerate(trace) if item[0] == "confirm")
    assert send_index < confirm_index
    assert trace[confirm_index] == ("confirm", "runtime-receipt", True, "")
