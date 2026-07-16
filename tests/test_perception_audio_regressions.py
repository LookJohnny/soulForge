"""Regression tests for echo suppression and barge-in state sharing."""

from engine.perception.audio import (
    BargeInController,
    MockASRProvider,
    MockVAD,
    run_audio_pipeline,
)
from engine.perception.sources import AudioChunk


def _speech(text: str):
    return AudioChunk(
        ts=1.0,
        ref="memory://speech",
        pcm=b"\x00\x00",
        sidecar={"speech": True, "transcript": text, "speaker": "user"},
    )


def test_tts_echo_rejected_by_barge_in_is_not_delivered_to_planner():
    stopped = []
    paused = []
    controller = BargeInController(
        stop_tts=lambda: stopped.append(True),
        pause_motion=lambda reason: paused.append(reason),
    )
    controller.self_voice.on_tts_start("你好呀")

    observations = list(
        run_audio_pipeline(
            iter([_speech("你好呀")]),
            MockVAD(),
            MockASRProvider(),
            barge_in=controller,
        )
    )

    assert observations == []
    assert stopped == []
    assert paused == []


def test_real_user_barge_in_stops_tts_and_is_delivered_once():
    stopped = []
    paused = []
    controller = BargeInController(
        stop_tts=lambda: stopped.append(True),
        pause_motion=lambda reason: paused.append(reason),
    )
    controller.self_voice.on_tts_start("你好呀")

    observations = list(
        run_audio_pipeline(
            iter([_speech("等等，我有问题")]),
            MockVAD(),
            MockASRProvider(),
            barge_in=controller,
        )
    )

    assert [item.transcript for item in observations] == ["等等，我有问题"]
    assert stopped == [True]
    assert paused == ["user_barge_in"]
