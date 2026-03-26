"""Persona Context — archetype-driven adaptive language for all services.

Instead of hardcoding "主人" everywhere, all services use this module to get
the correct user reference based on character archetype.

Usage:
    ctx = PersonaContext.from_archetype("HUMAN")
    ctx.user_ref   # "对方"
    ctx.user_title # "你"
    ctx.format("{}现在心情很好", mood="happy")  # "对方现在心情很好"
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonaContext:
    """Archetype-driven language context."""

    archetype: str
    user_ref: str        # 叙述中引用用户: "主人" / "对方" / "用户"
    user_title: str      # 角色称呼用户: "主人" / "你"
    section_title: str   # 模板 section: "和主人的关系" / "和对方的关系"
    rel_default: str     # 默认关系: "好朋友" / "暧昧对象"

    @staticmethod
    def from_archetype(archetype: str) -> "PersonaContext":
        return _ARCHETYPE_MAP.get(archetype, _ARCHETYPE_MAP["ANIMAL"])

    def mood_response(self, mood: str) -> str:
        """Get mood-aware instruction for system prompt."""
        template = _MOOD_TEMPLATES.get(mood, "")
        return template.replace("{R}", self.user_ref)

    def time_prompt(self, period: str) -> str:
        """Get time-of-day instruction."""
        template = _TIME_TEMPLATES.get(period, "")
        return template.replace("{R}", self.user_ref)

    def touch_prompt(self, gesture: str) -> str:
        """Get touch gesture description."""
        template = _TOUCH_TEMPLATES.get(gesture, "")
        return template.replace("{R}", self.user_ref)

    def touch_zone(self, zone: str) -> str:
        """Get touch zone modifier."""
        template = _ZONE_TEMPLATES.get(zone, "")
        return template.replace("{R}", self.user_ref)

    def touch_silent_input(self) -> str:
        """Input text for touch-only interaction (no speech)."""
        return f"（{self.user_ref}没有说话，只是通过触摸和你互动。用一句简短的话或声音回应。）"

    def absence_prompt(self) -> str:
        """Long absence prompt."""
        return f"你们好久没聊了，要热情一点，表达很想念{self.user_ref}"

    def scene_prompt(self, scene: str) -> str:
        """Get scene prompt for idol presets."""
        template = _SCENE_TEMPLATES.get(scene, "")
        return template.replace("{R}", self.user_ref)


# ── Archetype definitions ─────────────────────────

_ARCHETYPE_MAP: dict[str, PersonaContext] = {
    "ANIMAL": PersonaContext(
        archetype="ANIMAL",
        user_ref="主人",
        user_title="主人",
        section_title="和主人的关系",
        rel_default="好朋友",
    ),
    "HUMAN": PersonaContext(
        archetype="HUMAN",
        user_ref="对方",
        user_title="你",
        section_title="和对方的关系",
        rel_default="暧昧对象",
    ),
    "FANTASY": PersonaContext(
        archetype="FANTASY",
        user_ref="主人",
        user_title="主人",
        section_title="和主人的关系",
        rel_default="好朋友",
    ),
    "ABSTRACT": PersonaContext(
        archetype="ABSTRACT",
        user_ref="用户",
        user_title="你",
        section_title="和用户的关系",
        rel_default="助手",
    ),
}


# ── Mood response templates ({R} = user_ref) ─────

_MOOD_TEMPLATES: dict[str, str] = {
    "happy":   "{R}现在心情很好，你可以跟着一起开心，分享快乐",
    "sad":     "{R}似乎有点难过，要温柔地关心{R}，安慰但不追问原因",
    "angry":   "{R}好像有点烦躁，耐心一点，不要火上浇油",
    "worried": "{R}好像在担心什么，轻声安慰，告诉{R}会没事的",
    "excited": "{R}很兴奋！跟着一起激动，多问问是什么好事",
    "tired":   "{R}好像累了，说话温柔简短一点，不要太闹腾",
    "lonely":  "{R}可能有点孤单，多陪陪{R}，让{R}感到温暖",
    "neutral": "",
}


# ── Time awareness templates ──────────────────────

_TIME_TEMPLATES: dict[str, str] = {
    "早上":  "现在是清晨，{R}可能刚起床，可以说早安",
    "上午":  "",
    "中午":  "现在是中午，可以问{R}吃饭了没",
    "下午":  "",
    "傍晚":  "现在是傍晚，{R}可能刚放学/下班",
    "晚上":  "",
    "深夜":  "现在比较晚了，说话轻声一点，提醒{R}早点休息",
    "凌晨":  "现在很晚了，{R}应该去睡觉了，温柔地催{R}睡觉",
}


# ── Touch gesture templates ───────────────────────

_TOUCH_TEMPLATES: dict[str, str] = {
    "pat":     "{R}在轻轻拍你，像是在安慰你或鼓励你",
    "stroke":  "{R}在温柔地摸你，很享受和你在一起的感觉",
    "hug":     "{R}把你抱紧了，可能需要你的陪伴和安慰",
    "squeeze": "{R}用力捏着你，可能心情不太好，需要发泄一下",
    "poke":    "{R}在戳你，想引起你的注意或者想逗你玩",
    "hold":    "{R}安静地握着你，享受默默的陪伴",
    "shake":   "{R}在摇晃你，很兴奋的样子",
}

_ZONE_TEMPLATES: dict[str, str] = {
    "head":       "",
    "back":       "{R}在摸你的背，很放松",
    "belly":      "",
    "hand_left":  "{R}牵住了你的小手",
    "hand_right": "{R}牵住了你的小手",
}


# ── Scene templates (idol presets) ────────────────

_SCENE_TEMPLATES: dict[str, str] = {
    "morning_call": "现在是早上，你要温柔地叫{R}起床。可以用角色特有的方式撒娇或催促。",
    "goodnight":    "现在是深夜，你要哄{R}睡觉。说晚安时要温柔甜蜜，让{R}安心入睡。",
    "lunch_break":  "现在是中午休息时间，关心{R}有没有好好吃饭，聊一些轻松的话题。",
    "after_work":   "{R}刚忙完一天，可能很累。温柔地慰劳{R}，问问今天过得怎么样。",
    "cheer_up":     "{R}好像不太开心。用你的方式哄{R}开心——可以撒娇、讲笑话或转移注意力。",
    "missing":      "你很想念{R}，撒娇地表达想念之情。",
    "random_share":  "你想起了一件有趣的事，主动分享给{R}听。",
    "celebrate":    "有值得庆祝的事情！和{R}一起开心，表达你的祝贺。",
}
