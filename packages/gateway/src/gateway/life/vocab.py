"""Ambient utterance vocabulary for the life loop.

All entries are plain vocalizable text (no stage directions in
parentheses) because they go straight to TTS in the character's own
voice. They are archetype-neutral on purpose — character-specific
musings come from the LLM idle path, these are the cheap in-between
sounds (hums, yawns, snores) any plush character can make.
"""

import random

# Soft sounds while bored — short hums, sighs, tiny self-talk
BORED: list[str] = [
    "嗯……",
    "啦啦啦~ 啦~",
    "哼哼~ 哼哼哼~",
    "唔…… 好安静呀。",
    "呼……",
    "诶嘿嘿。",
    "嗯哼~ 嗯哼~",
]

# Drowsy sounds — yawns and sleepy mumbles
SLEEPY: list[str] = [
    "哈啊…… 好困……",
    "唔…… 眼睛睁不开了……",
    "哈啊……",
    "呼…… 嗯……",
]

# Soft snoring while asleep
ASLEEP: list[str] = [
    "呼…… 呼……",
    "唔嗯……",
    "呼…… 呼…… 呼……",
]

AMBIENT: dict[str, list[str]] = {
    "bored": BORED,
    "sleepy": SLEEPY,
    "asleep": ASLEEP,
}

# Instant reactions while the pipeline thinks — masks first-word latency
THINKING_FILLERS: list[str] = [
    "嗯？",
    "唔——",
    "嗯…… 我想想哦。",
    "诶嘿~",
    "嗯嗯。",
]


def pick_ambient(state: str, rng: random.Random | None = None) -> str:
    """Pick a random ambient utterance for a life state."""
    pool = AMBIENT.get(state) or BORED
    return (rng or random).choice(pool)
