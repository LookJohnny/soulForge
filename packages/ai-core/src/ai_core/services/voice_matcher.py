"""Voice Persona Engine — builds a complete voice profile for each character.

Combines three layers:
1. Voice selection — pick the best DashScope preset
2. Pitch shift — DashScope pitch_rate (-500 to 500) to match species/age
3. Speech rate — DashScope speech_rate (-500 to 500) for energy/personality

When a character has no explicit voice assigned, this engine analyzes
species, age, personality to produce a complete voice persona.
"""


# DashScope CosyVoice preset profiles
VOICE_PROFILES = {
    "longxiaochun": {"gender": "female", "age": "young", "style": "sweet", "energy": 70, "pitch": "high"},
    "longxiaoxia":  {"gender": "female", "age": "adult", "style": "gentle", "energy": 40, "pitch": "medium"},
    "longshu":      {"gender": "female", "age": "adult", "style": "calm", "energy": 30, "pitch": "medium"},
    "longlaotie":   {"gender": "male",   "age": "adult", "style": "hearty", "energy": 80, "pitch": "low"},
    "longshuo":     {"gender": "male",   "age": "young", "style": "bright", "energy": 75, "pitch": "medium"},
    "longjielidou": {"gender": "female", "age": "child", "style": "energetic", "energy": 90, "pitch": "high"},
    "longyue":      {"gender": "female", "age": "adult", "style": "elegant", "energy": 35, "pitch": "medium"},
    "longcheng":    {"gender": "male",   "age": "adult", "style": "deep", "energy": 25, "pitch": "low"},
}

# Species → voice persona hints
# pitch_shift: DashScope pitch_rate value (-500 to 500), positive = higher
# speech_shift: DashScope speech_rate value (-500 to 500), positive = faster
SPECIES_HINTS = {
    "猫":       {"pitch": "high", "energy": 65, "prefer_style": ["sweet", "energetic", "gentle"],
                 "pitch_shift": 100, "speech_shift": 50},
    "小猫":     {"pitch": "high", "energy": 75, "prefer_style": ["energetic", "sweet"],
                 "pitch_shift": 150, "speech_shift": 80},
    "兔子":     {"pitch": "high", "energy": 75, "prefer_style": ["sweet", "energetic"],
                 "pitch_shift": 80, "speech_shift": 60},
    "熊":       {"pitch": "low",  "energy": 40, "prefer_style": ["gentle", "calm", "deep"],
                 "pitch_shift": -200, "speech_shift": -80},
    "狗":       {"pitch": "medium", "energy": 70, "prefer_style": ["bright", "hearty"],
                 "pitch_shift": 0, "speech_shift": 30},
    "狐狸":     {"pitch": "medium", "energy": 50, "prefer_style": ["elegant", "gentle"],
                 "pitch_shift": 50, "speech_shift": 0},
    "龙":       {"pitch": "low",  "energy": 60, "prefer_style": ["deep", "calm"],
                 "pitch_shift": -250, "speech_shift": -50},
    "企鹅":     {"pitch": "high", "energy": 55, "prefer_style": ["sweet", "bright"],
                 "pitch_shift": 100, "speech_shift": 20},
    "独角兽":   {"pitch": "high", "energy": 50, "prefer_style": ["elegant", "gentle"],
                 "pitch_shift": 60, "speech_shift": 0},
}


def match_voice(
    species: str = "",
    age_setting: int | None = None,
    personality: dict | None = None,
    relationship: str | None = None,
) -> dict:
    """Select the best voice and speed for a character.

    Returns:
        {"voice_id": str, "speed": float, "reason": str}
    """
    scores: dict[str, float] = {vid: 0.0 for vid in VOICE_PROFILES}

    # 1. Species matching
    hints = SPECIES_HINTS.get(species, {})
    preferred_pitch = hints.get("pitch", "medium")
    preferred_styles = hints.get("prefer_style", [])

    for vid, profile in VOICE_PROFILES.items():
        # Pitch match
        if profile["pitch"] == preferred_pitch:
            scores[vid] += 3.0
        elif (preferred_pitch == "high" and profile["pitch"] == "medium") or \
             (preferred_pitch == "low" and profile["pitch"] == "medium"):
            scores[vid] += 1.0

        # Style match
        if profile["style"] in preferred_styles:
            idx = preferred_styles.index(profile["style"])
            scores[vid] += 2.0 - idx * 0.3  # First preferred style gets highest score

    # 2. Age matching
    if age_setting is not None:
        for vid, profile in VOICE_PROFILES.items():
            if age_setting <= 8:
                if profile["age"] == "child":
                    scores[vid] += 3.0
                elif profile["age"] == "young":
                    scores[vid] += 1.5
            elif age_setting <= 18:
                if profile["age"] == "young":
                    scores[vid] += 2.0
            else:
                if profile["age"] == "adult":
                    scores[vid] += 1.5

    # 3. Personality energy matching
    if personality:
        char_energy = personality.get("energy", 50)
        char_extrovert = personality.get("extrovert", 50)
        char_warmth = personality.get("warmth", 50)
        combined_energy = (char_energy + char_extrovert) / 2

        for vid, profile in VOICE_PROFILES.items():
            voice_energy = profile["energy"]
            energy_diff = abs(combined_energy - voice_energy)
            scores[vid] += max(0, 2.0 - energy_diff / 25)

            # Warm characters → sweet/gentle voices
            if char_warmth > 70 and profile["style"] in ("sweet", "gentle"):
                scores[vid] += 1.0

    # Pick best
    best_vid = max(scores, key=scores.get)  # type: ignore
    best_profile = VOICE_PROFILES[best_vid]

    # ─── Pitch rate (DashScope -500 to 500) ───
    pitch_rate = hints.get("pitch_shift", 0)
    # Age adjusts pitch further
    if age_setting is not None:
        if age_setting <= 5:
            pitch_rate += 80   # Very young = higher pitch
        elif age_setting <= 10:
            pitch_rate += 40
        elif age_setting > 50:
            pitch_rate -= 30   # Older = slightly lower
    # Personality fine-tune
    if personality:
        energy = personality.get("energy", 50)
        if energy > 75:
            pitch_rate += 20
        elif energy < 25:
            pitch_rate -= 20
    pitch_rate = max(-500, min(500, pitch_rate))

    # ─── Speech rate (DashScope -500 to 500) ───
    speech_rate = hints.get("speech_shift", 0)
    if age_setting is not None and age_setting <= 10:
        speech_rate += 50
    if personality:
        energy = personality.get("energy", 50)
        extrovert = personality.get("extrovert", 50)
        speech_rate += int((energy - 50) * 0.5 + (extrovert - 50) * 0.3)
    speech_rate = max(-500, min(500, speech_rate))

    # Also compute a float speed for backward compatibility
    speed = round(1.0 + speech_rate / 500, 2)

    return {
        "voice_id": best_vid,
        "speed": speed,
        "pitch_rate": pitch_rate,
        "speech_rate": speech_rate,
        "reason": f"{species} → {best_vid}({best_profile['style']}), pitch={pitch_rate}, speech={speech_rate}",
    }
