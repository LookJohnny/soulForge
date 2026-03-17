"""Voice auto-matcher — selects the best voice + speed based on character traits.

When a character has no explicit voice assigned, this service analyzes
species, age, personality to pick the most fitting DashScope preset voice
and appropriate speech speed.
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

# Species → preferred voice traits
SPECIES_HINTS = {
    "猫":       {"pitch": "high", "energy": 65, "prefer_style": ["sweet", "energetic", "gentle"], "speed_boost": 0.08},
    "小猫":     {"pitch": "high", "energy": 75, "prefer_style": ["energetic", "sweet"], "speed_boost": 0.1},
    "兔子":     {"pitch": "high", "energy": 75, "prefer_style": ["sweet", "energetic"]},
    "熊":       {"pitch": "low",  "energy": 40, "prefer_style": ["gentle", "calm", "deep"]},
    "狗":       {"pitch": "medium", "energy": 70, "prefer_style": ["bright", "hearty"]},
    "狐狸":     {"pitch": "medium", "energy": 50, "prefer_style": ["elegant", "gentle"]},
    "龙":       {"pitch": "low",  "energy": 60, "prefer_style": ["deep", "calm"]},
    "企鹅":     {"pitch": "high", "energy": 55, "prefer_style": ["sweet", "bright"]},
    "独角兽":   {"pitch": "high", "energy": 50, "prefer_style": ["elegant", "gentle"]},
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

    # Calculate speed adjustment
    speed = 1.0
    # Species-specific speed boost (e.g., small animals sound cuter faster)
    speed += hints.get("speed_boost", 0)
    if age_setting is not None and age_setting <= 10:
        speed += 0.1  # Kids speak slightly faster
    if personality:
        energy = personality.get("energy", 50)
        if energy > 70:
            speed += 0.05
        elif energy < 30:
            speed -= 0.05
    speed = round(max(0.8, min(1.3, speed)), 2)

    return {
        "voice_id": best_vid,
        "speed": speed,
        "reason": f"species={species}, voice={best_vid}({best_profile['style']}), speed={speed}",
    }
