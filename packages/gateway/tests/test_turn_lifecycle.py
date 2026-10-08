"""Turn lifecycle regressions: re-arming the mic, a free receive loop, one speaker, late answers."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import server as gateway_server
from gateway.pipeline.character_bridge import CharacterBridge
from gateway.protocols.base import InboundMessage, MessageType
from gateway.reply import speech_lock


def bare_server():
    s = object.__new__(gateway_server.WebSocketServer)
    s.audio_handler = MagicMock()
    s.orchestrator = MagicMock()
    s.session_manager = SimpleNamespace(add_to_history=AsyncMock())
    return s


def session(**kw):
    return SimpleNamespace(session_id="s1", character_id="c", brand_id="b", _mic_pcm=True, **kw)


@pytest.mark.asyncio
async def test_mic_rearms_after_a_successful_streaming_turn_with_its_pcm_format(monkeypatch):
    s, sess = bare_server(), session()
    s.audio_handler.is_speech_complete.return_value = True
    s.audio_handler.get_streaming_asr_result = AsyncMock(return_value="今天天气怎么样")
    s.audio_handler.stop_listening.return_value = b"pcm"
    s._process_text_and_respond_streaming = AsyncMock()
    monkeypatch.setattr(gateway_server, "match_plugin", lambda text: None)
    await s._vad_monitor(None, None, sess)
    s._process_text_and_respond_streaming.assert_awaited_once()
    # before: returned without re-arming, so a browser mic went deaf after one turn
    s.audio_handler.start_listening.assert_called_once_with(sess, pcm=True)
    assert sess._silence_task is not None and not sess._silence_task.done()
    sess._silence_task.cancel()


@pytest.mark.asyncio
async def test_a_finished_vad_monitor_does_not_block_a_new_one():
    s, sess = bare_server(), session()
    done = asyncio.get_running_loop().create_future()
    done.set_result(None)
    sess._silence_task = done
    sess._playing = False
    s._vad_monitor = AsyncMock()
    await s._handle_message(None, None, sess, InboundMessage(type=MessageType.AUDIO, device_id="d", payload=b"x"))
    assert sess._silence_task is not done


@pytest.mark.asyncio
async def test_text_turns_run_off_the_receive_loop_in_order_and_abort_cancels_them():
    s, sess = bare_server(), session()
    started, release = [], asyncio.Event()

    async def slow_turn(ws, adapter, session, text, image=None):
        started.append(text)
        await release.wait()

    s._process_text_and_respond = slow_turn
    s._vision_frame_for = AsyncMock(return_value=None)
    ws = SimpleNamespace(send_text=AsyncMock())
    adapter = SimpleNamespace(encode=AsyncMock(return_value="{}"))
    for text in ("一", "二"):
        # returns at once: the socket keeps reading while the brain thinks
        await asyncio.wait_for(
            s._handle_message(ws, adapter, sess, InboundMessage(type=MessageType.TEXT, device_id="d", payload=text)),
            timeout=0.2,
        )
    await asyncio.sleep(0.05)
    assert started == ["一"]  # the second waits for the first (per-session order)
    assert sess._last_activity  # typing counts as activity (no idle close mid-chat)
    s.audio_handler.abort = MagicMock()
    await s._handle_message(
        ws, adapter, sess, InboundMessage(type=MessageType.CONTROL, device_id="d", payload={"action": "abort"})
    )
    await asyncio.sleep(0.05)
    assert not sess._turn_tasks  # both turns cancelled


@pytest.mark.asyncio
async def test_one_reply_plays_at_a_time_per_session():
    sess, order = session(), []

    async def speak(name):
        async with speech_lock(sess):
            order.append(f"{name}+")
            await asyncio.sleep(0.02)
            order.append(f"{name}-")

    await asyncio.gather(speak("text"), speak("unsolicited"))
    assert order in (["text+", "text-", "unsolicited+", "unsolicited-"], ["unsolicited+", "unsolicited-", "text+", "text-"])


def test_latency_record_ignores_non_numeric_stage_markers(monkeypatch):
    recorded = []
    monkeypatch.setattr(gateway_server.latency_tracker, "record_turn", lambda route, stages: recorded.append(stages))
    s = bare_server()
    # before: int("no_transcript") raised and turned an empty-transcript turn into a pipeline error
    s._record_voice_turn(session(), 0.0, 5.0, None, {"asr_only": "no_transcript", "decision_ms": 120}, False)
    assert "core_asr_only" not in recorded[0] and recorded[0]["core_decision_ms"] == 120


class FakeSocket:
    def __init__(self, frames):
        self.frames, self.sent = frames, []

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for frame in self.frames:
            yield json.dumps(frame)

    async def send(self, raw):
        self.sent.append(json.loads(raw))


@pytest.mark.asyncio
async def test_a_late_answer_is_refused_not_spoken_into_the_next_turn():
    bridge = CharacterBridge(url="ws://x", agent_id="joi", body_id="voice-1")
    bridge._expire("old-turn")
    late = {"type": "action", "agent_id": "joi", "dialogue": "上一轮的回答", "command_id": "c1", "correlation_id": "old-turn"}
    ambient = {"type": "action", "agent_id": "joi", "dialogue": "我去倒杯水", "command_id": "c2", "correlation_id": None}
    sock = FakeSocket([late, ambient])
    queued, put = [], bridge._unsolicited.put

    async def recording_put(item):
        queued.append(item)
        await put(item)

    bridge._unsolicited.put = recording_put  # the queue is drained when the socket closes
    await bridge._reader_loop(sock)
    statuses = {f["command_id"]: f["status"] for f in sock.sent if f.get("type") == "observation"}
    assert statuses == {"c1": "rejected", "c2": "accepted"}
    assert [q["dialogue"] for q in queued] == ["我去倒杯水"]


@pytest.mark.asyncio
async def test_bridge_streams_lines_until_completion_not_a_quiet_window():
    bridge = CharacterBridge(url="ws://x", agent_id="joi", body_id="voice-1", timeout_s=5)
    sent = []

    class Sock:
        async def send(self, raw):
            sent.append(json.loads(raw))

    async def connected():
        return Sock()

    bridge._ensure_connected = connected

    async def runtime():
        while not sent:
            await asyncio.sleep(0.01)
        inbox = bridge._waiters[sent[0]["payload"]["event_id"]]
        await inbox.put({"type": "action", "dialogue": "第一句。", "command_id": "a"})
        await asyncio.sleep(0.8)  # longer than the old 0.6 s quiet window
        await inbox.put({"type": "action", "dialogue": "第二句。", "command_id": "b"})
        await inbox.put({"type": "decision_complete", "cognitive_state": {"emotion": "happy"}})

    producer = asyncio.create_task(runtime())
    got = [item async for item in bridge.stream_utterance("你好")]
    await producer
    assert [k for k, _ in got] == ["command", "command", "complete"]
    assert got[-1][1]["cognitive_state"] == {"emotion": "happy"}
    assert not bridge._expired  # a completed turn is not expired


@pytest.mark.asyncio
async def test_orchestrator_speaks_the_first_line_before_the_second_exists(monkeypatch):
    from gateway.config import settings
    from gateway.pipeline.orchestrator import PipelineOrchestrator

    monkeypatch.setattr(settings, "character_runtime_url", "ws://x")
    second_ready = asyncio.Event()
    bridge = SimpleNamespace(confirm_spoken=AsyncMock())

    async def stream(session, text):
        yield "command", {"command_id": "a", "dialogue": "第一句。", "params": {}}, bridge
        await second_ready.wait()
        yield "command", {"command_id": "b", "dialogue": "第二句。", "params": {}}, bridge
        yield "complete", {"type": "decision_complete", "cognitive_state": {"emotion": "calm", "pad": {}}}, bridge

    orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orch._runtime_stream = stream
    orch.synthesize_tts = AsyncMock(side_effect=lambda text, *a, **k: text.encode())
    turn = orch.process_text_stream(session(), "你好")
    first = await asyncio.wait_for(anext(turn), 1)
    assert first.text == "第一句。" and first.audio_data and not second_ready.is_set()
    second_ready.set()
    rest = [c async for c in turn]
    assert [c.kind for c in rest] == ["sentence", "emotion", "done"]
    assert rest[-1].full_text == "第一句。第二句。"
    assert {first.playback_receipt, rest[0].playback_receipt} == set(orch._pending_playback)
