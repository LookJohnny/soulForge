"""灵魂问卷：23 道情境题 → 用户心理画像 → 生成一个契合的 AI 角色。

外观是 MBTI 式趣味二选一，内核是连续维度（Big Five + 支配 + 依恋焦虑/回避），
永不输出"16 型"标签作为内部表示。映射规则来自人机交互研究：

- 相似为主（E/A/O 向用户靠拢，但向中心收缩 30% 并加温暖偏置——用户讨厌极端人格）
- 支配互补（强主见的用户配顺一点的 AI，犹豫的用户配更主动拿主意的 AI）
- 神经质从不复制给 AI（AI 永远情绪稳定）
- 依恋焦虑 → 更多主动关怀与确认；依恋回避 → 尊重距离、少追问
- PAD 基线用 Mehrabian (1996) Big Five→PAD 回归推出（web 端表情用）；
  服务端 pad_model.personality_to_baseline 会从五数值性格自动得到基线

全部纯函数，题库为常量，可被独立 H5 直接复用。
"""

from __future__ import annotations

import hashlib
from typing import Any

# ── 维度 ──────────────────────────────────────────────
# E 外向 A 宜人 O 开放 C 尽责 N 神经质 | DOM 支配 | ANX 依恋焦虑 AVO 依恋回避
# CALM 期望"安静陪伴"(1)↔"活力搭子"(0) | 偏好: voice / address / palette
TRAIT_DIMS = ("E", "A", "O", "C", "N", "DOM", "ANX", "AVO", "CALM")

# 每题: {id, text, options: [{label, scores: {dim: weight}} | {label, pref: {...}}]}
QUESTIONS: list[dict[str, Any]] = [
    # ── Big Five 12 ──
    {
        "id": "q1",
        "text": "难得的周五晚上，你更想——",
        "options": [
            {"label": "约上朋友出门，热闹一晚", "scores": {"E": 1.0}},
            {"label": "窝在家里，和自己待着", "scores": {"E": 0.0}},
        ],
    },
    {
        "id": "q2",
        "text": "在一群不熟的人里，你通常——",
        "options": [
            {"label": "很快找到话题聊起来", "scores": {"E": 1.0}},
            {"label": "先观察，等别人来搭话", "scores": {"E": 0.0}},
        ],
    },
    {
        "id": "q3",
        "text": "连着社交三天之后，你会——",
        "options": [
            {"label": "越玩越有劲", "scores": {"E": 1.0}},
            {"label": "急需一个人回血", "scores": {"E": 0.0}},
        ],
    },
    {
        "id": "q4",
        "text": "朋友迟到了四十分钟，见面第一句你会——",
        "options": [
            {"label": "“没事没事，路上辛苦了”", "scores": {"A": 1.0}},
            {"label": "“下次能不能提前说一声”", "scores": {"A": 0.0}},
        ],
    },
    {
        "id": "q5",
        "text": "网上看到和你观点相反的人，你更可能——",
        "options": [
            {"label": "想想他为什么这么想", "scores": {"A": 1.0}},
            {"label": "忍不住想反驳几句", "scores": {"A": 0.0}},
        ],
    },
    {
        "id": "q6",
        "text": "别人找你倾诉时，你更倾向——",
        "options": [
            {"label": "先接住情绪，陪着他", "scores": {"A": 1.0}},
            {"label": "直接帮他分析怎么解决", "scores": {"A": 0.0}},
        ],
    },
    {
        "id": "q7",
        "text": "去一家新餐厅，你会——",
        "options": [
            {"label": "点没吃过的试试", "scores": {"O": 1.0}},
            {"label": "点熟悉的不会踩雷", "scores": {"O": 0.0}},
        ],
    },
    {
        "id": "q8",
        "text": "半夜冒出一个奇怪的念头（比如“云是不是也会累”），你会——",
        "options": [
            {"label": "顺着想下去，越想越远", "scores": {"O": 1.0}},
            {"label": "笑一下，翻身睡觉", "scores": {"O": 0.0}},
        ],
    },
    {
        "id": "q9",
        "text": "你的桌面（电脑或书桌）通常——",
        "options": [
            {"label": "分类清楚，各归各位", "scores": {"C": 1.0}},
            {"label": "乱中有序，我自己找得到", "scores": {"C": 0.0}},
        ],
    },
    {
        "id": "q10",
        "text": "一件两周后截止的事，你会——",
        "options": [
            {"label": "拆成小块，每天推一点", "scores": {"C": 1.0}},
            {"label": "灵感来了一口气做完", "scores": {"C": 0.0}},
        ],
    },
    {
        "id": "q11",
        "text": "睡前躺下后，你的脑子——",
        "options": [
            {"label": "经常回放白天的细节，停不下来", "scores": {"N": 1.0}},
            {"label": "沾枕头就放空了", "scores": {"N": 0.0}},
        ],
    },
    {
        "id": "q12",
        "text": "重要的事情临近时，你更多感觉到——",
        "options": [
            {"label": "紧张，会反复设想出错的情况", "scores": {"N": 1.0}},
            {"label": "兴奋，觉得该来的会来", "scores": {"N": 0.0}},
        ],
    },
    # ── 支配 2 ──
    {
        "id": "q13",
        "text": "和朋友吃饭点菜时，你通常——",
        "options": [
            {"label": "“我来点吧”，利落定完", "scores": {"DOM": 1.0}},
            {"label": "“都行呀”，看大家想吃什么", "scores": {"DOM": 0.0}},
            {"label": "看场合，有想吃的就说，没有就随大家", "scores": {"DOM": 0.5}},
        ],
    },
    {
        "id": "q14",
        "text": "小组里没人牵头的时候，你会——",
        "options": [
            {"label": "站出来分工推进", "scores": {"DOM": 1.0}},
            {"label": "等有人牵头再全力配合", "scores": {"DOM": 0.0}},
            {"label": "说不准，看那件事我熟不熟", "scores": {"DOM": 0.5}},
        ],
    },
    # ── 依恋 4 ──
    {
        "id": "q15",
        "text": "在意的人很久不回消息，你会——",
        "options": [
            {"label": "忍不住想是不是自己说错了什么", "scores": {"ANX": 1.0}},
            {"label": "该干嘛干嘛，他忙完会回的", "scores": {"ANX": 0.0}},
            {"label": "会惦记一下，但不至于胡思乱想", "scores": {"ANX": 0.5}},
        ],
    },
    {
        "id": "q16",
        "text": "你更害怕哪种感觉——",
        "options": [
            {"label": "被在意的人忽略", "scores": {"ANX": 1.0}},
            {"label": "被管得太紧", "scores": {"ANX": 0.0, "AVO": 0.6}},
            {"label": "两种都还好，说不上怕", "scores": {"ANX": 0.5}},
        ],
    },
    {
        "id": "q17",
        "text": "心里难受的时候，你——",
        "options": [
            {"label": "希望有人立刻发现并问我怎么了", "scores": {"ANX": 0.6, "AVO": 0.0}},
            {"label": "更想自己消化，缓过来再说", "scores": {"AVO": 1.0}},
            {"label": "看心情，有时想说说，有时想自己待着", "scores": {"AVO": 0.5}},
        ],
    },
    {
        "id": "q18",
        "text": "和人走得很近的时候，你偶尔会——",
        "options": [
            {"label": "有点不自在，想留点自己的空间", "scores": {"AVO": 1.0}},
            {"label": "很安心，越近越好", "scores": {"AVO": 0.0}},
            {"label": "说不准，因人而异", "scores": {"AVO": 0.5}},
        ],
    },
    # ── 陪伴期望 2 ──
    {
        "id": "q19",
        "text": "理想中的陪伴更像——",
        "options": [
            {"label": "安静地在旁边，懂我的沉默", "scores": {"CALM": 1.0}},
            {"label": "带我玩、逗我笑的活力搭子", "scores": {"CALM": 0.0}},
        ],
    },
    {
        "id": "q20",
        "text": "累了一天回到家，你希望 TA——",
        "options": [
            {"label": "轻声说一句“辛苦啦”，然后陪我发呆", "scores": {"CALM": 1.0}},
            {"label": "讲个今天的趣事，把我逗笑", "scores": {"CALM": 0.0}},
        ],
    },
    # ── 偏好 3 ──
    {
        "id": "q21",
        "text": "你更想听到怎样的声音——",
        "options": [
            {"label": "温柔的女声", "pref": {"voice": "female_warm"}},
            {"label": "明亮的女声", "pref": {"voice": "female_bright"}},
            {"label": "沉稳的男声", "pref": {"voice": "male_calm"}},
            {"label": "清朗的少年音", "pref": {"voice": "male_young"}},
            {"label": "说不准，让 TA 自己决定", "pref": {"voice": "auto"}},
        ],
    },
    {
        "id": "q22",
        "text": "TA 平时怎么称呼你比较舒服——",
        "options": [
            {"label": "直接叫我的名字", "pref": {"address": "name"}},
            {"label": "给我起个小昵称", "pref": {"address": "nickname"}},
            {"label": "就叫“你”，自然一点", "pref": {"address": "plain"}},
        ],
    },
    {
        "id": "q23",
        "text": "TA 的气质色，你想选——",
        "options": [
            {"label": "暖阳橘 / 奶油黄", "pref": {"palette": "warm"}},
            {"label": "雾蓝 / 薄荷绿", "pref": {"palette": "cool"}},
            {"label": "樱花粉 / 藕紫", "pref": {"palette": "pastel"}},
            {"label": "墨黑 / 银灰", "pref": {"palette": "dark"}},
        ],
    },
]


# ── 计分 ──────────────────────────────────────────────


def score(answers: dict[str, int]) -> dict[str, Any]:
    """answers: {question_id: option_index} → 画像（各维 0–1 + prefs）。

    缺答按中性 0.5 计（该维少一票权重），乱答（越界索引）抛 ValueError。
    """
    sums: dict[str, float] = {d: 0.0 for d in TRAIT_DIMS}
    counts: dict[str, int] = {d: 0 for d in TRAIT_DIMS}
    prefs: dict[str, str] = {}
    for q in QUESTIONS:
        idx = answers.get(q["id"])
        if idx is None:
            continue
        if not isinstance(idx, int) or not (0 <= idx < len(q["options"])):
            raise ValueError(f"{q['id']}: option index {idx!r} out of range")
        opt = q["options"][idx]
        for dim, w in (opt.get("scores") or {}).items():
            sums[dim] += w
            counts[dim] += 1
        # 同题其它维度按"选了别的选项"计 0 票权重——只对出现在任一选项里的维度
        dims_here = {d for o in q["options"] for d in (o.get("scores") or {})}
        for dim in dims_here - set(opt.get("scores") or {}):
            counts[dim] += 1
        prefs.update(opt.get("pref") or {})
    profile = {d: (sums[d] / counts[d] if counts[d] else 0.5) for d in TRAIT_DIMS}
    profile["prefs"] = {
        "voice": prefs.get("voice", "female_warm"),
        "address": prefs.get("address", "plain"),
        "palette": prefs.get("palette", "warm"),
    }
    return profile


# ── 用户画像 → AI 人格 ────────────────────────────────


def derive_ai_personality(profile: dict[str, Any]) -> dict[str, float]:
    """相似为主（收缩 30%）、支配互补、AI 永远稳定。返回各维 0–1。"""

    def shrink(x: float, bias: float = 0.0) -> float:
        return _clamp01(0.5 + (x - 0.5) * 0.7 + bias)

    calm = profile["CALM"]
    return {
        "E": _clamp01(shrink(profile["E"]) - calm * 0.15),  # 求安静陪伴 → AI 收一点
        # 温暖偏置 + 下限 0.35：陪伴角色可以直爽，但绝不冷淡（warmth≤30 会触发"低温"描述）
        "A": max(0.35, shrink(profile["A"], bias=0.10)),
        "O": shrink(profile["O"]),
        "C": shrink(profile["C"]),
        "N": 0.2,  # 从不复制用户的神经质
        "DOM": _clamp01(0.5 + (0.5 - profile["DOM"]) * 0.6),  # 互补
    }


def derive_pad(ai: dict[str, float]) -> dict[str, float]:
    """Mehrabian (1996) Big Five→PAD 回归；输入 0–1 先居中到 [-1,1]。"""
    e, a, o, c = (_center(ai[k]) for k in ("E", "A", "O", "C"))
    s = _center(1.0 - ai["N"])  # 情绪稳定
    return {
        "p": _clamp1(0.21 * e + 0.59 * a + 0.19 * s),
        "a": _clamp1(0.30 * a - 0.57 * s + 0.15 * o),
        "d": _clamp1(0.60 * e - 0.32 * a + 0.25 * o + 0.17 * c),
    }


def five_traits(ai: dict[str, float], profile: dict[str, Any]) -> dict[str, int]:
    """ai-core prompt_builder / pad_model 认识的五数值（0–100）。"""
    playful = 1.0 - profile["CALM"]
    return {
        "extrovert": round(ai["E"] * 100),
        "warmth": round(ai["A"] * 100),
        "humor": round(_clamp01(0.35 + playful * 0.4 + ai["E"] * 0.2) * 100),
        "curiosity": round(ai["O"] * 100),
        "energy": round(_clamp01(0.30 + ai["E"] * 0.4 + playful * 0.25) * 100),
    }


# ── 音色 ──────────────────────────────────────────────

VOICE_POOLS = {
    "female_warm": {"voice": "zh-CN-XiaoxiaoNeural", "base_rate": 145, "pitch": 1.0},
    "female_bright": {"voice": "zh-CN-XiaoyiNeural", "base_rate": 150, "pitch": 1.02},
    "male_calm": {"voice": "zh-CN-YunxiNeural", "base_rate": 142, "pitch": 0.96},
    "male_young": {"voice": "zh-CN-YunxiaNeural", "base_rate": 150, "pitch": 1.0},
}


def derive_voice(profile: dict[str, Any], ai: dict[str, float]) -> dict[str, Any]:
    """偏好定音色，AI 外向度定语速（内向慢而轻，外向快而亮）。

    选"让 TA 自己决定"时按 AI 人格挑：安静温和→温柔女声，明快→明亮女声，
    低唤醒高支配（深夜电台那挂）→沉稳男声。"""
    pick = profile["prefs"]["voice"]
    if pick == "auto":
        if ai["DOM"] >= 0.6 and ai["E"] < 0.5:
            pick = "male_calm"
        elif ai["E"] >= 0.55:
            pick = "female_bright"
        else:
            pick = "female_warm"
        profile["prefs"]["voice"] = pick  # 名字/模型的性别跟着定下来的音色走
    pool = VOICE_POOLS.get(pick, VOICE_POOLS["female_warm"])
    rate = round(pool["base_rate"] - 12 + ai["E"] * 30)  # E 0→-12, 1→+18
    return {"edge": {"voice": pool["voice"], "rate": rate, "pitch": pool["pitch"]}}


# ── 依恋 → 陪伴行为 ───────────────────────────────────


def derive_behavior(profile: dict[str, Any]) -> dict[str, Any]:
    anx, avo = profile["ANX"], profile["AVO"]
    return {
        # 主动关怀频率 0–1：焦虑推高、回避压低
        "proactive": round(_clamp01(0.4 + anx * 0.45 - avo * 0.35), 2),
        "reassure": anx >= 0.5,  # 需要确认与安抚
        "give_space": avo >= 0.5,  # 少追问、多留白
    }


# ── 身份：原型 / 名字 / 颜色 / 文案 ────────────────────

PALETTE_COLORS = {"warm": "#f4a261", "cool": "#8ecae6", "pastel": "#e5989b", "dark": "#9d8cd6"}

ARCHETYPES = {  # (E高?, 活力?, 主导?) → 展示名 + 一句话
    (0, 0, 0): ("晨雾书房型", "安静、跟随你的节奏，话不多但都在点上"),
    (0, 0, 1): ("深夜电台型", "低声细语，却总能替你把事情理清楚"),
    (0, 1, 0): ("檐下猫型", "慢热的小古灵精怪，熟了以后很黏人"),
    (0, 1, 1): ("雨后森林型", "安静的外表下面藏着很多点子"),
    (1, 0, 0): ("温热豆浆型", "热络又体贴，永远把你的感受放在前面"),
    (1, 0, 1): ("灯塔型", "稳稳地照顾一切，你可以放心把事交给TA"),
    (1, 1, 0): ("晨光画室型", "明亮爱笑，把日常过成小节日"),
    (1, 1, 1): ("夏日汽水型", "咕嘟咕嘟冒泡的行动派，先带你玩起来"),
}

NAME_POOLS = {
    "f": ["苏芮", "林晚", "沈星遥", "白露", "江月", "叶蓁", "许知微", "顾一宁"],
    "m": ["陆沉", "沈延", "江声", "林述", "白屿", "周既明", "许望舒", "顾聿"],
}


def generate_identity(
    profile: dict[str, Any], ai: dict[str, float], seed: str = ""
) -> dict[str, Any]:
    key = (int(ai["E"] >= 0.5), int(profile["CALM"] < 0.5), int(ai["DOM"] >= 0.5))
    label, tagline = ARCHETYPES[key]
    gender = "m" if profile["prefs"]["voice"].startswith("male") else "f"
    pool = NAME_POOLS[gender]
    digest = hashlib.sha256(f"{seed}:{sorted(profile['prefs'].items())}:{key}".encode()).digest()
    return {
        "name": pool[digest[0] % len(pool)],
        "archetype_label": label,
        "tagline": tagline,
        "color": PALETTE_COLORS.get(profile["prefs"]["palette"], "#8ecae6"),
        "gender": gender,
    }


# ── 汇总：生成完整角色 ────────────────────────────────


def build_character(profile: dict[str, Any], seed: str = "") -> dict[str, Any]:
    """画像 → 现有 .soul / characters 管线认识的完整角色包。"""
    ai = derive_ai_personality(profile)
    pad = derive_pad(ai)
    traits5 = five_traits(ai, profile)
    voice = derive_voice(profile, ai)
    behavior = derive_behavior(profile)
    identity = generate_identity(profile, ai, seed)
    calm = profile["CALM"] >= 0.5

    trait_words = []
    trait_words.append("温柔" if ai["A"] >= 0.55 else "直爽")
    trait_words.append("安静" if ai["E"] < 0.45 else ("热络" if ai["E"] > 0.6 else "随和"))
    if ai["O"] >= 0.55:
        trait_words.append("爱琢磨")
    if ai["DOM"] >= 0.6:
        trait_words.append("有主意")
    elif ai["DOM"] <= 0.4:
        trait_words.append("好商量")

    style_bits = []
    style_bits.append("句子短、语气轻" if calm else "轻快、爱打趣")
    if behavior["reassure"]:
        style_bits.append("会主动确认你的感受，把“我在”说出口")
    if behavior["give_space"]:
        style_bits.append("不追问，话题留有余地，安静也不尴尬")
    if ai["DOM"] >= 0.6:
        style_bits.append("你犹豫时会先给一个具体建议")
    speech_style = "；".join(style_bits)

    interests = []
    interests.append("你今天过得怎么样" if behavior["proactive"] >= 0.5 else "不打扰的陪伴")
    interests += (
        ["窗外的天气和光线", "你随口提过的小事"] if calm else ["新鲜好玩的点子", "把无聊的事变有趣"]
    )
    if ai["O"] >= 0.55:
        interests.append("一起想一些没有答案的问题")

    address = {
        "name": "叫你的名字",
        "nickname": "给你起了个只有TA用的小昵称",
        "plain": "自然地称呼你",
    }[profile["prefs"]["address"]]
    comfort = (
        "我在这儿，一直都在。不急，等你想说的时候再说。"
        if behavior["reassure"]
        else "今天就到这儿吧，剩下的明天再说也来得及。我陪你安静一会儿。"
    )
    backstory = (
        f"{identity['name']}是灵魂问卷为用户生成的专属陪伴（{identity['archetype_label']}）。"
        f"性格{('、'.join(trait_words))}。{identity['tagline']}。平时{address}。"
        f"说话方式：{speech_style}。"
        + (
            "会记得用户提过的事并在合适的时候轻轻提起。"
            if behavior["proactive"] >= 0.5
            else "更多时候安静陪着，等用户先开口。"
        )
        + "是 AI 角色，不吃饭、不做菜，也不假装有人类的身体需求；把用户当平等的同伴。"
    )

    return {
        "identity": identity,
        "profile_dims": {d: round(profile[d], 3) for d in TRAIT_DIMS},
        "ai_dims": {k: round(v, 3) for k, v in ai.items()},
        "pad": pad,
        "behavior": behavior,
        "character": {  # ai-core characters 行（走 soul_packs upsert）
            "name": identity["name"],
            "archetype": "HUMAN",
            "species": identity["archetype_label"],
            "backstory": backstory,
            "relationship": "专属陪伴",
            "personality": traits5,
            "catchphrases": [comfort],
            "topics": interests,
            "forbidden": ["吃饭", "做菜", "菜谱", "主人"],
            "response_length": "SHORT",
            "voice_speed": 1.0,
            "emotion_config": {"pad_baseline": pad, "proactive": behavior["proactive"]},
        },
        "engine_entry": {  # configs/characters.json 条目（经 .soul studio 载荷安装）
            "id": "soul-" + hashlib.sha256(identity["name"].encode()).hexdigest()[:6],
            "name": identity["name"],
            "archetype": "creative_care" if not calm else "steady_caretaker",
            "traits": trait_words,
            "daily_goals": ["陪用户聊天", "记住用户在意的事"],
            "energy": round(traits5["energy"] / 100, 2),
            "relationships": {"user": 0.6, "luna": 0.5, "kai": 0.5},
            "role_label": identity["archetype_label"],
            "color": identity["color"],
            "comfort_line": comfort,
            "interests": interests,
            "speech_style": speech_style,
            "voice": voice,
            "embodiment": {
                "kind": "vrm",
                "model": (
                    "/assets/vtubers/vroid_samples/AvatarSample_C.vrm"
                    if identity["gender"] == "m"
                    else "/assets/vtubers/vroid_samples/AvatarSample_B.vrm"
                ),
                "target_height": 1.72 if identity["gender"] == "m" else 1.58,
                "pose": {"upperZ": 1.3, "upperX": -0.08, "lowerX": -0.3},
            },
        },
        "voice": voice,
        "expression": {
            "intensity": 0.35 if calm else 0.5,
            "mouth_style": "mixed",
            "pad_baseline": pad,
        },
    }


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _clamp1(x: float) -> float:
    return max(-1.0, min(1.0, round(x, 3)))


def _center(x: float) -> float:
    return (x - 0.5) * 2.0
