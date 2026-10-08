"""Per-sentence expression cues: tone readouts ride each speak_line and are sent
right before the sentence's clip, so the client can apply them when it plays."""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import settings
from gateway.protocols.web_audio import WebAudioAdapter
from gateway.session import Session

TONE = {
    "readout": {"joy": 0.5, "neutral": 0.3},
    "expression": {"happy": 0.4, "neutral": 0.6},
    "sentences": [
        {"text": "考过啦！", "readout": {"joy": 0.8}, "expression": {"happy": 0.9, "neutral": 0.1}},
        {
            "text": "我替你高兴。",
            "readout": {"warmth": 0.6},
            "expression": {"relaxed": 0.7, "neutral": 0.3},
        },
    ],
}


def orchestrator_module():
    return importlib.import_module("gateway.pipeline.orchestrator")


def test_sentence_expression_exact_match_line_fallback_and_sanitizing():
    pick = orchestrator_module().PipelineOrchestrator._sentence_expression
    command = {"dialogue": "考过啦！我替你高兴。", "params": {"tone_readout": TONE}}
    first = pick(command, "考过啦！", 0)
    assert first == {
        "weights": {"happy": 0.9, "neutral": 0.1},
        "readout": {"joy": 0.8},
        "source": "sentence",
        "index": 0,
        "text": "考过啦！",
    }
    assert (
        pick({**command, "params": {**command["params"], "emotion": " happy "}}, "考过啦！", 0)[
            "declared"
        ]
        == "happy"
    )
    assert pick(command, " 我替你高兴。", 1)["weights"] == {"relaxed": 0.7, "neutral": 0.3}
    # a sentence the reader never saw (e.g. changed downstream) gets the line reading
    other = pick(command, "另一句。", 2)
    assert other["source"] == "line" and other["weights"] == {"happy": 0.4, "neutral": 0.6}
    # no readout -> no cue (the face stays on PAD); junk never reaches a client
    assert pick({"dialogue": "x", "params": {"emotion": "happy"}}, "x", 0) is None
    assert pick({"params": {"tone_readout": "gentle"}}, "x", 0) is None
    junk = {
        "params": {
            "tone_readout": {
                "expression": {"happy": 7, "sad": "x", "angry": float("nan"), "relaxed": -1}
            }
        }
    }
    assert pick(junk, "x", 0)["weights"] == {"happy": 1.0, "relaxed": 0.0}


class Recorder:
    """One ordered wire log for text and binary frames."""

    def __init__(self):
        self.frames = []

    async def send_text(self, data):
        self.frames.append(("text", json.loads(data)))

    async def send_bytes(self, data):
        self.frames.append(("bytes", data))


async def text_turn(monkeypatch, commands, method="_process_text_and_respond"):
    monkeypatch.setattr(settings, "face_host", "")
    monkeypatch.setattr(settings, "character_runtime_url", "ws://synthetic.test")
    server_module = importlib.import_module("gateway.server")
    playback_module = importlib.import_module("gateway.playback")
    monkeypatch.setattr(playback_module, "speaking_hook", None)
    monkeypatch.setattr(playback_module, "audio_hook", None)
    monkeypatch.setattr(playback_module, "SETTLE_SECS", 0)
    monkeypatch.setattr(playback_module, "MIN_DRAIN_SECS", 0)
    monkeypatch.setattr(playback_module, "FRAME_SECS", 0)

    async def decide(session, text):
        return None, {
            "text": "".join(c.get("dialogue", "") for c in commands),
            "commands": commands,
        }

    async def synthesize(text, *args, **kwargs):
        return ("MP3:" + text).encode()

    pipeline = orchestrator_module().PipelineOrchestrator.__new__(
        orchestrator_module().PipelineOrchestrator
    )
    pipeline._runtime_stream = stream_of(decide)
    pipeline.synthesize_tts = AsyncMock(side_effect=synthesize)
    server = server_module.WebSocketServer.__new__(server_module.WebSocketServer)
    server.orchestrator = pipeline
    server.session_manager = SimpleNamespace(add_to_history=AsyncMock())
    ws = Recorder()
    session = Session("web", "web", character_id="c", brand_id="b")
    await getattr(server, method)(ws, WebAudioAdapter(), session, "我考过了")
    return ws.frames


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["_process_text_and_respond", "_process_text_and_respond_streaming"]
)
async def test_cue_precedes_its_sentence_and_clip_on_the_wire(monkeypatch, method):
    commands = [
        {
            "name": "speak_line",
            "dialogue": "考过啦！我替你高兴。",
            "params": {"emotion": "happy", "tone_readout": TONE},
        },
        {"name": "speak_line", "dialogue": "没有读数的一句。", "params": {"emotion": "calm"}},
    ]
    frames = await text_turn(monkeypatch, commands, method)
    wire = []
    for kind, data in frames:
        if kind == "bytes":
            wire.append(("clip", data.decode()))
        elif data.get("type") == "control" and data["payload"].get("type") == "expression":
            wire.append(("cue", data["payload"]["text"], data["payload"]["weights"]))
        elif data.get("type") == "text" and data.get("state") == "sentence":
            wire.append(("sentence", data["content"]))
    assert wire == [
        ("cue", "考过啦！", {"happy": 0.9, "neutral": 0.1}),
        ("sentence", "考过啦！"),
        ("clip", "MP3:考过啦！"),
        ("cue", "我替你高兴。", {"relaxed": 0.7, "neutral": 0.3}),
        ("sentence", "我替你高兴。"),
        ("clip", "MP3:我替你高兴。"),
        ("sentence", "没有读数的一句。"),  # no readout -> no cue
        ("clip", "MP3:没有读数的一句。"),
    ]
    cue = next(
        d["payload"]
        for k, d in frames
        if k == "text" and d.get("payload", {}).get("type") == "expression"
    )
    assert cue["index"] == 0 and cue["source"] == "sentence" and cue["readout"] == {"joy": 0.8}


def test_tts_sentences_match_the_reader_split_and_respect_the_tts_limit():
    import re

    split = orchestrator_module()._tts_sentences
    line = "考过啦！我替你高兴。真的"
    assert split(line) == re.findall(r"[^。！？!?]+[。！？!?]*", line)
    long = "好" * 300 + "，" + "棒" * 300 + "。"
    parts = split(long)
    assert all(len(p) <= 500 for p in parts) and "".join(parts) == long
    assert parts[0].endswith("，")  # broken at the comma, not mid-word
    assert all(len(p) <= 500 for p in split("长" * 1200))


def stream_of(decide):
    """Replay a stubbed whole decision (bridge, {"commands": ...}) as the Runtime's
    stream: each line, then the completion carrying the turn's cognitive state."""

    async def _stream(session, text):
        bridge, decision = await decide(session, text)
        for command in decision.get("commands", []):
            yield "command", command, bridge
        yield "complete", {"type": "decision_complete"}, bridge

    return _stream
