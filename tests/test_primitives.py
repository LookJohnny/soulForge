"""Tests for Performance Primitive Protocol (Task 1A)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "protocol"))

from primitives_pb2 import (
    EmotionType, EmotionPrimitive,
    AttentionMode, AttentionPrimitive,
    GestureType, GesturePrimitive,
    VocalizationPrimitive, PhonemeTiming,
    RhythmPrimitive, IdlePrimitive,
    CompositePrimitive,
)


class TestEmotionPrimitive:
    def test_all_emotion_types(self):
        """At least 11 emotion types defined."""
        assert len(EmotionType.items()) >= 11

    def test_serialize_deserialize(self):
        ep = EmotionPrimitive(type=EmotionType.JOY, intensity=0.8, duration_ms=500)
        data = ep.SerializeToString()
        ep2 = EmotionPrimitive()
        ep2.ParseFromString(data)
        assert ep2.type == EmotionType.JOY
        assert abs(ep2.intensity - 0.8) < 1e-5

    def test_blend(self):
        ep = EmotionPrimitive(
            type=EmotionType.JOY, intensity=0.7,
            blend_with=EmotionType.CURIOSITY, blend_ratio=0.3,
        )
        data = ep.SerializeToString()
        ep2 = EmotionPrimitive()
        ep2.ParseFromString(data)
        assert ep2.blend_with == EmotionType.CURIOSITY
        assert abs(ep2.blend_ratio - 0.3) < 1e-5

    def test_transition_speed(self):
        ep = EmotionPrimitive(type=EmotionType.SADNESS, transition_speed=0.0)
        assert ep.transition_speed == 0.0
        ep2 = EmotionPrimitive(type=EmotionType.ANGER, transition_speed=1.0)
        assert ep2.transition_speed == 1.0


class TestAttentionPrimitive:
    def test_all_modes(self):
        assert len(AttentionMode.items()) >= 6

    def test_serialize(self):
        ap = AttentionPrimitive(
            mode=AttentionMode.TRACKING, yaw=45.0, pitch=-10.0,
            tracking_speed=0.8, hold_duration_ms=2000, saccade_frequency=2.5,
        )
        data = ap.SerializeToString()
        ap2 = AttentionPrimitive()
        ap2.ParseFromString(data)
        assert ap2.mode == AttentionMode.TRACKING
        assert abs(ap2.yaw - 45.0) < 1e-3
        assert abs(ap2.saccade_frequency - 2.5) < 1e-3


class TestGesturePrimitive:
    def test_all_types(self):
        assert len(GestureType.items()) >= 13  # including NONE

    def test_serialize(self):
        gp = GesturePrimitive(
            type=GestureType.WAVE, amplitude=0.7, speed=0.5,
            repeat_count=3, expressiveness=0.8,
        )
        data = gp.SerializeToString()
        gp2 = GesturePrimitive()
        gp2.ParseFromString(data)
        assert gp2.type == GestureType.WAVE
        assert gp2.repeat_count == 3


class TestVocalizationPrimitive:
    def test_with_phonemes(self):
        vp = VocalizationPrimitive(
            speech_text="你好呀",
            emotion_overlay=EmotionType.JOY,
            volume=0.7, pitch_shift=0.1, speed_ratio=1.1,
            sync_gestures=True,
            phonemes=[
                PhonemeTiming(phoneme="n", start_ms=0, end_ms=80),
                PhonemeTiming(phoneme="i", start_ms=80, end_ms=200),
                PhonemeTiming(phoneme="h", start_ms=200, end_ms=280),
            ],
        )
        data = vp.SerializeToString()
        vp2 = VocalizationPrimitive()
        vp2.ParseFromString(data)
        assert vp2.speech_text == "你好呀"
        assert len(vp2.phonemes) == 3
        assert vp2.phonemes[0].phoneme == "n"
        assert vp2.sync_gestures is True


class TestRhythmPrimitive:
    def test_serialize(self):
        rp = RhythmPrimitive(bpm=120.0, body_sway_amplitude=0.3, head_bob_intensity=0.5, sync_to_audio=True)
        data = rp.SerializeToString()
        rp2 = RhythmPrimitive()
        rp2.ParseFromString(data)
        assert abs(rp2.bpm - 120.0) < 1e-3
        assert rp2.sync_to_audio is True


class TestIdlePrimitive:
    def test_serialize(self):
        ip = IdlePrimitive(breathing_rate=15.0, micro_movement_intensity=0.2, fidget_probability=0.1, personality_preset="calm")
        data = ip.SerializeToString()
        ip2 = IdlePrimitive()
        ip2.ParseFromString(data)
        assert abs(ip2.breathing_rate - 15.0) < 1e-3
        assert ip2.personality_preset == "calm"


class TestCompositePrimitive:
    def test_arbitrary_combination(self):
        """CompositePrimitive supports any combination of sub-primitives."""
        # All fields populated
        cp = CompositePrimitive(
            emotion=EmotionPrimitive(type=EmotionType.EXCITED, intensity=0.9),
            attention=AttentionPrimitive(mode=AttentionMode.DIRECT_GAZE),
            gesture=GesturePrimitive(type=GestureType.BOUNCE, amplitude=0.8),
            vocalization=VocalizationPrimitive(speech_text="太棒了!"),
            rhythm=RhythmPrimitive(bpm=140),
            idle=IdlePrimitive(breathing_rate=20),
            timestamp_ms=9999999, priority=8, source="llm",
        )
        data = cp.SerializeToString()
        cp2 = CompositePrimitive()
        cp2.ParseFromString(data)
        assert cp2.emotion.type == EmotionType.EXCITED
        assert cp2.gesture.type == GestureType.BOUNCE
        assert cp2.source == "llm"

    def test_partial_combination(self):
        """Only emotion + gesture, others left empty."""
        cp = CompositePrimitive(
            emotion=EmotionPrimitive(type=EmotionType.FEAR, intensity=0.6),
            gesture=GesturePrimitive(type=GestureType.LEAN_BACK, amplitude=0.5),
        )
        data = cp.SerializeToString()
        cp2 = CompositePrimitive()
        cp2.ParseFromString(data)
        assert cp2.emotion.type == EmotionType.FEAR
        assert cp2.gesture.type == GestureType.LEAN_BACK
        # Unset fields have default values
        assert cp2.vocalization.speech_text == ""
        assert cp2.priority == 0

    def test_metadata_fields(self):
        cp = CompositePrimitive(timestamp_ms=1711234567890, priority=10, source="sensor")
        assert cp.timestamp_ms == 1711234567890
        assert cp.priority == 10
        assert cp.source == "sensor"
