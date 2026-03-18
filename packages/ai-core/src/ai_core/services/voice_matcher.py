"""Voice Persona Engine — personality-vector-driven voice matching.

Core idea: Every voice and every character both have a personality vector
on 4 dimensions: warmth, energy, maturity, gravity.

Match by finding the voice with the smallest distance to the character's vector.

The voice instruction is generated dynamically from the character's traits,
not hardcoded per species.
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
}

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
    """Get species size modifiers."""
    for cat in SPECIES_MODIFIERS.values():
        if species in cat["keywords"]:
            return cat
        for kw in cat["keywords"]:
            if kw in species or species in kw:
                return cat
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

    return {"w": warmth, "e": energy, "m": maturity, "g": gravity}


def _distance(a: dict, b: dict) -> float:
    """Weighted Euclidean distance between two personality vectors."""
    # Warmth and energy matter most, maturity and gravity are secondary
    dw = (a["w"] - b["w"]) * 1.2   # warmth weight: 1.2
    de = (a["e"] - b["e"]) * 1.0   # energy weight: 1.0
    dm = (a["m"] - b["m"]) * 0.8   # maturity weight: 0.8
    dg = (a["g"] - b["g"]) * 0.7   # gravity weight: 0.7
    return math.sqrt(dw*dw + de*de + dm*dm + dg*dg)


def _generate_instruction(char_vec: dict, species: str) -> str:
    """Generate a natural language voice instruction from personality vector."""
    parts = []

    # Warmth
    w = char_vec["w"]
    if w >= 80:
        parts.append("语气温暖亲切")
    elif w >= 60:
        parts.append("语气友善")
    elif w <= 25:
        parts.append("语气冷淡疏离")

    # Energy
    e = char_vec["e"]
    if e >= 75:
        parts.append("声音明亮有活力")
    elif e >= 55:
        parts.append("声音自然轻快")
    elif e <= 25:
        parts.append("声音低缓沉静")
    elif e <= 40:
        parts.append("声音平和舒缓")

    # Maturity
    m = char_vec["m"]
    if m <= 20:
        parts.append("像个孩子一样")
    elif m >= 75:
        parts.append("带着阅历的沉稳")

    # Gravity
    g = char_vec["g"]
    if g >= 70:
        parts.append("庄重不苟言笑")
    elif g <= 15:
        parts.append("轻松随意")

    if not parts:
        parts.append("用自然的声音说话")

    instruction = "，".join(parts)

    # Keep within 100 char limit
    char_count = sum(2 if ord(c) > 127 else 1 for c in instruction)
    if char_count > 100:
        instruction = instruction[:45]

    return instruction


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
            "instruction": str,
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

    # 3. Generate instruction
    instruction = _generate_instruction(char_vec, species)

    label = VOICES[best_vid]["label"]

    return {
        "voice_id": best_vid,
        "instruction": instruction,
        "speed": 1.0,
        "pitch_rate": 0,
        "speech_rate": 0,
        "reason": (
            f"{species} → {best_vid}({label}) "
            f"dist={best_dist:.0f} "
            f"char=[w={char_vec['w']:.0f} e={char_vec['e']:.0f} m={char_vec['m']:.0f} g={char_vec['g']:.0f}]"
        ),
    }
