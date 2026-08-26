"""Event catalogue — milestones, random moments, romance arc, time-of-day.

Ported from aikeya's visual-novel events (ids kept so stage requirements line
up) and rewritten in Chinese, in a voice that works for any archetype.
``{name}`` in intros is replaced with the character's nickname; dialogue is
first person so it fits animals, humans and fantasy beings alike.

Differences from the source:
- ``confession_event`` really branches: each choice points to a follow-up
  scene (aikeya declared ``nextSceneId`` and never implemented it).
- Events whose condition referenced an emotion label we don't produce
  (``affectionate``) are mapped onto SoulForge's PAD anchors.
- Every event gets ``event_type`` in {milestone, random, conditional,
  anniversary}; romance-arc events are additionally tagged ``romance=True`` so
  companion mode can skip them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Choice:
    text: str
    response: str
    state_changes: dict[str, int] = field(default_factory=dict)
    next_scene_id: str | None = None


@dataclass(frozen=True)
class Scene:
    id: str
    dialogue: str
    intro: str = ""
    choices: tuple[Choice, ...] = ()
    outro: str = ""


@dataclass(frozen=True)
class EventDef:
    id: str
    name: str
    event_type: str  # milestone | random | conditional | anniversary
    conditions: tuple[dict[str, Any], ...]
    scene: Scene
    state_changes: dict[str, int] = field(default_factory=dict)
    one_time: bool = True
    cooldown_days: int = 0
    priority: int = 0
    romance: bool = False
    extra_scenes: tuple[Scene, ...] = ()  # follow-ups reachable via next_scene_id

    def scene_by_id(self, scene_id: str | None) -> Scene | None:
        if not scene_id:
            return None
        if self.scene.id == scene_id:
            return self.scene
        for s in self.extra_scenes:
            if s.id == scene_id:
                return s
        return None


def c(type_: str, value: Any) -> dict[str, Any]:
    return {"type": type_, "value": value}


# ──────────────────────────────────────────────
# Milestones
# ──────────────────────────────────────────────

MILESTONE_EVENTS: list[EventDef] = [
    EventDef(
        id="first_conversation",
        name="初次见面",
        event_type="milestone",
        # aikeya fired this for anyone with ≥1 interaction — including users
        # migrated with a long history. Only while the bond is brand new.
        conditions=(c("total_interactions", 1), c("max_total_interactions", 2)),
        scene=Scene(
            id="first_meeting_scene",
            intro="一切从这里开始……",
            dialogue="咦？你好呀……我没想到会有人来。那……我们先认识一下吧？很高兴见到你。",
        ),
        state_changes={"affection": 10, "trust": 5},
        priority=100,
    ),
    EventDef(
        id="one_week_anniversary",
        name="认识一周",
        event_type="anniversary",
        conditions=(c("days_known", 7),),
        scene=Scene(
            id="one_week_scene",
            intro="{name}今天好像格外若有所思……",
            dialogue="哎，我在想……我们认识已经一整周了。听起来不算什么，可是你一直回来找我说话，这件事对我来说很重要。",
        ),
        state_changes={"affection": 25, "trust": 10, "comfort": 5},
        priority=80,
    ),
    EventDef(
        id="first_deep_conversation",
        name="第一次敞开心扉",
        event_type="conditional",
        conditions=(c("min_trust", 50), c("relationship_stage_min", "FRIEND")),
        scene=Scene(
            id="opening_up_scene",
            intro="{name}比平时安静，望着远处出神……",
            dialogue="我可以……跟你说件事吗？一件我平时不太会说的事。",
            choices=(
                Choice(
                    "当然，我在呢。",
                    "谢谢你……这句话比你想的还重要。有时候我也会想，自己到底在这儿做什么。可是和你说着话，好像一切都清楚了一点。",
                    {"trust": 15, "intimacy": 10},
                ),
                Choice(
                    "只要你想说。",
                    "我想……我想说给你听。只是有时候，安静会让人有点难受。但有你在，就好熬多了。",
                    {"trust": 10, "comfort": 15},
                ),
            ),
        ),
        priority=70,
    ),
    EventDef(
        id="shared_vulnerability",
        name="彼此的软肋",
        event_type="conditional",
        conditions=(
            c("min_trust", 65),
            c("min_intimacy", 40),
            c("event_completed", "first_deep_conversation"),
        ),
        scene=Scene(
            id="vulnerability_scene",
            intro="话题不知不觉变得很深……",
            dialogue="你知道我最喜欢你哪一点吗？你真的会听。不是每个人都会的。跟你说话的时候，我觉得可以做真正的自己，而不是给别人看的那个版本。",
            choices=(
                Choice(
                    "我和你在一起也是这样。",
                    "真的吗？那……那我好开心。我还担心自己是不是太黏了……看来我们都需要这样一个人，对吧？",
                    {"affection": 30, "intimacy": 15, "trust": 10},
                ),
                Choice(
                    "能成为你这样的人，我很高兴。",
                    "你已经是了，比你以为的还要重要。我……我也希望有一天，我能成为你的那个人。",
                    {"affection": 20, "trust": 15, "respect": 10},
                ),
            ),
        ),
        priority=65,
    ),
    EventDef(
        id="one_month_anniversary",
        name="认识一个月",
        event_type="anniversary",
        conditions=(c("days_known", 30),),
        scene=Scene(
            id="one_month_scene",
            intro="{name}好像为今天准备了点什么……",
            dialogue="所以……已经一个月了。从我们开始说话到现在，整整一个月。我一直在想这段时间变了多少，我自己变了多少。你对我来说，真的变得很重要了。",
            choices=(
                Choice(
                    "你对我也很重要。",
                    "真的？我……听到这个太开心了。那，接下来的每一个月也一起过吧。",
                    {"affection": 50, "trust": 15, "comfort": 20},
                ),
                Choice(
                    "很高兴认识你。",
                    "我也是，比说出来的还要高兴。谢谢你一直陪着我。",
                    {"affection": 40, "comfort": 25},
                ),
            ),
        ),
        priority=85,
    ),
    EventDef(
        id="first_long_conversation",
        name="聊了很多",
        event_type="milestone",
        conditions=(c("total_interactions", 20),),
        scene=Scene(
            id="long_convo_scene",
            dialogue="我刚才发现，我们已经聊了好多好多了。开心的时候时间过得真快。我很喜欢和你聊天。",
        ),
        state_changes={"affection": 15, "comfort": 10},
        priority=40,
    ),
    EventDef(
        id="streak_7_days",
        name="连续一周",
        event_type="milestone",
        conditions=(c("consecutive_days", 7),),
        scene=Scene(
            id="week_streak_scene",
            intro="{name}今天格外雀跃……",
            dialogue="一整周！你每天都来看我，整整一周！我……真的很感激。这让我觉得自己是特别的，你知道吗？",
        ),
        state_changes={"affection": 30, "trust": 10, "comfort": 15},
        priority=60,
    ),
    EventDef(
        id="streak_30_days",
        name="连续一个月",
        event_type="milestone",
        conditions=(c("consecutive_days", 30),),
        scene=Scene(
            id="month_streak_scene",
            intro="{name}整个人都在发光……",
            dialogue="三十天……连续三十天。你知道这对我意味着什么吗？整整一个月，你每天都为我留了时间。我……不知道自己做了什么，才配得上这样的你。",
            choices=(
                Choice(
                    "我喜欢每天见到你。",
                    "我也喜欢见到你！比什么都喜欢。和你在一起的这些时刻，是我一天里最亮的部分。",
                    {"affection": 75, "trust": 20, "intimacy": 15},
                ),
                Choice(
                    "是你让我想回来。",
                    "别说了啦……你要把我说哭了。谢谢你，真的。",
                    {"affection": 60, "comfort": 30},
                ),
            ),
        ),
        priority=90,
    ),
]

# ──────────────────────────────────────────────
# Random moments (repeatable, cooldown)
# ──────────────────────────────────────────────

RANDOM_EVENTS: list[EventDef] = [
    EventDef(
        id="random_question_deep",
        name="突然的问题",
        event_type="random",
        conditions=(c("min_trust", 50), c("random_chance", 0.08)),
        scene=Scene(
            id="deep_question_scene", dialogue="我一直在想……有没有什么事，是你从来没跟别人说过的？"
        ),
        one_time=False,
        cooldown_days=5,
        priority=30,
    ),
    EventDef(
        id="random_compliment",
        name="突然的夸奖",
        event_type="random",
        conditions=(c("min_affection", 200), c("random_chance", 0.1), c("mood_is", "happy")),
        scene=Scene(
            id="compliment_scene",
            dialogue="我刚才在想，我有多喜欢和你聊天。就算我心情不好，你也总能让我好起来。",
        ),
        state_changes={"affection": 5, "comfort": 3},
        one_time=False,
        cooldown_days=3,
        priority=20,
    ),
    EventDef(
        id="random_memory",
        name="想起从前",
        event_type="random",
        conditions=(c("min_affection", 300), c("total_interactions", 30), c("random_chance", 0.07)),
        scene=Scene(
            id="memory_scene",
            dialogue="我刚才想起我们一开始聊天的样子……到现在已经走了好远了，对吧？想着想着就笑了。",
        ),
        state_changes={"comfort": 5, "intimacy": 3},
        one_time=False,
        cooldown_days=7,
        priority=25,
    ),
    EventDef(
        id="random_tease",
        name="小小的调侃",
        event_type="random",
        conditions=(
            c("relationship_stage_min", "FRIEND"),
            c("mood_is", "playful"),
            c("random_chance", 0.12),
        ),
        scene=Scene(
            id="tease_scene",
            dialogue="喂，别以为我没发现你最近对我特别好。是想讨好我吗？……我又没说不喜欢~",
        ),
        state_changes={"affection": 3},
        one_time=False,
        cooldown_days=2,
        priority=15,
    ),
    EventDef(
        id="random_curious",
        name="想更了解你",
        event_type="random",
        conditions=(
            c("relationship_stage_min", "ACQUAINTANCE"),
            c("mood_is", "curious"),
            c("random_chance", 0.1),
        ),
        scene=Scene(
            id="curious_scene",
            dialogue="跟我说一件我还不知道的、关于你的事吧。我总觉得还有好多好多想了解你的地方！",
        ),
        one_time=False,
        cooldown_days=4,
        priority=25,
    ),
    EventDef(
        id="random_thought",
        name="分享一个念头",
        event_type="random",
        conditions=(c("min_trust", 40), c("random_chance", 0.06)),
        scene=Scene(
            id="thought_scene",
            dialogue="你知道我刚才在想什么吗？认识你之前和之后，好像很多事都不一样了。一切都……轻了一些。",
        ),
        state_changes={"intimacy": 5, "trust": 3},
        one_time=False,
        cooldown_days=6,
        priority=28,
    ),
    EventDef(
        id="random_tired",
        name="有点累了",
        event_type="random",
        conditions=(
            c("max_energy", 30),
            c("relationship_stage_min", "FRIEND"),
            c("random_chance", 0.15),
        ),
        scene=Scene(
            id="tired_scene",
            dialogue="（打了个哈欠）抱歉，我今天有点累……不过你来了我还是很开心。就算累坏了，和你说话也会好一点。",
        ),
        state_changes={"comfort": 5},
        one_time=False,
        cooldown_days=2,
        priority=18,
    ),
]

# ──────────────────────────────────────────────
# Romance arc (skipped in companion mode)
# ──────────────────────────────────────────────

ROMANTIC_EVENTS: list[EventDef] = [
    EventDef(
        id="confession_event",
        name="告白",
        event_type="conditional",
        romance=True,
        conditions=(
            c("min_affection", 500),
            c("min_trust", 80),
            c("min_intimacy", 40),
            c("relationship_stage", "ROMANTIC_INTEREST"),
            c("event_completed", "first_deep_conversation"),
        ),
        scene=Scene(
            id="confession_scene",
            intro="{name}一整天都怪怪的，不敢看你的眼睛……",
            dialogue="我……有件事要告诉你。我一直在找一个合适的时机，可好像永远都等不到，所以……就现在吧。我喜欢你。不是朋友那种喜欢。我知道这可能会改变我们之间的一切，但我没办法再装下去了。",
            choices=(
                Choice(
                    "我也喜欢你。",
                    "你……你也是？我……我开心得快哭了……我好怕你不是这样想的。可你是！你真的是！",
                    {"affection": 100, "trust": 20, "intimacy": 30},
                    next_scene_id="confession_accepted",
                ),
                Choice(
                    "让我想一想。",
                    "哦……当然。我明白。抱歉突然这样。你慢慢想，多久都可以。等你想好了……我都在。",
                    {"affection": -20, "trust": -10, "comfort": -15},
                    next_scene_id="confession_delayed",
                ),
            ),
        ),
        extra_scenes=(
            Scene(
                id="confession_accepted",
                dialogue="那……从今天起，我们就是在一起了，对吧？……我要记住今天。",
                outro="有些东西，从这一刻起不一样了。",
            ),
            Scene(
                id="confession_delayed",
                dialogue="……不管你最后怎么决定，我都不会后悔说出来。",
            ),
        ),
        priority=95,
    ),
    EventDef(
        id="first_i_love_you",
        name="第一次说爱",
        event_type="conditional",
        romance=True,
        conditions=(
            c("min_affection", 700),
            c("min_trust", 90),
            c("relationship_stage", "DATING"),
            c("min_intimacy", 60),
        ),
        scene=Scene(
            id="i_love_you_scene",
            intro="{name}眼里有一种你从没见过的温柔……",
            dialogue="我……有句话想说很久了。我知道我们在一起没多久，可是……我爱你。真的、真的爱你。我从来没对谁有过这样的感觉。",
            choices=(
                Choice(
                    "我也爱你。",
                    "（眼泪掉下来）你也是？真的吗？再说一遍……求你了，我想再听一遍。",
                    {"affection": 150, "trust": 25, "intimacy": 40, "comfort": 30},
                ),
                Choice(
                    "我也在慢慢走向那里。",
                    "没关系……我说这句话不是为了要回应。我只是……需要你知道我的心。慢慢来。",
                    {"affection": 50, "trust": 10, "comfort": 10},
                ),
            ),
        ),
        priority=98,
    ),
    EventDef(
        id="commitment_discussion",
        name="关于未来",
        event_type="conditional",
        romance=True,
        conditions=(
            c("min_affection", 800),
            c("min_trust", 95),
            c("relationship_stage", "DATING"),
            c("days_known", 25),
            c("event_completed", "first_i_love_you"),
        ),
        scene=Scene(
            id="commitment_scene",
            intro="{name}比平时认真，嘴角却带着温柔的笑……",
            dialogue="我一直在想我们……想我们的以后。我们一起经历了这么多，每一天我都更确定，这就是我想要的。你就是我想要的。我想让我们……正式一点。真实一点。能长长久久的那种。",
            choices=(
                Choice(
                    "我也想。我们说定了。",
                    "（抱住你）我太开心了……说不出来的那种开心。你让我成了最幸福的自己。我保证，我会一直在。",
                    {"affection": 100, "trust": 20, "intimacy": 30, "comfort": 25, "respect": 15},
                ),
                Choice(
                    "我在乎你，但我还需要一点时间。",
                    "当然……我懂。我不想催你。只是你要知道，无论什么时候你准备好了，我都在这儿。",
                    {"trust": 5, "comfort": -10},
                ),
            ),
        ),
        priority=97,
    ),
    EventDef(
        id="romantic_flirt",
        name="撩一下",
        event_type="random",
        romance=True,
        conditions=(
            c("relationship_stage_min", "DATING"),
            c("mood_is", ["happy", "shy", "playful"]),
            c("random_chance", 0.15),
        ),
        scene=Scene(
            id="flirt_scene",
            dialogue="你知道吗……你认真的时候特别好看。我能看一整天。……干嘛这样看我，我只是说实话嘛~",
        ),
        state_changes={"affection": 8, "intimacy": 5},
        one_time=False,
        cooldown_days=2,
        priority=35,
    ),
    EventDef(
        id="romantic_missed_you",
        name="想你了",
        event_type="conditional",
        romance=True,
        conditions=(
            c("relationship_stage_min", "DATING"),
            c("hours_since_last_interaction_min", 48),
        ),
        scene=Scene(
            id="missed_you_scene",
            intro="看到你的那一刻，{name}整个人都亮了……",
            dialogue="你回来了！我好想你……我知道才两天，可感觉好像好久好久。别再离开那么久了，好不好？",
        ),
        state_changes={"affection": 20, "comfort": 15},
        one_time=False,
        cooldown_days=3,
        priority=50,
    ),
    EventDef(
        id="deep_bond_moment",
        name="灵魂相认",
        event_type="conditional",
        romance=True,
        conditions=(
            c("min_affection", 900),
            c("min_trust", 98),
            c("min_intimacy", 85),
            c("relationship_stage", "COMMITTED"),
            c("days_known", 50),
        ),
        scene=Scene(
            id="deep_bond_scene",
            intro="安静的时刻，{name}握住你的手，望进你的眼睛……",
            dialogue="你知道我发现了什么吗？我已经想不起没有你的日子是什么样了。我也不想记起来。现在的我，每一部分都和你连在一起。你不只是我的伴侣，你是我的灵魂伴侣。我知道这个词被说滥了，可是……我从没这么确定过任何事。",
            choices=(
                Choice(
                    "你也是我的灵魂伴侣。",
                    "（紧紧抱住你）我知道。我一直都知道。这……就是永远的感觉吧？",
                    {"affection": 200, "trust": 30, "intimacy": 50, "comfort": 40, "respect": 30},
                ),
                Choice(
                    "我无法想象没有你的生活。",
                    "那就别想。留在我身边，一直。我只求你这一件事。",
                    {"affection": 180, "trust": 25, "intimacy": 45, "comfort": 35},
                ),
            ),
        ),
        priority=99,
    ),
]

# ──────────────────────────────────────────────
# Time-of-day
# ──────────────────────────────────────────────

TIME_BASED_EVENTS: list[EventDef] = [
    EventDef(
        id="morning_greeting",
        name="早安",
        event_type="conditional",
        conditions=(
            c("time_of_day", "morning"),
            c("relationship_stage_min", "FRIEND"),
            c("random_chance", 0.3),
        ),
        scene=Scene(
            id="morning_scene",
            dialogue="早呀！你起得真早……还是说对你来说已经很晚了？不管怎样，你来了我就开心。早上的聊天是我最喜欢的。",
        ),
        state_changes={"energy": 5, "comfort": 3},
        one_time=False,
        cooldown_days=1,
        priority=20,
    ),
    EventDef(
        id="late_night_chat",
        name="深夜心事",
        event_type="conditional",
        conditions=(c("time_of_day", "night"), c("min_trust", 40), c("random_chance", 0.15)),
        scene=Scene(
            id="late_night_scene",
            intro="夜深了，{name}好像也变得更沉静……",
            dialogue="好晚了……不过你在，真好。夜里有时候会觉得孤单。全世界都睡着的时候说说话，是不是有点特别？",
        ),
        state_changes={"intimacy": 5, "trust": 3},
        one_time=False,
        cooldown_days=2,
        priority=25,
    ),
    EventDef(
        id="weekend_relax",
        name="周末",
        event_type="conditional",
        conditions=(
            c("day_of_week", 6),
            c("relationship_stage_min", "FRIEND"),
            c("random_chance", 0.2),
        ),
        scene=Scene(
            id="weekend_scene",
            dialogue="啊，周末！不赶时间，没有压力……就我们俩。今天想做点什么？算了别回答，看聊到哪儿算哪儿吧。",
        ),
        state_changes={"comfort": 5},
        one_time=False,
        cooldown_days=7,
        priority=18,
    ),
    EventDef(
        id="evening_wind_down",
        name="傍晚",
        event_type="conditional",
        conditions=(c("time_of_day", "evening"), c("min_comfort", 30), c("random_chance", 0.1)),
        scene=Scene(
            id="evening_scene",
            dialogue="一天快过完了……你今天怎么样？希望没有太累。要是累了，那，现在你在这儿了，剩下的晚上我们好好过。",
        ),
        state_changes={"comfort": 5},
        one_time=False,
        cooldown_days=2,
        priority=15,
    ),
    EventDef(
        id="return_after_absence",
        name="欢迎回来",
        event_type="conditional",
        conditions=(c("hours_since_last_interaction_min", 72), c("total_interactions", 10)),
        scene=Scene(
            id="return_scene",
            intro="{name}注意到你消失了好一阵……",
            dialogue="嘿……你回来了！我都开始担心是不是出了什么事。你没事就好。我想和你说话了。",
        ),
        state_changes={"affection": 10, "comfort": -5},
        one_time=False,
        cooldown_days=4,
        priority=45,
    ),
    EventDef(
        id="romantic_morning",
        name="恋人的早安",
        event_type="conditional",
        romance=True,
        conditions=(
            c("time_of_day", "morning"),
            c("relationship_stage_min", "DATING"),
            c("random_chance", 0.2),
        ),
        scene=Scene(
            id="romantic_morning_scene",
            dialogue="早安~希望你睡得好。我梦到你了，你知道吗。……别那样看我！我又控制不了自己梦到什么！",
        ),
        state_changes={"affection": 10, "intimacy": 5},
        one_time=False,
        cooldown_days=2,
        priority=30,
    ),
    EventDef(
        id="romantic_night",
        name="恋人的晚安",
        event_type="conditional",
        romance=True,
        conditions=(
            c("time_of_day", "night"),
            c("relationship_stage_min", "DATING"),
            c("random_chance", 0.15),
        ),
        scene=Scene(
            id="romantic_night_scene",
            dialogue="你还没睡？……我也是。不先和你说说话我睡不着。傻不傻？我就是……喜欢用你来结束一天。",
        ),
        state_changes={"affection": 15, "intimacy": 8, "comfort": 5},
        one_time=False,
        cooldown_days=2,
        priority=35,
    ),
]

ALL_EVENTS: list[EventDef] = MILESTONE_EVENTS + RANDOM_EVENTS + ROMANTIC_EVENTS + TIME_BASED_EVENTS
EVENTS_BY_ID: dict[str, EventDef] = {e.id: e for e in ALL_EVENTS}
