"""Tests for the PAD Emotion Model."""

import pytest
import math
from unittest.mock import AsyncMock, MagicMock

from ai_core.services.pad_model import (
    PADState,
    PADEngine,
    EMOTION_PAD_ANCHORS,
    TOUCH_PAD_IMPULSE,
    USER_MOOD_PAD,
    pad_to_emotion,
    emotion_to_pad,
    pad_to_tts_offsets,
    pad_to_prompt_description,
    transition_pad,
    BASE_TRANSITION_SPEED,
    BASE_DECAY_RATE,
)
from ai_core.services.emotion import EmotionEngine, EMOTIONS


# ──────────────────────────────────────────────
# PADState basics
# ──────────────────────────────────────────────

class TestPADState:
    def test_default_values(self):
        s = PADState()
        assert s.p == 0.0 and s.a == 0.0 and s.d == 0.0

    def test_neutral(self):
        s = PADState.neutral()
        assert -0.5 <= s.p <= 0.5
        assert -0.5 <= s.a <= 0.5
        assert -0.5 <= s.d <= 0.5

    def test_clamp(self):
        s = PADState(p=1.5, a=-2.0, d=0.5).clamp()
        assert s.p == 1.0
        assert s.a == -1.0
        assert s.d == 0.5

    def test_distance_same(self):
        a = PADState(0.5, 0.5, 0.5)
        assert a.distance_to(a) == 0.0

    def test_distance_different(self):
        a = PADState(1.0, 0.0, 0.0)
        b = PADState(-1.0, 0.0, 0.0)
        assert abs(a.distance_to(b) - 2.0) < 1e-6

    def test_lerp_zero(self):
        a = PADState(0.0, 0.0, 0.0)
        b = PADState(1.0, 1.0, 1.0)
        result = a.lerp(b, 0.0)
        assert result.p == 0.0 and result.a == 0.0

    def test_lerp_one(self):
        a = PADState(0.0, 0.0, 0.0)
        b = PADState(1.0, 1.0, 1.0)
        result = a.lerp(b, 1.0)
        assert abs(result.p - 1.0) < 1e-6
        assert abs(result.a - 1.0) < 1e-6

    def test_lerp_half(self):
        a = PADState(0.0, 0.0, 0.0)
        b = PADState(1.0, 1.0, 1.0)
        result = a.lerp(b, 0.5)
        assert abs(result.p - 0.5) < 1e-6

    def test_lerp_clamps_alpha(self):
        a = PADState(0.0, 0.0, 0.0)
        b = PADState(1.0, 1.0, 1.0)
        result = a.lerp(b, 2.0)  # alpha > 1 clamped to 1
        assert abs(result.p - 1.0) < 1e-6

    def test_to_dict_from_dict(self):
        s = PADState(0.123, -0.456, 0.789)
        d = s.to_dict()
        restored = PADState.from_dict(d)
        assert abs(restored.p - 0.123) < 1e-3
        assert abs(restored.a - (-0.456)) < 1e-3
        assert abs(restored.d - 0.789) < 1e-3


# ──────────────────────────────────────────────
# Emotion ↔ PAD mapping
# ──────────────────────────────────────────────

class TestEmotionPADMapping:
    def test_all_emotions_have_anchors(self):
        for emotion in EMOTIONS:
            assert emotion in EMOTION_PAD_ANCHORS

    def test_pad_to_emotion_at_anchor(self):
        """Each anchor should map back to its own emotion."""
        for emotion, anchor in EMOTION_PAD_ANCHORS.items():
            result = pad_to_emotion(anchor)
            assert result == emotion, f"Anchor for {emotion} maps to {result}"

    def test_emotion_to_pad_returns_copy(self):
        """emotion_to_pad should return a new object, not the shared anchor."""
        a = emotion_to_pad("happy")
        b = emotion_to_pad("happy")
        a.p = -999
        assert b.p != -999  # b should be unaffected

    def test_unknown_emotion_returns_neutral(self):
        s = emotion_to_pad("nonexistent")
        assert abs(s.p - PADState.neutral().p) < 1e-6

    def test_happy_has_positive_pleasure(self):
        s = emotion_to_pad("happy")
        assert s.p > 0.5

    def test_sad_has_negative_pleasure(self):
        s = emotion_to_pad("sad")
        assert s.p < -0.3

    def test_angry_has_high_arousal(self):
        s = emotion_to_pad("angry")
        assert s.a > 0.5

    def test_calm_has_low_arousal(self):
        s = emotion_to_pad("calm")
        assert s.a < 0.0

    def test_shy_has_low_dominance(self):
        s = emotion_to_pad("shy")
        assert s.d < -0.3

    def test_playful_has_high_arousal_and_positive_pleasure(self):
        s = emotion_to_pad("playful")
        assert s.p >= 0.5 and s.a > 0.5


# ──────────────────────────────────────────────
# Transition dynamics
# ──────────────────────────────────────────────

class TestTransition:
    def test_no_inputs_decays_toward_neutral(self):
        current = PADState(0.8, 0.8, 0.8)
        result = transition_pad(current)
        # Should be closer to neutral than before
        neutral = PADState.neutral()
        assert result.distance_to(neutral) < current.distance_to(neutral)

    def test_text_emotion_moves_toward_target(self):
        current = PADState.neutral()
        target = emotion_to_pad("happy")
        result = transition_pad(current, text_target=target)
        # Should be closer to happy than neutral
        assert result.p > current.p

    def test_touch_impulse_additive(self):
        current = PADState(0.0, 0.0, 0.0)
        impulse = TOUCH_PAD_IMPULSE["poke"]  # positive arousal
        result = transition_pad(current, touch_impulse=impulse)
        # Arousal should increase (poke has high arousal impulse)
        assert result.a > current.a

    def test_user_mood_empathy(self):
        current = PADState(0.0, 0.0, 0.0)
        sad_mood = USER_MOOD_PAD["sad"]
        result = transition_pad(current, user_mood_pad=sad_mood)
        # Character should mirror sadness slightly (lower pleasure)
        assert result.p < current.p

    def test_multi_modal_fusion(self):
        """All three signals together should produce a blended result."""
        current = PADState.neutral()
        text = emotion_to_pad("happy")
        touch = TOUCH_PAD_IMPULSE["hug"]
        mood = USER_MOOD_PAD["sad"]

        result = transition_pad(current, text_target=text, touch_impulse=touch, user_mood_pad=mood)
        # Result should be somewhere between inputs, not extreme
        assert -1.0 <= result.p <= 1.0
        assert -1.0 <= result.a <= 1.0
        assert -1.0 <= result.d <= 1.0

    def test_result_always_clamped(self):
        extreme = PADState(0.95, 0.95, 0.95)
        impulse = PADState(0.5, 0.5, 0.5)
        result = transition_pad(extreme, text_target=PADState(1.0, 1.0, 1.0), touch_impulse=impulse)
        assert result.p <= 1.0
        assert result.a <= 1.0
        assert result.d <= 1.0

    def test_smooth_transition_not_instant(self):
        """Transition should not jump directly to target."""
        current = PADState(0.0, 0.0, 0.0)
        target = emotion_to_pad("angry")
        result = transition_pad(current, text_target=target)
        # Should move toward angry but not reach it in one step
        assert result.distance_to(target) > 0.1
        assert result.distance_to(current) > 0.1

    def test_repeated_transitions_converge(self):
        """Multiple transitions with same input should converge toward target."""
        state = PADState.neutral()
        target = emotion_to_pad("happy")
        for _ in range(20):
            state = transition_pad(state, text_target=target)
        # After many iterations, should be close to happy anchor
        assert state.distance_to(target) < 0.3


# ──────────────────────────────────────────────
# PAD → TTS offsets
# ──────────────────────────────────────────────

class TestPADToTTS:
    def test_neutral_near_zero(self):
        offsets = pad_to_tts_offsets(PADState.neutral())
        assert abs(offsets["pitch_offset"]) < 0.05
        assert abs(offsets["rate_offset"]) < 0.05

    def test_happy_positive_pitch(self):
        offsets = pad_to_tts_offsets(emotion_to_pad("happy"))
        assert offsets["pitch_offset"] > 0

    def test_sad_negative_pitch(self):
        offsets = pad_to_tts_offsets(emotion_to_pad("sad"))
        assert offsets["pitch_offset"] < 0

    def test_high_arousal_positive_rate(self):
        offsets = pad_to_tts_offsets(PADState(0.0, 0.8, 0.0))
        assert offsets["rate_offset"] > 0

    def test_offsets_clamped(self):
        offsets = pad_to_tts_offsets(PADState(1.0, 1.0, 1.0))
        assert -0.12 <= offsets["pitch_offset"] <= 0.12
        assert -0.12 <= offsets["rate_offset"] <= 0.12


# ──────────────────────────────────────────────
# PAD → Prompt description
# ──────────────────────────────────────────────

class TestPADToPrompt:
    def test_happy_state(self):
        desc = pad_to_prompt_description(PADState(0.8, 0.6, 0.3))
        assert "开心" in desc or "心情" in desc

    def test_sad_state(self):
        desc = pad_to_prompt_description(PADState(-0.7, -0.3, -0.4))
        assert "难过" in desc or "低落" in desc

    def test_calm_state(self):
        desc = pad_to_prompt_description(PADState(0.1, -0.6, 0.0))
        assert "安静" in desc or "平和" in desc

    def test_shy_state(self):
        desc = pad_to_prompt_description(PADState(0.1, -0.1, -0.6))
        assert "小心翼翼" in desc

    def test_neutral_state(self):
        desc = pad_to_prompt_description(PADState(0.0, 0.0, 0.0))
        assert "平静" in desc

    def test_high_arousal(self):
        desc = pad_to_prompt_description(PADState(0.0, 0.8, 0.0))
        assert "充沛" in desc or "活跃" in desc


# ──────────────────────────────────────────────
# PAD Engine (with cache)
# ──────────────────────────────────────────────

class TestPADEngine:
    def setup_method(self):
        self.store = {}
        self.cache = MagicMock()

        async def mock_get_json(key):
            raw = self.store.get(key)
            if raw is None:
                return None
            import json
            return json.loads(raw)

        async def mock_set_json(key, value, ttl=3600):
            import json
            self.store[key] = json.dumps(value)

        self.cache.get_json = AsyncMock(side_effect=mock_get_json)
        self.cache.set_json = AsyncMock(side_effect=mock_set_json)
        self.engine = PADEngine(self.cache)

    @pytest.mark.asyncio
    async def test_get_pad_default(self):
        state = await self.engine.get_pad("new-session")
        neutral = PADState.neutral()
        assert abs(state.p - neutral.p) < 1e-6

    @pytest.mark.asyncio
    async def test_set_and_get_pad(self):
        await self.engine.set_pad("sess-1", PADState(0.5, -0.3, 0.2))
        state = await self.engine.get_pad("sess-1")
        assert abs(state.p - 0.5) < 1e-3
        assert abs(state.a - (-0.3)) < 1e-3

    @pytest.mark.asyncio
    async def test_update_with_text(self):
        pad, emotion = await self.engine.update("sess-1", text_emotion="happy")
        assert pad.p > 0  # moved toward happy
        assert emotion in EMOTIONS

    @pytest.mark.asyncio
    async def test_update_with_touch(self):
        pad, emotion = await self.engine.update("sess-1", touch_gesture="hug")
        assert emotion in EMOTIONS

    @pytest.mark.asyncio
    async def test_update_multi_modal(self):
        pad, emotion = await self.engine.update(
            "sess-1",
            text_emotion="happy",
            touch_gesture="pat",
            user_mood="excited",
        )
        assert pad.p > 0  # all positive signals → positive pleasure

    @pytest.mark.asyncio
    async def test_successive_updates_accumulate(self):
        # Start neutral, then multiple happy signals
        for _ in range(5):
            pad, _ = await self.engine.update("sess-1", text_emotion="happy")
        assert pad.p > 0.3  # should have moved significantly toward happy

    @pytest.mark.asyncio
    async def test_apply_touch_only(self):
        pad, emotion = await self.engine.apply_touch_only("sess-1", "poke")
        assert emotion in EMOTIONS

    @pytest.mark.asyncio
    async def test_empty_session(self):
        pad = await self.engine.get_pad("")
        neutral = PADState.neutral()
        assert abs(pad.p - neutral.p) < 1e-6


# ──────────────────────────────────────────────
# EmotionEngine PAD integration
# ──────────────────────────────────────────────

class TestEmotionEnginePAD:
    def setup_method(self):
        self.store = {}
        self.cache = MagicMock()

        async def mock_get(key):
            return self.store.get(key)

        async def mock_set(key, value, ttl=3600):
            self.store[key] = value

        async def mock_get_json(key):
            raw = self.store.get(key)
            if raw is None:
                return None
            import json
            return json.loads(raw)

        async def mock_set_json(key, value, ttl=3600):
            import json
            self.store[key] = json.dumps(value)

        self.cache.get = AsyncMock(side_effect=mock_get)
        self.cache.set = AsyncMock(side_effect=mock_set)
        self.cache.get_json = AsyncMock(side_effect=mock_get_json)
        self.cache.set_json = AsyncMock(side_effect=mock_set_json)

        self.engine = EmotionEngine(self.cache)

    @pytest.mark.asyncio
    async def test_update_with_pad_returns_discrete(self):
        pad, emotion = await self.engine.update_with_pad("sess-1", text_emotion="happy")
        assert emotion in EMOTIONS
        assert isinstance(pad, PADState)

    @pytest.mark.asyncio
    async def test_update_with_pad_syncs_discrete(self):
        """PAD update should also update the discrete emotion cache."""
        pad, emotion = await self.engine.update_with_pad("sess-1", text_emotion="happy")
        stored = await self.engine.get_emotion("sess-1")
        assert stored == emotion

    @pytest.mark.asyncio
    async def test_get_pad_state(self):
        await self.engine.update_with_pad("sess-1", text_emotion="angry")
        pad = await self.engine.get_pad_state("sess-1")
        assert isinstance(pad, PADState)
        # Should have moved toward angry (positive arousal)
        assert pad.a > 0

    def test_apply_tts_offsets_pad(self):
        pad = PADState(0.8, 0.5, 0.3)  # happy-like state
        pitch, rate = self.engine.apply_tts_offsets_pad(pad, 1.0, 1.0)
        assert pitch > 1.0  # happy → higher pitch
        assert rate > 1.0   # excited → faster rate

    def test_get_prompt_text_pad(self):
        pad = PADState(0.8, 0.6, 0.3)
        text = self.engine.get_prompt_text_pad(pad)
        assert "开心" in text or "心情" in text

    @pytest.mark.asyncio
    async def test_pad_touch_fusion(self):
        """Touch should visibly shift PAD when text is neutral."""
        # Establish a neutral baseline
        pad_no_touch, _ = await self.engine.update_with_pad("sess-a", text_emotion="calm")
        pad_with_pat, _ = await self.engine.update_with_pad("sess-b", text_emotion="calm", touch_gesture="pat")
        # Pat adds positive pleasure impulse, so with-pat should have higher P
        assert pad_with_pat.p > pad_no_touch.p

    @pytest.mark.asyncio
    async def test_legacy_methods_still_work(self):
        """Verify legacy discrete methods are unaffected."""
        await self.engine.set_emotion("sess-1", "happy")
        e = await self.engine.get_emotion("sess-1")
        assert e == "happy"

        detected = self.engine.detect_emotion("太好了！好开心！")
        assert detected == "happy"

        pitch, rate = self.engine.apply_tts_offsets("happy", 1.0, 1.0)
        assert pitch > 1.0


# ──────────────────────────────────────────────
# Data integrity
# ──────────────────────────────────────────────

class TestPADDataIntegrity:
    def test_all_touch_gestures_have_impulse(self):
        from ai_core.services.touch import TOUCH_GESTURES
        for gesture in TOUCH_GESTURES:
            assert gesture in TOUCH_PAD_IMPULSE

    def test_all_user_moods_have_pad(self):
        from ai_core.services.emotion import _USER_MOOD_KEYWORDS
        for mood in _USER_MOOD_KEYWORDS:
            assert mood in USER_MOOD_PAD

    def test_anchor_pleasure_range(self):
        for emotion, anchor in EMOTION_PAD_ANCHORS.items():
            assert -1.0 <= anchor.p <= 1.0, f"{emotion} P out of range"
            assert -1.0 <= anchor.a <= 1.0, f"{emotion} A out of range"
            assert -1.0 <= anchor.d <= 1.0, f"{emotion} D out of range"

    def test_impulse_reasonable_magnitude(self):
        for gesture, impulse in TOUCH_PAD_IMPULSE.items():
            mag = math.sqrt(impulse.p ** 2 + impulse.a ** 2 + impulse.d ** 2)
            assert mag < 1.5, f"{gesture} impulse too large: {mag}"
