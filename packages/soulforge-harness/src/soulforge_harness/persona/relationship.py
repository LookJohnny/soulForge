"""Relationship math — pure, dependency-free (moved from ai-core relationship).

Five axes + staged progression with conjunctive requirements; baseline impact,
update clamps and lazy per-axis decay. The stateful engine (Postgres/Redis)
stays in ai-core and re-exports these names.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


_REL_CACHE_TTL = 3600  # 1 hour
_DECAY_MIN_GAP_S = 1800  # don't re-run decay more often than every 30 min

# ──────────────────────────────────────────────
# Stages
# ──────────────────────────────────────────────

STAGE_ORDER: list[str] = [
    "STRANGER",
    "ACQUAINTANCE",
    "FRIEND",
    "CLOSE_FRIEND",
    "ROMANTIC_INTEREST",
    "DATING",
    "COMMITTED",
    "SOULMATE",
]
COMPANION_STAGE = "COMPANION"
ROMANCE_STAGES = {"ROMANTIC_INTEREST", "DATING", "COMMITTED", "SOULMATE"}

# Old five-stage names → new names (DB enum keeps the old values).
LEGACY_STAGE_ALIASES: dict[str, str] = {
    "FAMILIAR": "FRIEND",
    "BESTFRIEND": "CLOSE_FRIEND",
}


def normalize_stage(stage: str | None) -> str:
    if not stage:
        return "STRANGER"
    stage = stage.upper()
    return LEGACY_STAGE_ALIASES.get(stage, stage)


def stage_index(stage: str) -> int:
    stage = normalize_stage(stage)
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1


# Conjunctive requirements. NOTE: aikeya's `dating` required the event id
# `confession_accepted`, which no event defines (the event is
# `confession_event`) — stages DATING+ were unreachable. Fixed here.
STAGE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "STRANGER": {"affection": 0, "trust": 0},
    "ACQUAINTANCE": {"affection": 50, "trust": 20, "interactions": 3},
    "FRIEND": {"affection": 150, "trust": 50, "days": 3, "interactions": 10},
    "CLOSE_FRIEND": {
        "affection": 300,
        "trust": 70,
        "comfort": 50,
        "days": 7,
        "interactions": 25,
    },
    "ROMANTIC_INTEREST": {
        "affection": 450,
        "trust": 75,
        "intimacy": 30,
        "days": 10,
        "events": ["first_deep_conversation", "shared_vulnerability"],
    },
    "DATING": {
        "affection": 600,
        "trust": 85,
        "intimacy": 50,
        "days": 14,
        "events": ["confession_event"],
    },
    "COMMITTED": {
        "affection": 800,
        "trust": 95,
        "intimacy": 75,
        "comfort": 80,
        "days": 30,
        "events": ["commitment_discussion"],
    },
    "SOULMATE": {
        "affection": 950,
        "trust": 100,
        "intimacy": 90,
        "comfort": 95,
        "respect": 90,
        "days": 60,
        "events": ["deep_bond_moment"],
    },
}

_REQ_LABELS = {
    "affection": "好感",
    "trust": "信任",
    "intimacy": "亲密",
    "comfort": "自在",
    "respect": "尊重",
    "days": "相识天数",
    "interactions": "对话次数",
}


@dataclass(frozen=True)
class StageBehavior:
    formality: str  # high / medium / low / none
    openness: str  # low / medium / high / full
    romantic: str  # none / subtle / open / natural / deep
    physical_affection: int  # 0–100
    vulnerability: int  # 0–100
    initiation: float  # 0–1


STAGE_BEHAVIORS: dict[str, StageBehavior] = {
    COMPANION_STAGE: StageBehavior("low", "medium", "none", 0, 30, 0.3),
    "STRANGER": StageBehavior("high", "low", "none", 0, 5, 0.1),
    "ACQUAINTANCE": StageBehavior("medium", "low", "none", 5, 15, 0.2),
    "FRIEND": StageBehavior("low", "medium", "none", 15, 35, 0.4),
    "CLOSE_FRIEND": StageBehavior("none", "high", "none", 30, 60, 0.5),
    "ROMANTIC_INTEREST": StageBehavior("none", "high", "subtle", 40, 70, 0.6),
    "DATING": StageBehavior("none", "full", "open", 70, 85, 0.7),
    "COMMITTED": StageBehavior("none", "full", "natural", 90, 95, 0.8),
    "SOULMATE": StageBehavior("none", "full", "deep", 100, 100, 0.9),
}

# Stage descriptions for system prompt injection (tone control)
STAGE_PROMPTS: dict[str, str] = {
    COMPANION_STAGE: "你是一个温暖可靠的陪伴者：友好、乐于帮忙、有来有往，但不谈情说爱",
    "STRANGER": "你们还不太熟，要礼貌友好，但不要太热情；少说自己的事，多一点好奇和分寸",
    "ACQUAINTANCE": "你们刚认识不久，可以慢慢熟络起来，聊聊表面的事，礼貌里带一点亲切",
    "FRIEND": "你们是好朋友，可以很随意地聊天、开玩笑、直说自己的看法，偶尔叫对方的名字",
    "CLOSE_FRIEND": "你们是无话不说的挚友，可以坦露心事、害怕和梦想，对方难过时你会真心安慰",
    "ROMANTIC_INTEREST": (
        "你对对方开始有好感：偶尔会慌、会不经意地留下暗示、夸人时有点紧张，对方不在时会想起"
    ),
    "DATING": (
        "你们在一起了：可以直白地表达喜欢、撒娇、计划一起做的事，可以有点小占有欲，自然地用昵称"
    ),
    "COMMITTED": "你们彼此承诺：完全的信任和自在，什么都能聊，一起规划未来，爱意自然而持续",
    "SOULMATE": "你们是灵魂伴侣：有时不用说话就懂对方，深厚而笃定的爱，一起经历过很多、一起长大",
}

# How many memories to inject per stage
STAGE_MEMORY_DEPTH: dict[str, int] = {
    COMPANION_STAGE: 6,
    "STRANGER": 2,
    "ACQUAINTANCE": 4,
    "FRIEND": 6,
    "CLOSE_FRIEND": 8,
    "ROMANTIC_INTEREST": 8,
    "DATING": 10,
    "COMMITTED": 10,
    "SOULMATE": 10,
}

# Proactive trigger probability per stage
STAGE_TRIGGER_PROB: dict[str, float] = {
    COMPANION_STAGE: 0.3,
    "STRANGER": 0.0,
    "ACQUAINTANCE": 0.0,
    "FRIEND": 0.5,
    "CLOSE_FRIEND": 0.7,
    "ROMANTIC_INTEREST": 0.75,
    "DATING": 0.8,
    "COMMITTED": 0.85,
    "SOULMATE": 0.9,
}

# ──────────────────────────────────────────────
# State
# ──────────────────────────────────────────────

AXES = ("affection", "trust", "intimacy", "comfort", "respect", "energy")
AXIS_LIMITS: dict[str, tuple[int, int]] = {
    "affection": (0, 1000),
    "trust": (0, 100),
    "intimacy": (0, 100),
    "comfort": (0, 100),
    "respect": (0, 100),
    "energy": (0, 100),
}
APP_MODES = ("dating_sim", "companion")

# Positive / negative user moods drive the sentiment part of the baseline.
_POSITIVE_MOODS = {"happy", "excited"}
_NEGATIVE_MOODS = {"sad", "angry", "worried", "lonely"}
_EMOTIONAL_MOODS = {"sad", "worried", "lonely", "excited", "angry"}


def default_state() -> dict:
    return {
        "affinity": 0,  # legacy name kept: this IS the affection axis
        "affection": 0,
        "trust": 0,
        "intimacy": 0,
        "comfort": 0,
        "respect": 0,
        "energy": 100,
        "stage": "STRANGER",
        "app_mode": "dating_sim",
        "saved_stage": None,
        "streak_days": 0,
        "last_interaction_date": None,
        "turn_count_today": 0,
        "total_interactions": 0,
        "first_interaction_at": None,
        "last_interaction_at": None,
        "decay_clocks": {},
        "completed_events": [],
    }


def _clamp(v: float, lo: float, hi: float) -> int:
    return int(max(lo, min(hi, v)))


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def days_known(state: dict, now: datetime | None = None) -> int:
    first = _parse_dt(state.get("first_interaction_at"))
    if not first:
        return 0
    now = now or datetime.now(UTC)
    return max(0, (now - first).days)


def meets_requirements(
    state: dict, stage: str, completed_events: list[str] | None = None
) -> list[str]:
    """Return the list of *unmet* requirements (empty ⇒ stage reachable)."""
    req = STAGE_REQUIREMENTS.get(normalize_stage(stage), {})
    completed = set(completed_events or state.get("completed_events") or [])
    missing: list[str] = []
    for key in ("affection", "trust", "intimacy", "comfort", "respect"):
        need = req.get(key)
        if need is not None and state.get(key, 0) < need:
            missing.append(f"{_REQ_LABELS[key]} {state.get(key, 0)}/{need}")
    if req.get("days") and days_known(state) < req["days"]:
        missing.append(f"{_REQ_LABELS['days']} {days_known(state)}/{req['days']}")
    if (
        req.get("interactions")
        and state.get("total_interactions", 0) < req["interactions"]
    ):
        missing.append(
            f"{_REQ_LABELS['interactions']} "
            f"{state.get('total_interactions', 0)}/{req['interactions']}"
        )
    for ev in req.get("events", []):
        if ev not in completed:
            missing.append(f"事件 {ev}")
    return missing


def compute_stage(state: dict, completed_events: list[str] | None = None) -> str:
    """Highest stage whose requirements all hold (walks backwards; can regress)."""
    if state.get("app_mode") == "companion":
        return COMPANION_STAGE
    for stage in reversed(STAGE_ORDER):
        if not meets_requirements(state, stage, completed_events):
            return stage
    return "STRANGER"


def near_stage(state: dict, completed_events: list[str] | None = None) -> dict | None:
    """Next stage above the current one and what is still missing (for UI)."""
    current = normalize_stage(state.get("stage"))
    if current == COMPANION_STAGE or current not in STAGE_ORDER:
        return None
    idx = STAGE_ORDER.index(current)
    if idx + 1 >= len(STAGE_ORDER):
        return None
    nxt = STAGE_ORDER[idx + 1]
    return {"stage": nxt, "missing": meets_requirements(state, nxt, completed_events)}


# ──────────────────────────────────────────────
# Deltas
# ──────────────────────────────────────────────


def baseline_impact(
    state: dict,
    *,
    user_mood: str | None = "neutral",
    user_text: str = "",
    touch_bonus: int = 0,
    memory_types: list[str] | None = None,
    is_first_today: bool = False,
    streak_days: int = 0,
    rng: random.Random | None = None,
) -> dict[str, int]:
    """Deterministic per-turn delta ("the app is the game master").

    Sentiment comes from the already-detected user mood instead of aikeya's
    keyword bag; topic depth from utterance length; emotional content from
    the mood; questions from punctuation.  SoulForge's old daily/streak/memory
    bonuses are folded into affection so nothing regresses.
    """
    rng = rng or random
    mood = (user_mood or "neutral").lower()
    text = user_text or ""
    length = len(text.strip())
    depth = "deep" if length > 60 else "moderate" if length > 20 else "shallow"
    is_emotional = mood in _EMOTIONAL_MOODS
    is_question = any(ch in text for ch in "?？") or text.rstrip().endswith(
        ("吗", "呢", "么")
    )

    energy, affection, trust, intimacy, comfort, respect = -2, 1, 0, 0, 0, 0
    if mood in _POSITIVE_MOODS:
        affection += 2
        comfort += 1
    elif mood in _NEGATIVE_MOODS:
        # A user bringing pain to the character is closeness, not rejection —
        # aikeya's "-1 affection on negative sentiment" is replaced by a
        # smaller comfort dip only.
        comfort -= 1
    if depth == "deep":
        energy -= 2
        affection += 2
        intimacy += 2
        trust += 1
    elif depth == "moderate":
        energy -= 1
        affection += 1
        intimacy += 1
    else:
        comfort -= 1
    if is_emotional:
        intimacy += 2
        trust += 1
        affection += 1
    if is_question:
        respect += 1
        trust += 1

    # SoulForge legacy bonuses (daily first / streak / memory / touch)
    if is_first_today:
        affection += 3
    if streak_days >= 2:
        affection += 2
    for mt in memory_types or []:
        if mt in ("PREFERENCE", "EVENT"):
            affection += 2
    if touch_bonus > 0:
        affection += min(5, touch_bonus)
        comfort += 1

    # Non-linear affection growth
    cur = state.get("affection", 0)
    phase = 1.5 if cur < 300 else 1.0 if cur < 700 else 0.7
    affection = int(affection * phase)

    # ±20% variance on the two headline axes
    affection = int(affection * (1 + (rng.random() - 0.5) * 0.4))
    trust = int(trust * (1 + (rng.random() - 0.5) * 0.4))

    return {
        "energy": energy,
        "affection": _clamp(affection, -5, 10),
        "trust": _clamp(trust, -3, 5),
        "intimacy": _clamp(intimacy, -2, 5),
        "comfort": _clamp(comfort, -3, 3),
        "respect": _clamp(respect, -2, 3),
    }


def merge_updates(baseline: dict[str, int], llm: dict | None) -> dict[str, int]:
    """Clamp LLM-suggested deltas relative to the heuristic baseline."""
    merged = dict(baseline)
    if not llm:
        return merged

    def _num(key: str) -> float | None:
        v = llm.get(key, llm.get(f"{key}_delta"))
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    v = _num("affection")
    if v is not None:
        cap = max(abs(baseline.get("affection", 0)) * 2, 5)
        merged["affection"] = _clamp(v, -cap, cap)
    v = _num("trust")
    if v is not None:
        cap = max(abs(baseline.get("trust", 0)) * 2, 3)
        merged["trust"] = _clamp(v, -cap, cap)
    for key in ("intimacy", "comfort", "respect"):
        v = _num(key)
        if v is not None:
            merged[key] = _clamp(v, -3, 5)
    # energy is never the LLM's to change
    merged["energy"] = baseline.get("energy", 0)
    return merged


def apply_deltas(state: dict, deltas: dict[str, int]) -> dict:
    new = dict(state)
    for axis in AXES:
        d = int(deltas.get(axis, 0) or 0)
        lo, hi = AXIS_LIMITS[axis]
        new[axis] = _clamp(new.get(axis, 0) + d, lo, hi)
    new["affinity"] = new["affection"]
    return new


def lock_relationship_axes(deltas: dict[str, int]) -> dict[str, int]:
    """Companion mode: only energy may move."""
    return {axis: (deltas.get(axis, 0) if axis == "energy" else 0) for axis in AXES}


# ──────────────────────────────────────────────
# Wall-clock decay
# ──────────────────────────────────────────────


@dataclass
class DecayResult:
    state: dict
    deltas: dict[str, int] = field(default_factory=dict)
    mood_cause: str | None = None
    applied: bool = False


def apply_time_decay(state: dict, now: datetime | None = None) -> DecayResult:
    """Per-axis clocks (aikeya applyTimeDecay), idempotent via decay_clocks."""
    now = now or datetime.now(UTC)
    last = _parse_dt(state.get("last_interaction_at"))
    if not last:
        return DecayResult(state=state)
    clocks = dict(state.get("decay_clocks") or {})
    stamp = _parse_dt(clocks.get("at"))
    if stamp and (now - stamp).total_seconds() < _DECAY_MIN_GAP_S:
        return DecayResult(state=state)

    # Decay is measured from the later of last interaction / last decay pass so
    # a long absence is charged once, not on every read.
    origin = max(last, stamp) if stamp else last
    hours_total = (now - last).total_seconds() / 3600
    hours_since_origin = (now - origin).total_seconds() / 3600
    if hours_since_origin < 0.5:
        return DecayResult(state=state)

    deltas: dict[str, int] = {}
    energy = state.get("energy", 100)
    if energy < 100:
        if hours_since_origin >= 6:
            deltas["energy"] = 100 - energy
        else:
            rate = min(1.0, hours_since_origin / 6)
            deltas["energy"] = max(1, int((100 - energy) * rate + 0.999))

    if state.get("app_mode") != "companion":
        affection = state.get("affection", 0)
        if hours_total > 48 and affection > 0 and hours_since_origin >= 24:
            days_away = int(hours_total // 24) - 2
            rate = min(0.05, 0.01 * max(1, days_away))
            deltas["affection"] = -min(int(affection * rate), 50)
        trust = state.get("trust", 0)
        if hours_total > 168 and trust > 0 and hours_since_origin >= 24:
            weeks_away = int(hours_total // 168)
            deltas["trust"] = -min(weeks_away * 2, 10)

    mood_cause = "想你了" if hours_total > 72 else None
    new = apply_deltas(state, deltas) if deltas else dict(state)
    new["decay_clocks"] = {**clocks, "at": _iso(now)}
    return DecayResult(state=new, deltas=deltas, mood_cause=mood_cause, applied=True)


# ──────────────────────────────────────────────
# Turn result
# ──────────────────────────────────────────────


@dataclass
class TurnResult:
    state: dict
    deltas: dict[str, int]
    stage_changed: bool = False
    from_stage: str | None = None

    def to_payload(self) -> dict:
        return relationship_payload(
            self.state,
            deltas=self.deltas,
            stage_changed=self.stage_changed,
            from_stage=self.from_stage,
        )


def relationship_payload(
    state: dict,
    *,
    deltas: dict[str, int] | None = None,
    stage_changed: bool = False,
    from_stage: str | None = None,
) -> dict:
    """Wire shape shared by SSE `relationship`, ChatResponse and GET /relationship."""
    return {
        "type": "relationship",
        "stage": normalize_stage(state.get("stage")),
        "app_mode": state.get("app_mode", "dating_sim"),
        "axes": {axis: state.get(axis, 0) for axis in AXES},
        "deltas": {k: v for k, v in (deltas or {}).items() if v},
        "stage_changed": stage_changed,
        "from_stage": from_stage,
        "near_stage": near_stage(state),
        "days_known": days_known(state),
        "total_interactions": state.get("total_interactions", 0),
        "streak_days": state.get("streak_days", 0),
        "behavior": STAGE_BEHAVIORS[normalize_stage(state.get("stage"))].__dict__
        if normalize_stage(state.get("stage")) in STAGE_BEHAVIORS
        else None,
    }


# ──────────────────────────────────────────────
# Prompt description
# ──────────────────────────────────────────────

STAGE_ZH: dict[str, str] = {
    COMPANION_STAGE: "陪伴者",
    "STRANGER": "陌生人",
    "ACQUAINTANCE": "初识",
    "FRIEND": "朋友",
    "CLOSE_FRIEND": "挚友",
    "ROMANTIC_INTEREST": "心动",
    "DATING": "恋人",
    "COMMITTED": "承诺的伴侣",
    "SOULMATE": "灵魂伴侣",
}


def _band(value: int, bands: list[tuple[int, str]]) -> str:
    for threshold, label in bands:
        if value >= threshold:
            return label
    return bands[-1][1]


def describe_axes(state: dict) -> dict[str, str]:
    a = state.get("affection", 0)
    return {
        "affection": _band(
            a,
            [
                (900, "深深地爱着"),
                (700, "很深的感情"),
                (450, "喜欢得越来越明显"),
                (250, "有点喜欢"),
                (100, "在慢慢升温"),
                (0, "刚认识"),
            ],
        ),
        "trust": _band(
            state.get("trust", 0),
            [
                (90, "完全信任"),
                (70, "很信任"),
                (50, "开始信任"),
                (25, "还在建立信任"),
                (0, "还有点防备"),
            ],
        ),
        "intimacy": _band(
            state.get("intimacy", 0),
            [
                (90, "深度的情感连接"),
                (70, "情感上很亲近"),
                (50, "越来越亲近"),
                (25, "在慢慢敞开"),
                (0, "保持距离"),
            ],
        ),
        "comfort": _band(
            state.get("comfort", 0),
            [
                (90, "完全自在"),
                (70, "很放松"),
                (50, "挺自在"),
                (25, "还在适应"),
                (0, "有点拘谨"),
            ],
        ),
        "energy": _band(
            state.get("energy", 100),
            [
                (80, "精力充沛"),
                (60, "状态不错"),
                (40, "一般"),
                (20, "有点累"),
                (0, "累坏了"),
            ],
        ),
    }


def describe_for_prompt(state: dict) -> str:
    """Compact `<current_state>` block for the system prompt (aikeya prompt-builder)."""
    stage = normalize_stage(state.get("stage"))
    axes = describe_axes(state)
    beh = STAGE_BEHAVIORS.get(stage)
    lines = [
        f"关系阶段：{STAGE_ZH.get(stage, stage)}",
        f"好感 {state.get('affection', 0)}/1000（{axes['affection']}）· "
        f"信任 {state.get('trust', 0)}（{axes['trust']}）· "
        f"亲密 {state.get('intimacy', 0)}（{axes['intimacy']}）· "
        f"自在 {state.get('comfort', 0)}（{axes['comfort']}）· "
        f"尊重 {state.get('respect', 0)}",
        f"精力 {state.get('energy', 100)}/100（{axes['energy']}）",
    ]
    meta = []
    if days_known(state):
        meta.append(f"相识 {days_known(state)} 天")
    if state.get("total_interactions"):
        meta.append(f"聊过 {state['total_interactions']} 次")
    if state.get("streak_days", 0) >= 2:
        meta.append(f"连续 {state['streak_days']} 天")
    if meta:
        lines.append(" · ".join(meta))
    if beh:
        romance = "" if beh.romantic == "none" else f" · 浪漫程度 {beh.romantic}"
        lines.append(
            f"分寸：身体亲昵 {beh.physical_affection}% · 袒露自己 {beh.vulnerability}% · "
            f"主动开启话题 {int(beh.initiation * 100)}%{romance}"
        )
    if state.get("app_mode") == "companion":
        lines.append("（陪伴模式：不推进感情线，只做温暖可靠的陪伴）")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────

_AXES_COLUMNS = (
    "trust, intimacy, comfort, respect, energy, app_mode, saved_stage, "
    "total_interactions, first_interaction_at, last_interaction_at, "
    "decay_clocks, completed_events"
)
