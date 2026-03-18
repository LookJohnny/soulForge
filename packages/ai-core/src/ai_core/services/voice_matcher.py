"""Voice Persona Engine — matches characters to CosyVoice v3 voices.

Uses the expanded v3 voice library (60+ voices) for more precise matching,
with optional instruct mode for voices that support it.
"""

# ─── CosyVoice v3 voice library ─────────────────
# Curated subset with character-relevant traits

V3_VOICES = {
    # Cute / childlike
    "longhuhu_v3":      {"gender": "female", "age": "child",  "style": "cute",      "energy": 85},
    "longjielidou_v3":  {"gender": "female", "age": "child",  "style": "energetic",  "energy": 90},
    "longpaopao_v3":    {"gender": "female", "age": "child",  "style": "playful",    "energy": 80},
    "longniuniu_v3":    {"gender": "female", "age": "child",  "style": "sweet",      "energy": 75},
    # Young female
    "longxiaochun_v3":  {"gender": "female", "age": "young",  "style": "sweet",      "energy": 70},
    "longmiao_v3":      {"gender": "female", "age": "young",  "style": "gentle",     "energy": 55},
    "longfeifei_v3":    {"gender": "female", "age": "young",  "style": "bright",     "energy": 75},
    "longdaiyu_v3":     {"gender": "female", "age": "young",  "style": "literary",   "energy": 30},
    # Mature female
    "longyue_v3":       {"gender": "female", "age": "adult",  "style": "elegant",    "energy": 35},
    "longshu_v3":       {"gender": "female", "age": "adult",  "style": "calm",       "energy": 30},
    "longanrou_v3":     {"gender": "female", "age": "adult",  "style": "gentle",     "energy": 40},
    "longxiaoxia_v3":   {"gender": "female", "age": "adult",  "style": "warm",       "energy": 45},
    "longxiu_v3":       {"gender": "female", "age": "adult",  "style": "composed",   "energy": 30},
    # Young male
    "longshuo_v3":      {"gender": "male",   "age": "young",  "style": "bright",     "energy": 75},
    "longfei_v3":       {"gender": "male",   "age": "young",  "style": "energetic",  "energy": 80},
    "longhao_v3":       {"gender": "male",   "age": "young",  "style": "warm",       "energy": 65},
    # Mature male
    "longcheng_v3":     {"gender": "male",   "age": "adult",  "style": "deep",       "energy": 25},
    "longze_v3":        {"gender": "male",   "age": "adult",  "style": "steady",     "energy": 30},
    "longyan_v3":       {"gender": "male",   "age": "adult",  "style": "authoritative", "energy": 35},
    "longlaotie_v3":    {"gender": "male",   "age": "adult",  "style": "hearty",     "energy": 80},
    "longqiang_v3":     {"gender": "male",   "age": "adult",  "style": "rugged",     "energy": 50},
    # Special
    "longlaobo_v3":     {"gender": "male",   "age": "elderly", "style": "wise",      "energy": 20},
    "longlaoyi_v3":     {"gender": "female", "age": "elderly", "style": "kind",      "energy": 25},
    "longjiqi_v3":      {"gender": "neutral","age": "adult",  "style": "robotic",    "energy": 40},
}


# ─── Species → voice mapping ─────────────────────

SPECIES_ARCHETYPES = {
    "tiny_cute": {
        "keywords": ["猫", "小猫", "猫咪", "喵", "兔", "兔子", "小兔", "仓鼠", "松鼠", "刺猬", "小鸟", "小鸡", "小鸭", "奶猫", "奶狗"],
        "prefer_voices": ["longhuhu_v3", "longniuniu_v3", "longpaopao_v3"],
        "prefer_traits": {"age": "child", "style": ["cute", "sweet", "playful"]},
        "instruction": "用甜美软萌的奶音说话，语气轻柔活泼，像可爱的小动物",
    },
    "small_playful": {
        "keywords": ["狗", "小狗", "犬", "狗狗", "柴犬", "柯基", "企鹅", "猴", "猴子", "浣熊", "水獭", "鹦鹉", "小鹿"],
        "prefer_voices": ["longjielidou_v3", "longhuhu_v3", "longfeifei_v3"],
        "prefer_traits": {"age": "child", "style": ["energetic", "playful", "bright"]},
        "instruction": "用明亮开朗的声音说话，语气活泼热情，元气满满",
    },
    "elegant_mystical": {
        "keywords": ["狐", "狐狸", "独角兽", "仙鹤", "凤凰", "孔雀", "天鹅", "白鸽", "仙女", "精灵", "小精灵", "花仙子", "天使"],
        "prefer_voices": ["longyue_v3", "longdaiyu_v3", "longmiao_v3"],
        "prefer_traits": {"style": ["elegant", "literary", "gentle"]},
        "instruction": "用优雅空灵的声音缓缓说话，温柔从容，带神秘气质",
    },
    "big_gentle": {
        "keywords": ["熊", "大熊", "熊猫", "大熊猫", "北极熊", "河马", "大象", "牛", "水牛", "海豹", "海象", "树懒"],
        "prefer_voices": ["longcheng_v3", "longze_v3", "longhao_v3"],
        "prefer_traits": {"style": ["deep", "steady", "warm"]},
        "instruction": "用低沉浑厚的嗓音慢慢说话，温和憨厚，可靠踏实",
    },
    "fierce_powerful": {
        "keywords": ["龙", "恐龙", "老虎", "狮子", "豹", "鹰", "老鹰", "猎豹", "鲨鱼", "狼", "野猪", "犀牛", "鳄鱼"],
        "prefer_voices": ["longyan_v3", "longcheng_v3", "longqiang_v3"],
        "prefer_traits": {"style": ["authoritative", "deep", "rugged"]},
        "instruction": "用威严深沉的声音说话，庄重有力，不怒自威",
    },
    "cool_mysterious": {
        "keywords": ["蛇", "蜥蜴", "猫头鹰", "乌鸦", "蝙蝠", "蜘蛛", "蝎子", "黑猫", "暗影"],
        "prefer_voices": ["longxiu_v3", "longdaiyu_v3", "longshu_v3"],
        "prefer_traits": {"style": ["composed", "literary", "calm"]},
        "instruction": "用冷静低沉的语调说话，不紧不慢，神秘莫测",
    },
    "mechanical_artificial": {
        "keywords": ["机器人", "机器", "AI", "人工智能", "赛博", "数码", "芯片", "外星", "外星人", "星际"],
        "prefer_voices": ["longjiqi_v3", "longze_v3"],
        "prefer_traits": {"style": ["robotic", "steady"]},
        "instruction": "用平稳冷静的语调说话，吐字清晰精准，语速均匀",
    },
    "insect_tiny": {
        "keywords": ["虫", "毛毛虫", "蝴蝶", "蜜蜂", "瓢虫", "蚂蚁", "蜻蜓", "萤火虫", "蟋蟀"],
        "prefer_voices": ["longpaopao_v3", "longhuhu_v3", "longniuniu_v3"],
        "prefer_traits": {"age": "child", "style": ["playful", "cute"]},
        "instruction": "用细小轻快的声音说话，语速稍快，灵动跳跃",
    },
    "elderly_wise": {
        "keywords": ["老爷爷", "老奶奶", "智者", "长老", "仙人", "大师", "禅师"],
        "prefer_voices": ["longlaobo_v3", "longlaoyi_v3"],
        "prefer_traits": {"age": "elderly", "style": ["wise", "kind"]},
        "instruction": "用沉稳慈祥的声音缓缓说话，从容不迫",
    },
}

PERSONALITY_MODIFIERS = {
    "high_warmth": "，充满关心和温暖",
    "high_humor": "，带着调皮俏皮的语气",
    "low_energy": "，语气慵懒放松",
    "high_energy": "，充满活力和激情",
    "shy": "，语气有些害羞怯怯的",
}


def _classify_species(species: str) -> dict | None:
    species_lower = species.strip()
    for archetype in SPECIES_ARCHETYPES.values():
        if species_lower in archetype["keywords"]:
            return archetype
    for archetype in SPECIES_ARCHETYPES.values():
        for kw in archetype["keywords"]:
            if kw in species_lower or species_lower in kw:
                return archetype
    return None


def _score_voice(vid: str, profile: dict, archetype: dict | None, age_setting: int | None, personality: dict | None) -> float:
    score = 0.0
    if archetype:
        if vid in archetype.get("prefer_voices", []):
            idx = archetype["prefer_voices"].index(vid)
            score += 5.0 - idx * 1.0
        traits = archetype.get("prefer_traits", {})
        if traits.get("age") and profile["age"] == traits["age"]:
            score += 2.0
        for s in traits.get("style", []):
            if profile["style"] == s:
                score += 1.5
                break

    if age_setting is not None:
        if age_setting <= 8 and profile["age"] == "child": score += 3.0
        elif age_setting <= 8 and profile["age"] == "young": score += 1.0
        elif age_setting <= 18 and profile["age"] == "young": score += 2.0
        elif age_setting > 60 and profile["age"] == "elderly": score += 3.0
        elif age_setting > 18 and profile["age"] == "adult": score += 1.0

    if personality:
        combined_energy = (personality.get("energy", 50) + personality.get("extrovert", 50)) / 2
        energy_diff = abs(combined_energy - profile["energy"])
        score += max(0, 2.0 - energy_diff / 20)
        if personality.get("warmth", 50) > 75 and profile["style"] in ("sweet", "warm", "gentle", "kind"):
            score += 1.0

    return score


def _build_instruction(archetype: dict | None, personality: dict | None) -> str:
    if not archetype:
        return "用自然亲切的声音说话"
    base = archetype["instruction"]
    if personality:
        w, h, e, x = personality.get("warmth",50), personality.get("humor",50), personality.get("energy",50), personality.get("extrovert",50)
        mod = ""
        if w > 80: mod = PERSONALITY_MODIFIERS["high_warmth"]
        elif h > 80: mod = PERSONALITY_MODIFIERS["high_humor"]
        elif e < 25: mod = PERSONALITY_MODIFIERS["low_energy"]
        elif e > 85: mod = PERSONALITY_MODIFIERS["high_energy"]
        elif x < 25: mod = PERSONALITY_MODIFIERS["shy"]
        combined = base + mod
        if sum(2 if ord(c)>127 else 1 for c in combined) <= 100:
            base = combined
    return base


def match_voice(species="", age_setting=None, personality=None, relationship=None) -> dict:
    archetype = _classify_species(species)

    scores = {vid: _score_voice(vid, p, archetype, age_setting, personality) for vid, p in V3_VOICES.items()}
    best_vid = max(scores, key=scores.get)  # type: ignore

    instruction = _build_instruction(archetype, personality)

    archetype_name = "default"
    if archetype:
        for name, a in SPECIES_ARCHETYPES.items():
            if a is archetype:
                archetype_name = name
                break

    return {
        "voice_id": best_vid,
        "instruction": instruction,
        "speed": 1.0,
        "pitch_rate": 0,
        "speech_rate": 0,
        "reason": f"[{archetype_name}] {species} → {best_vid}",
    }
