"""Voice Persona Engine — personality-vector-driven voice matching + SSML effects.

Core idea: Every voice and every character both have a personality vector
on 4 dimensions: warmth, energy, maturity, gravity.

Match by finding the voice with the smallest distance to the character's vector.

SSML parameters (pitch, rate, effect) are computed per species archetype
and fine-tuned by personality traits and age, then passed to the TTS engine
as `<speak pitch="X" rate="Y" effect="Z">text</speak>`.
"""

import math


# ─── Voice Library with Personality Vectors ──────
# Each voice is profiled on 4 dimensions (0-100):
#   warmth:   0=冷酷/机械  →  100=温暖/亲切
#   energy:   0=沉静/慵懒  →  100=活泼/元气
#   maturity: 0=稚嫩/童声  →  100=苍老/沧桑
#   gravity:  0=轻松/俏皮  →  100=庄重/威严

VOICES = {
    # ─── Child / cute (neutral gender — works for any small character) ─────
    "longhuhu_v3":     {"w": 70, "e": 85, "m": 10, "g": 5,  "gender": "female",  "label": "活泼童声"},
    "longjielidou_v3": {"w": 60, "e": 90, "m": 12, "g": 5,  "gender": "female",  "label": "元气童声"},
    "longpaopao_v3":   {"w": 65, "e": 80, "m": 15, "g": 8,  "gender": "female",  "label": "俏皮童声"},
    "longniuniu_v3":   {"w": 80, "e": 65, "m": 10, "g": 5,  "gender": "female",  "label": "软糯童声"},
    # ─── Young female ─────
    "longxiaochun_v3": {"w": 75, "e": 60, "m": 25, "g": 10, "gender": "female",  "label": "甜美少女"},
    "longmiao_v3":     {"w": 70, "e": 45, "m": 30, "g": 15, "gender": "female",  "label": "温柔少女"},
    "longfeifei_v3":   {"w": 55, "e": 75, "m": 25, "g": 12, "gender": "female",  "label": "明亮少女"},
    "longdaiyu_v3":    {"w": 50, "e": 20, "m": 35, "g": 40, "gender": "female",  "label": "文艺忧郁"},
    # ─── Mature female ────
    "longyue_v3":      {"w": 55, "e": 25, "m": 55, "g": 50, "gender": "female",  "label": "优雅知性"},
    "longshu_v3":      {"w": 45, "e": 20, "m": 55, "g": 45, "gender": "female",  "label": "沉稳女声"},
    "longanrou_v3":    {"w": 75, "e": 35, "m": 45, "g": 20, "gender": "female",  "label": "温婉柔和"},
    "longxiaoxia_v3":  {"w": 70, "e": 40, "m": 40, "g": 15, "gender": "female",  "label": "亲切姐姐"},
    "longxiu_v3":      {"w": 35, "e": 18, "m": 60, "g": 55, "gender": "female",  "label": "冷静从容"},
    # ─── Young male ───────
    "longshuo_v3":     {"w": 55, "e": 70, "m": 30, "g": 15, "gender": "male",    "label": "阳光少年"},
    "longfei_v3":      {"w": 50, "e": 80, "m": 28, "g": 12, "gender": "male",    "label": "活力少年"},
    "longhao_v3":      {"w": 80, "e": 50, "m": 38, "g": 25, "gender": "male",    "label": "温暖大哥"},
    # ─── Mature male ──────
    "longcheng_v3":    {"w": 25, "e": 15, "m": 75, "g": 85, "gender": "male",    "label": "深沉威严"},
    "longze_v3":       {"w": 40, "e": 22, "m": 70, "g": 65, "gender": "male",    "label": "沉稳可靠"},
    "longyan_v3":      {"w": 30, "e": 30, "m": 72, "g": 80, "gender": "male",    "label": "威严权威"},
    "longlaotie_v3":   {"w": 75, "e": 75, "m": 50, "g": 10, "gender": "male",    "label": "豪爽热情"},
    "longqiang_v3":    {"w": 45, "e": 45, "m": 60, "g": 50, "gender": "male",    "label": "粗犷质朴"},
    # ─── Special ──────────
    "longlaobo_v3":    {"w": 70, "e": 12, "m": 90, "g": 55, "gender": "male",    "label": "慈祥老者"},
    "longlaoyi_v3":    {"w": 80, "e": 15, "m": 88, "g": 40, "gender": "female",  "label": "慈爱老奶奶"},
    "longjiqi_v3":     {"w": 20, "e": 35, "m": 50, "g": 60, "gender": "neutral", "label": "机械冷静"},
}


# ─── Species size/type hints ─────────────────────
# Only affects maturity and gravity slightly — personality is the PRIMARY driver

SPECIES_MODIFIERS = {
    # small animals: lower maturity, lower gravity, prefer female voices
    "tiny":  {"m_offset": -15, "g_offset": -10, "gender_hint": "female",
              "keywords": ["猫", "小猫", "猫咪", "兔", "兔子", "仓鼠", "松鼠", "刺猬",
                           "小鸟", "小鸡", "小鸭", "虫", "毛毛虫", "蝴蝶", "蜜蜂",
                           "瓢虫", "蚂蚁", "蜻蜓", "萤火虫"]},
    # medium animals: neutral gender
    "medium": {"m_offset": 0, "g_offset": 0, "gender_hint": None,
               "keywords": ["狗", "小狗", "犬", "柯基", "柴犬", "企鹅", "狐", "狐狸",
                            "猴", "猴子", "浣熊", "鹦鹉", "小鹿", "水獭"]},
    # large animals: prefer male voices
    "large":  {"m_offset": 8, "g_offset": 5, "gender_hint": "male",
               "keywords": ["熊", "大熊", "熊猫", "北极熊", "河马", "大象", "牛",
                            "海豹", "海象", "树懒"]},
    # powerful/mythical: push clearly into mature male range
    "mythic": {"m_offset": 18, "g_offset": 25, "gender_hint": "male",
               "keywords": ["龙", "恐龙", "老虎", "狮子", "狼", "鹰", "豹", "鲨鱼",
                            "犀牛", "鳄鱼", "凤凰"]},
    "ethereal": {"m_offset": 3, "g_offset": 5, "gender_hint": "female",
                 "keywords": ["独角兽", "仙鹤", "天鹅", "仙女", "精灵", "小精灵",
                              "花仙子", "天使", "孔雀"]},
    "shadow": {"m_offset": 8, "g_offset": 10, "gender_hint": None,
               "keywords": ["蛇", "蜥蜴", "猫头鹰", "乌鸦", "蝙蝠", "蜘蛛", "黑猫"]},
    "mech":   {"m_offset": 8, "g_offset": 15, "gender_hint": None,
               "keywords": ["机器人", "机器", "AI", "人工智能", "外星", "外星人"]},
    "elder":  {"m_offset": 30, "g_offset": 10, "gender_hint": None,
               "keywords": ["老爷爷", "老奶奶", "智者", "长老", "仙人", "大师"]},
    # ─── Human archetypes (non-animal characters) ──────
    "child_human":  {"m_offset": -20, "g_offset": -15, "gender_hint": None,
                     "keywords": ["小男孩", "小女孩", "小朋友", "小学生"]},
    "teen_human":   {"m_offset": -5, "g_offset": -5, "gender_hint": None,
                     "keywords": ["少年", "少女", "中学生", "高中生", "学生"]},
    "adult_female": {"m_offset": 5, "g_offset": 0, "gender_hint": "female",
                     "keywords": ["姐姐", "老师", "妈妈", "阿姨", "女声助手", "温柔姐姐"]},
    "adult_male":   {"m_offset": 10, "g_offset": 5, "gender_hint": "male",
                     "keywords": ["哥哥", "叔叔", "爸爸", "男声助手", "教练"]},
    "abstract_assistant": {"m_offset": 0, "g_offset": 0, "gender_hint": None,
                           "keywords": ["助手", "语音助手", "AI助手", "智能助手"]},
}


# ─── SSML profiles per species archetype ──────────
# pitch: 0.5-2.0 (1.0=normal), rate: 0.5-2.0 (1.0=normal)
# effect: "lolita" | "robot" | "echo" | "lowpass" | "" (none)

SSML_PROFILES = {
    "tiny":     {"pitch": 1.35, "rate": 1.1,  "effect": "lolita"},   # 奶声奶气，萌
    "medium":   {"pitch": 1.2,  "rate": 1.15, "effect": "lolita"},   # 活泼元气萌
    "large":    {"pitch": 0.7,  "rate": 0.85, "effect": ""},         # 低沉浑厚
    "mythic":   {"pitch": 0.6,  "rate": 0.8,  "effect": ""},         # 威严深沉
    "ethereal": {"pitch": 1.15, "rate": 0.9,  "effect": ""},         # 空灵优雅
    "shadow":   {"pitch": 0.85, "rate": 0.8,  "effect": "echo"},     # 神秘回响
    "mech":     {"pitch": 0.9,  "rate": 0.95, "effect": "robot"},    # 机械金属
    "elder":    {"pitch": 0.8,  "rate": 0.75, "effect": ""},         # 苍老慈祥
    # Human archetypes
    "child_human":  {"pitch": 1.25, "rate": 1.05, "effect": "lolita"},  # 童声
    "teen_human":   {"pitch": 1.1,  "rate": 1.0,  "effect": ""},        # 少年少女
    "adult_female": {"pitch": 1.0,  "rate": 0.95, "effect": ""},        # 温柔女声
    "adult_male":   {"pitch": 0.85, "rate": 0.9,  "effect": ""},        # 沉稳男声
    "abstract_assistant": {"pitch": 1.0, "rate": 1.0, "effect": ""},    # 中性标准
}

# Default SSML for unknown species
_DEFAULT_SSML = {"pitch": 1.0, "rate": 1.0, "effect": ""}

# Relationship modifiers
RELATIONSHIP_MODIFIERS = {
    "守护者":   {"m_offset": 8, "g_offset": 5},
    "导师":     {"m_offset": 10, "g_offset": 10},
    "好朋友":   {"m_offset": 0, "g_offset": -5},
    "小跟班":   {"m_offset": -8, "g_offset": -8},
    "兄弟姐妹": {"m_offset": 0, "g_offset": -3},
    "手足":     {"m_offset": 0, "g_offset": -3},
}


def _classify_species(species: str) -> dict:
    """Get species size modifiers. Exact match first, then fuzzy."""
    # Pass 1: exact match across ALL categories
    for cat in SPECIES_MODIFIERS.values():
        if species in cat["keywords"]:
            return cat
    # Pass 2: fuzzy match (keyword contains species or vice versa)
    # Prefer longer keyword matches to avoid "熊" matching "浣熊" before "熊" category
    best_match = None
    best_len_diff = 999
    for cat in SPECIES_MODIFIERS.values():
        for kw in cat["keywords"]:
            if kw in species or species in kw:
                diff = abs(len(kw) - len(species))
                if diff < best_len_diff:
                    best_len_diff = diff
                    best_match = cat
    if best_match:
        return best_match
    return {"m_offset": 0, "g_offset": 0, "gender_hint": None}


def _build_character_vector(
    species: str, age_setting: int | None, personality: dict | None, relationship: str | None
) -> dict:
    """Compute a 4D personality vector for the character."""
    p = personality or {}

    # Start from raw personality traits
    warmth = p.get("warmth", 50)
    energy = (p.get("energy", 50) + p.get("extrovert", 50)) / 2  # Combined energy
    maturity = 50.0  # Base
    gravity = 30.0   # Base — slightly light

    # Age affects maturity
    if age_setting is not None:
        if age_setting <= 5:
            maturity -= 25
            gravity -= 15
        elif age_setting <= 10:
            maturity -= 15
            gravity -= 8
        elif age_setting <= 18:
            maturity -= 5
        elif age_setting <= 40:
            maturity += 5
        elif age_setting <= 70:
            maturity += 15
            gravity += 5
        else:
            maturity += 25
            gravity += 10

    # Species modifiers
    sp = _classify_species(species)
    maturity += sp.get("m_offset", 0)
    gravity += sp.get("g_offset", 0)

    # Relationship modifiers
    if relationship and relationship in RELATIONSHIP_MODIFIERS:
        rm = RELATIONSHIP_MODIFIERS[relationship]
        maturity += rm.get("m_offset", 0)
        gravity += rm.get("g_offset", 0)

    # Personality fine-tuning of gravity
    humor = p.get("humor", 50)
    curiosity = p.get("curiosity", 50)
    if humor >= 65:
        gravity -= 18  # Humorous = much less grave (playful, light)
    elif humor > 45:
        gravity -= 5
    elif humor < 20:
        gravity += 10  # Serious = more grave

    # High curiosity = youthful feel
    if curiosity > 75:
        maturity -= 10

    # Clamp all values
    warmth = max(0, min(100, warmth))
    energy = max(0, min(100, energy))
    maturity = max(0, min(100, maturity))
    gravity = max(0, min(100, gravity))

    return {
        "w": warmth, "e": energy, "m": maturity, "g": gravity,
        "_humor": humor,  # raw value preserved for SSML micro-adjustments
    }


def _distance(a: dict, b: dict) -> float:
    """Weighted Euclidean distance between two personality vectors."""
    # Warmth and energy matter most, maturity and gravity are secondary
    dw = (a["w"] - b["w"]) * 1.2   # warmth weight: 1.2
    de = (a["e"] - b["e"]) * 1.0   # energy weight: 1.0
    dm = (a["m"] - b["m"]) * 0.8   # maturity weight: 0.8
    dg = (a["g"] - b["g"]) * 0.7   # gravity weight: 0.7
    return math.sqrt(dw*dw + de*de + dm*dm + dg*dg)


def _compute_ssml_params(
    species: str, char_vec: dict, age_setting: int | None
) -> dict:
    """Compute SSML parameters from species archetype + personality/age micro-adjustments.

    Returns: {"ssml_pitch": float, "ssml_rate": float, "ssml_effect": str}
    """
    # 1. Base profile from species archetype
    sp = _classify_species(species)
    # Find which archetype key matched
    archetype = None
    for key, cat in SPECIES_MODIFIERS.items():
        if cat is sp:
            archetype = key
            break
    profile = SSML_PROFILES.get(archetype or "", _DEFAULT_SSML)
    pitch = profile["pitch"]
    rate = profile["rate"]
    effect = profile["effect"]

    # 2. Personality micro-adjustments (additive)
    warmth = char_vec["w"]
    energy = char_vec["e"]
    humor = char_vec.get("_humor", 50)  # raw humor stored for SSML tuning

    if warmth > 80:
        pitch += 0.05
    if energy < 25:
        rate -= 0.05
    if humor > 70:
        rate += 0.05

    # 3. Age micro-adjustment
    if age_setting is not None and age_setting <= 5:
        pitch += 0.1
        if not effect:
            effect = "lolita"

    # 4. Clamp to valid ranges
    pitch = round(max(0.5, min(2.0, pitch)), 2)
    rate = round(max(0.5, min(2.0, rate)), 2)

    return {
        "ssml_pitch": pitch,
        "ssml_rate": rate,
        "ssml_effect": effect,
    }


def match_voice(
    species: str = "",
    age_setting: int | None = None,
    personality: dict | None = None,
    relationship: str | None = None,
) -> dict:
    """Match a character to the best voice using personality vector distance.

    Returns:
        {
            "voice_id": str,
            "ssml_pitch": float,   # 0.5-2.0
            "ssml_rate": float,    # 0.5-2.0
            "ssml_effect": str,    # "lolita"|"robot"|"echo"|"lowpass"|""
            "speed": float,
            "pitch_rate": int,
            "speech_rate": int,
            "reason": str,
        }
    """
    # 1. Build character personality vector
    char_vec = _build_character_vector(species, age_setting, personality, relationship)

    # 2. Find closest voice by distance, with gender filtering
    sp = _classify_species(species)
    gender_hint = sp.get("gender_hint")

    best_vid = ""
    best_dist = float("inf")
    for vid, voice in VOICES.items():
        voice_vec = {"w": voice["w"], "e": voice["e"], "m": voice["m"], "g": voice["g"]}
        dist = _distance(char_vec, voice_vec)

        # Gender penalty
        voice_gender = voice.get("gender", "neutral")
        if gender_hint:
            if voice_gender != "neutral" and voice_gender != gender_hint:
                dist += 35  # Strong penalty for wrong gender
            elif voice_gender == "neutral" and gender_hint in ("male", "female"):
                dist += 12  # Mild penalty — prefer gendered voice when hint exists

        if dist < best_dist:
            best_dist = dist
            best_vid = vid

    # 3. Compute SSML parameters
    ssml = _compute_ssml_params(species, char_vec, age_setting)

    label = VOICES[best_vid]["label"]

    return {
        "voice_id": best_vid,
        "ssml_pitch": ssml["ssml_pitch"],
        "ssml_rate": ssml["ssml_rate"],
        "ssml_effect": ssml["ssml_effect"],
        "speed": 1.0,
        "pitch_rate": 0,
        "speech_rate": 0,
        "reason": (
            f"{species} → {best_vid}({label}) "
            f"dist={best_dist:.0f} "
            f"char=[w={char_vec['w']:.0f} e={char_vec['e']:.0f} m={char_vec['m']:.0f} g={char_vec['g']:.0f}] "
            f"ssml=[pitch={ssml['ssml_pitch']} rate={ssml['ssml_rate']} effect={ssml['ssml_effect'] or 'none'}]"
        ),
    }
