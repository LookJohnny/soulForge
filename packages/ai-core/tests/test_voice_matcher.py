"""Tests for the Voice Matcher service."""

from ai_core.services.voice_matcher import (
    VOICES,
    _build_character_vector,
    _classify_species,
    _generate_instruction,
    match_voice,
)


# ─── Species classification ────────────────────────


class TestClassifySpecies:
    def test_small_cat(self):
        sp = _classify_species("小猫")
        assert sp["gender_hint"] == "female"
        assert sp["m_offset"] < 0

    def test_cat_keyword(self):
        sp = _classify_species("猫")
        assert sp["gender_hint"] == "female"

    def test_large_bear(self):
        sp = _classify_species("熊")
        assert sp["m_offset"] > 0

    def test_mythic_dragon(self):
        sp = _classify_species("龙")
        assert sp["gender_hint"] == "male"
        assert sp["g_offset"] >= 20

    def test_unknown_species_returns_default(self):
        sp = _classify_species("外星土豆怪")
        # Unknown species gets some default — the function doesn't crash
        assert isinstance(sp, dict)

    def test_empty_string_returns_dict(self):
        sp = _classify_species("")
        assert isinstance(sp, dict)

    def test_partial_match_works(self):
        """Species containing a keyword should still match."""
        sp = _classify_species("小猫咪")
        assert sp["gender_hint"] == "female"

    def test_ethereal_unicorn(self):
        sp = _classify_species("独角兽")
        assert sp["gender_hint"] == "female"

    def test_shadow_snake(self):
        sp = _classify_species("蛇")
        assert sp["gender_hint"] is None  # shadow category is gender-neutral

    def test_elder_grandpa(self):
        sp = _classify_species("老爷爷")
        assert sp["m_offset"] == 30

    def test_mech_robot(self):
        sp = _classify_species("机器人")
        assert sp["g_offset"] == 15


# ─── Species → voice matching (end-to-end) ──────────


class TestSpeciesVoiceMatching:
    def test_cat_gets_child_or_female_voice(self):
        result = match_voice(species="小猫")
        voice = VOICES[result["voice_id"]]
        assert voice["gender"] == "female"
        # Child/young voice expected for a small cat
        assert voice["m"] <= 40

    def test_bear_gets_male_voice(self):
        result = match_voice(species="熊")
        voice = VOICES[result["voice_id"]]
        assert voice["gender"] == "male"

    def test_dragon_gets_authoritative_voice(self):
        result = match_voice(species="龙")
        voice = VOICES[result["voice_id"]]
        assert voice["gender"] == "male"
        # Dragon should get a voice with high gravity
        assert voice["g"] >= 40

    def test_rabbit_gets_female_voice(self):
        result = match_voice(species="兔子")
        voice = VOICES[result["voice_id"]]
        assert voice["gender"] == "female"


# ─── Gender hints affect matching ───────────────────


class TestGenderHints:
    def test_large_animal_prefers_male(self):
        result = match_voice(species="大象")
        voice = VOICES[result["voice_id"]]
        assert voice["gender"] == "male"

    def test_small_animal_prefers_female(self):
        result = match_voice(species="蝴蝶")
        voice = VOICES[result["voice_id"]]
        assert voice["gender"] == "female"

    def test_medium_animal_allows_any_gender(self):
        """Medium animals have no gender hint, so matching should not crash."""
        result = match_voice(species="狗")
        assert result["voice_id"] in VOICES

    def test_neutral_species_allows_any_gender(self):
        result = match_voice(species="未知生物")
        assert result["voice_id"] in VOICES


# ─── Personality affects matching ───────────────────


class TestPersonalityAffectsMatching:
    def test_high_warmth_gets_warm_voice(self):
        result = match_voice(
            species="狗",
            personality={"warmth": 95, "energy": 50, "extrovert": 50, "humor": 50, "curiosity": 50},
        )
        voice = VOICES[result["voice_id"]]
        assert voice["w"] >= 55  # Voice should lean warm

    def test_low_warmth_gets_cold_voice(self):
        result = match_voice(
            species="狗",
            personality={"warmth": 10, "energy": 20, "extrovert": 20, "humor": 15, "curiosity": 30},
        )
        voice = VOICES[result["voice_id"]]
        assert voice["w"] <= 55  # Voice should lean cold/neutral

    def test_high_energy_gets_energetic_voice(self):
        result = match_voice(
            species="狗",
            personality={"warmth": 50, "energy": 95, "extrovert": 95, "humor": 50, "curiosity": 50},
        )
        voice = VOICES[result["voice_id"]]
        assert voice["e"] >= 40  # Voice should have some energy

    def test_low_energy_gets_calm_voice(self):
        result = match_voice(
            species="狗",
            personality={"warmth": 50, "energy": 10, "extrovert": 10, "humor": 50, "curiosity": 50},
        )
        voice = VOICES[result["voice_id"]]
        assert voice["e"] <= 60  # Voice should not be overly energetic

    def test_high_humor_reduces_gravity(self):
        """Characters with high humor should get less grave voices."""
        vec = _build_character_vector(
            "狗", age_setting=None,
            personality={"warmth": 50, "energy": 50, "extrovert": 50, "humor": 90, "curiosity": 50},
            relationship=None,
        )
        assert vec["g"] < 30  # Humor reduces gravity significantly

    def test_low_humor_increases_gravity(self):
        vec = _build_character_vector(
            "狗", age_setting=None,
            personality={"warmth": 50, "energy": 50, "extrovert": 50, "humor": 10, "curiosity": 50},
            relationship=None,
        )
        assert vec["g"] > 30  # Serious characters have more gravity

    def test_high_curiosity_reduces_maturity(self):
        vec = _build_character_vector(
            "狗", age_setting=None,
            personality={"warmth": 50, "energy": 50, "extrovert": 50, "humor": 50, "curiosity": 90},
            relationship=None,
        )
        vec_low_curiosity = _build_character_vector(
            "狗", age_setting=None,
            personality={"warmth": 50, "energy": 50, "extrovert": 50, "humor": 50, "curiosity": 30},
            relationship=None,
        )
        assert vec["m"] < vec_low_curiosity["m"]


# ─── Age affects matching ───────────────────────────


class TestAgeAffectsMatching:
    def test_young_child_gets_child_voice(self):
        result = match_voice(
            species="兔子", age_setting=3,
            personality={"warmth": 70, "energy": 80, "extrovert": 70, "humor": 60, "curiosity": 80},
        )
        voice = VOICES[result["voice_id"]]
        assert voice["m"] <= 30  # Child voice should have low maturity

    def test_elderly_gets_mature_voice(self):
        result = match_voice(
            species="熊", age_setting=80,
            personality={"warmth": 70, "energy": 20, "extrovert": 30, "humor": 40, "curiosity": 30},
        )
        voice = VOICES[result["voice_id"]]
        assert voice["m"] >= 50  # Elderly voice should have high maturity

    def test_age_5_reduces_maturity(self):
        vec = _build_character_vector("狗", age_setting=5, personality=None, relationship=None)
        vec_none = _build_character_vector("狗", age_setting=None, personality=None, relationship=None)
        assert vec["m"] < vec_none["m"]
        assert vec["g"] < vec_none["g"]

    def test_age_10_reduces_maturity_less(self):
        vec_5 = _build_character_vector("狗", age_setting=5, personality=None, relationship=None)
        vec_10 = _build_character_vector("狗", age_setting=10, personality=None, relationship=None)
        assert vec_10["m"] > vec_5["m"]  # Age 10 less childish than age 5

    def test_age_30_increases_maturity(self):
        vec = _build_character_vector("狗", age_setting=30, personality=None, relationship=None)
        vec_none = _build_character_vector("狗", age_setting=None, personality=None, relationship=None)
        assert vec["m"] > vec_none["m"]

    def test_age_60_increases_both(self):
        vec = _build_character_vector("狗", age_setting=60, personality=None, relationship=None)
        vec_none = _build_character_vector("狗", age_setting=None, personality=None, relationship=None)
        assert vec["m"] > vec_none["m"]
        assert vec["g"] > vec_none["g"]

    def test_age_none_uses_defaults(self):
        vec = _build_character_vector("狗", age_setting=None, personality=None, relationship=None)
        assert vec["m"] == 50.0  # Base maturity for medium species
        assert 0 <= vec["g"] <= 100


# ─── Relationship modifiers ────────────────────────


class TestRelationshipModifiers:
    def test_mentor_increases_maturity_and_gravity(self):
        vec_mentor = _build_character_vector("狗", None, None, "导师")
        vec_none = _build_character_vector("狗", None, None, None)
        assert vec_mentor["m"] > vec_none["m"]
        assert vec_mentor["g"] > vec_none["g"]

    def test_sidekick_decreases_both(self):
        vec = _build_character_vector("狗", None, None, "小跟班")
        vec_none = _build_character_vector("狗", None, None, None)
        assert vec["m"] < vec_none["m"]
        assert vec["g"] < vec_none["g"]

    def test_friend_decreases_gravity(self):
        vec = _build_character_vector("狗", None, None, "好朋友")
        vec_none = _build_character_vector("狗", None, None, None)
        assert vec["g"] < vec_none["g"]

    def test_unknown_relationship_ignored(self):
        vec = _build_character_vector("狗", None, None, "陌生人")
        vec_none = _build_character_vector("狗", None, None, None)
        assert vec["m"] == vec_none["m"]
        assert vec["g"] == vec_none["g"]


# ─── Unknown species don't crash ────────────────────


class TestUnknownSpecies:
    def test_empty_species(self):
        result = match_voice(species="")
        assert "voice_id" in result
        assert result["voice_id"] in VOICES

    def test_nonsense_species(self):
        result = match_voice(species="嘟嘟怪兽超级变形金刚")
        assert "voice_id" in result
        assert result["voice_id"] in VOICES

    def test_english_species(self):
        result = match_voice(species="unicorn")
        assert "voice_id" in result
        assert result["voice_id"] in VOICES

    def test_none_personality_and_age(self):
        result = match_voice(species="猫", age_setting=None, personality=None)
        assert "voice_id" in result


# ─── Instruction generation ─────────────────────────


class TestInstructionGeneration:
    def _char_count(self, s: str) -> int:
        """Count chars: CJK as 2, ASCII as 1 (mirrors the source logic)."""
        return sum(2 if ord(c) > 127 else 1 for c in s)

    def test_instruction_within_100_chars(self):
        """All species/personality combos should produce instructions <= 100 chars."""
        test_cases = [
            {"species": "小猫", "age_setting": 3, "personality": {"warmth": 90, "energy": 90, "extrovert": 90, "humor": 90, "curiosity": 90}},
            {"species": "龙", "age_setting": 100, "personality": {"warmth": 10, "energy": 10, "extrovert": 10, "humor": 10, "curiosity": 10}},
            {"species": "狗", "age_setting": None, "personality": None},
            {"species": "老爷爷", "age_setting": 80, "personality": {"warmth": 80, "energy": 10, "extrovert": 20, "humor": 30, "curiosity": 20}},
        ]
        for tc in test_cases:
            result = match_voice(**tc)
            char_count = self._char_count(result["instruction"])
            assert char_count <= 100, (
                f"Instruction too long ({char_count} chars) for {tc}: {result['instruction']}"
            )

    def test_instruction_is_nonempty(self):
        result = match_voice(species="猫")
        assert len(result["instruction"]) > 0

    def test_high_warmth_instruction_mentions_warm(self):
        vec = {"w": 85, "e": 50, "m": 50, "g": 30}
        instruction = _generate_instruction(vec, "猫")
        assert "温暖" in instruction or "亲切" in instruction

    def test_low_warmth_instruction_mentions_cold(self):
        vec = {"w": 15, "e": 50, "m": 50, "g": 30}
        instruction = _generate_instruction(vec, "猫")
        assert "冷淡" in instruction or "疏离" in instruction

    def test_high_energy_instruction_mentions_lively(self):
        vec = {"w": 50, "e": 85, "m": 50, "g": 30}
        instruction = _generate_instruction(vec, "猫")
        assert "活力" in instruction or "明亮" in instruction

    def test_low_energy_instruction_mentions_calm(self):
        vec = {"w": 50, "e": 20, "m": 50, "g": 30}
        instruction = _generate_instruction(vec, "猫")
        assert "低缓" in instruction or "沉静" in instruction

    def test_child_maturity_instruction(self):
        vec = {"w": 50, "e": 50, "m": 10, "g": 30}
        instruction = _generate_instruction(vec, "猫")
        assert "孩子" in instruction

    def test_high_maturity_instruction(self):
        vec = {"w": 50, "e": 50, "m": 80, "g": 30}
        instruction = _generate_instruction(vec, "猫")
        assert "阅历" in instruction or "沉稳" in instruction

    def test_high_gravity_instruction(self):
        vec = {"w": 50, "e": 50, "m": 50, "g": 80}
        instruction = _generate_instruction(vec, "猫")
        assert "庄重" in instruction

    def test_low_gravity_instruction(self):
        vec = {"w": 50, "e": 50, "m": 50, "g": 10}
        instruction = _generate_instruction(vec, "猫")
        assert "轻松" in instruction or "随意" in instruction

    def test_neutral_vector_fallback(self):
        """A perfectly neutral vector should still produce something."""
        vec = {"w": 50, "e": 50, "m": 50, "g": 50}
        instruction = _generate_instruction(vec, "猫")
        assert len(instruction) > 0
        # Falls through all branches, should get fallback
        assert "自然" in instruction


# ─── Return shape ───────────────────────────────────


class TestReturnShape:
    def test_all_keys_present(self):
        result = match_voice(species="猫")
        expected_keys = {"voice_id", "instruction", "speed", "pitch_rate", "speech_rate", "reason"}
        assert set(result.keys()) == expected_keys

    def test_speed_default(self):
        result = match_voice(species="猫")
        assert result["speed"] == 1.0

    def test_pitch_rate_default(self):
        result = match_voice(species="猫")
        assert result["pitch_rate"] == 0

    def test_speech_rate_default(self):
        result = match_voice(species="猫")
        assert result["speech_rate"] == 0

    def test_reason_contains_species(self):
        result = match_voice(species="龙")
        assert "龙" in result["reason"]

    def test_reason_contains_voice_label(self):
        result = match_voice(species="龙")
        vid = result["voice_id"]
        label = VOICES[vid]["label"]
        assert label in result["reason"]


# ─── Character vector clamping ──────────────────────


class TestVectorClamping:
    def test_values_clamped_to_0_100(self):
        """Even extreme inputs should result in clamped vectors."""
        vec = _build_character_vector(
            "龙", age_setting=200,
            personality={"warmth": 100, "energy": 100, "extrovert": 100, "humor": 0, "curiosity": 0},
            relationship="导师",
        )
        for key in ("w", "e", "m", "g"):
            assert 0 <= vec[key] <= 100, f"{key}={vec[key]} out of bounds"

    def test_extreme_low_inputs_clamped(self):
        vec = _build_character_vector(
            "小猫", age_setting=1,
            personality={"warmth": 0, "energy": 0, "extrovert": 0, "humor": 100, "curiosity": 100},
            relationship="小跟班",
        )
        for key in ("w", "e", "m", "g"):
            assert 0 <= vec[key] <= 100, f"{key}={vec[key]} out of bounds"
