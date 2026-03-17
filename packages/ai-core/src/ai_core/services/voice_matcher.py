"""Voice Persona Engine — builds a complete voice profile for each character.

Uses fuzzy species classification + personality analysis to produce:
1. Voice selection — best DashScope preset
2. Pitch shift — pitch_rate (-500 to 500)
3. Speech rate — speech_rate (-500 to 500)
"""


# ─── DashScope CosyVoice presets ──────────────────

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


# ─── Species classification via keyword matching ──

# Each archetype defines: voice preferences, base pitch_shift, base speech_shift
SPECIES_ARCHETYPES = {
    "tiny_cute": {
        "keywords": ["猫", "小猫", "猫咪", "喵", "兔", "兔子", "小兔", "仓鼠", "松鼠", "刺猬", "小鸟", "小鸡", "小鸭", "奶猫", "奶狗"],
        "pitch": "high", "prefer_style": ["sweet", "energetic"],
        "pitch_shift": 150, "speech_shift": 80,
    },
    "small_playful": {
        "keywords": ["狗", "小狗", "犬", "狗狗", "柴犬", "柯基", "企鹅", "猴", "猴子", "浣熊", "水獭", "鹦鹉", "小鹿"],
        "pitch": "high", "prefer_style": ["bright", "energetic", "sweet"],
        "pitch_shift": 80, "speech_shift": 60,
    },
    "elegant_mystical": {
        "keywords": ["狐", "狐狸", "独角兽", "仙鹤", "凤凰", "孔雀", "天鹅", "白鸽", "仙女", "精灵", "小精灵", "花仙子", "天使"],
        "pitch": "medium", "prefer_style": ["elegant", "gentle"],
        "pitch_shift": 60, "speech_shift": -20,
    },
    "big_gentle": {
        "keywords": ["熊", "大熊", "熊猫", "大熊猫", "北极熊", "河马", "大象", "牛", "水牛", "海豹", "海象", "树懒"],
        "pitch": "low", "prefer_style": ["gentle", "calm", "deep"],
        "pitch_shift": -200, "speech_shift": -80,
    },
    "fierce_powerful": {
        "keywords": ["龙", "恐龙", "老虎", "狮子", "豹", "鹰", "老鹰", "猎豹", "鲨鱼", "狼", "野猪", "犀牛", "鳄鱼"],
        "pitch": "low", "prefer_style": ["deep", "calm"],
        "pitch_shift": -250, "speech_shift": -50,
    },
    "cool_mysterious": {
        "keywords": ["蛇", "蜥蜴", "猫头鹰", "乌鸦", "蝙蝠", "蜘蛛", "蝎子", "黑猫", "暗影"],
        "pitch": "medium", "prefer_style": ["calm", "elegant"],
        "pitch_shift": -80, "speech_shift": -40,
    },
    "mechanical_artificial": {
        "keywords": ["机器人", "机器", "AI", "人工智能", "赛博", "数码", "芯片", "外星", "外星人", "星际"],
        "pitch": "medium", "prefer_style": ["calm", "deep"],
        "pitch_shift": -30, "speech_shift": -30,
    },
    "insect_tiny": {
        "keywords": ["虫", "毛毛虫", "蝴蝶", "蜜蜂", "瓢虫", "蚂蚁", "蜻蜓", "萤火虫", "蟋蟀"],
        "pitch": "high", "prefer_style": ["sweet", "energetic"],
        "pitch_shift": 200, "speech_shift": 50,
    },
}


def _classify_species(species: str) -> dict | None:
    """Classify a species string into an archetype using keyword matching."""
    species_lower = species.strip()
    # Exact match first
    for archetype in SPECIES_ARCHETYPES.values():
        if species_lower in archetype["keywords"]:
            return archetype
    # Fuzzy: check if species contains any keyword, or keyword contains species
    for archetype in SPECIES_ARCHETYPES.values():
        for kw in archetype["keywords"]:
            if kw in species_lower or species_lower in kw:
                return archetype
    return None


def match_voice(
    species: str = "",
    age_setting: int | None = None,
    personality: dict | None = None,
    relationship: str | None = None,
) -> dict:
    """Select the best voice, pitch_rate, and speech_rate for a character.

    Returns:
        {"voice_id": str, "speed": float, "pitch_rate": int, "speech_rate": int, "reason": str}
    """
    archetype = _classify_species(species)

    # ─── Voice selection scoring ───
    scores: dict[str, float] = {vid: 0.0 for vid in VOICE_PROFILES}

    if archetype:
        preferred_pitch = archetype.get("pitch", "medium")
        preferred_styles = archetype.get("prefer_style", [])

        for vid, profile in VOICE_PROFILES.items():
            if profile["pitch"] == preferred_pitch:
                scores[vid] += 3.0
            elif abs(["low", "medium", "high"].index(profile["pitch"]) -
                     ["low", "medium", "high"].index(preferred_pitch)) == 1:
                scores[vid] += 1.0
            if profile["style"] in preferred_styles:
                idx = preferred_styles.index(profile["style"])
                scores[vid] += 2.0 - idx * 0.3

    # Age weighting
    if age_setting is not None:
        for vid, profile in VOICE_PROFILES.items():
            if age_setting <= 8:
                if profile["age"] == "child": scores[vid] += 3.0
                elif profile["age"] == "young": scores[vid] += 1.5
            elif age_setting <= 18:
                if profile["age"] == "young": scores[vid] += 2.0
            else:
                if profile["age"] == "adult": scores[vid] += 1.5

    # Personality energy matching
    if personality:
        combined_energy = (personality.get("energy", 50) + personality.get("extrovert", 50)) / 2
        warmth = personality.get("warmth", 50)
        for vid, profile in VOICE_PROFILES.items():
            energy_diff = abs(combined_energy - profile["energy"])
            scores[vid] += max(0, 2.0 - energy_diff / 25)
            if warmth > 70 and profile["style"] in ("sweet", "gentle"):
                scores[vid] += 1.0

    best_vid = max(scores, key=scores.get)  # type: ignore
    best_profile = VOICE_PROFILES[best_vid]

    # ─── Pitch rate ───
    pitch_rate = archetype["pitch_shift"] if archetype else 0
    if age_setting is not None:
        if age_setting <= 5: pitch_rate += 80
        elif age_setting <= 10: pitch_rate += 40
        elif age_setting > 50: pitch_rate -= 30
    if personality:
        e = personality.get("energy", 50)
        if e > 75: pitch_rate += 20
        elif e < 25: pitch_rate -= 20
    pitch_rate = max(-500, min(500, pitch_rate))

    # ─── Speech rate ───
    speech_rate = archetype["speech_shift"] if archetype else 0
    if age_setting is not None and age_setting <= 10:
        speech_rate += 50
    if personality:
        e = personality.get("energy", 50)
        x = personality.get("extrovert", 50)
        speech_rate += int((e - 50) * 0.5 + (x - 50) * 0.3)
    speech_rate = max(-500, min(500, speech_rate))

    speed = round(1.0 + speech_rate / 500, 2)

    archetype_name = "unknown"
    if archetype:
        for name, a in SPECIES_ARCHETYPES.items():
            if a is archetype:
                archetype_name = name
                break

    return {
        "voice_id": best_vid,
        "speed": speed,
        "pitch_rate": pitch_rate,
        "speech_rate": speech_rate,
        "reason": f"[{archetype_name}] {species} → {best_vid}({best_profile['style']}), pitch={pitch_rate:+d}, speech={speech_rate:+d}",
    }
