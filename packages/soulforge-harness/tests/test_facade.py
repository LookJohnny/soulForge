"""Facade: Soul round trip, quiz generation, and the Harness personality loop."""

import pytest

from soulforge_harness import Harness, Soul
from soulforge_harness.soul import quiz


def make_soul():
    answers = {q["id"]: 1 for q in quiz.QUESTIONS}
    answers.update({"q15": 0, "q19": 0, "q20": 0, "q21": 0})
    return Soul.from_quiz(answers, seed="t")


def test_soul_quiz_roundtrip(tmp_path):
    soul = make_soul()
    assert soul.name and soul.character["archetype"] == "HUMAN"
    p = soul.save(tmp_path / "her.soul")
    again = Soul.load(p)
    assert again.name == soul.name
    assert again.expression["pad_baseline"] == soul.expression["pad_baseline"]
    assert again.studio["speech_style"] == soul.studio["speech_style"]


def test_soul_save_encrypted_requires_passphrase(tmp_path):
    soul = make_soul()
    p = soul.save(tmp_path / "her.soul", passphrase="SF-TEST")
    with pytest.raises(ValueError):
        Soul.load(p)
    assert Soul.load(p, passphrase="SF-TEST").name == soul.name


def test_harness_loop_updates_state_without_network():
    soul = make_soul()
    seen = []

    def fake_llm(messages):
        seen.append(messages)
        return "我在呢。"

    h = Harness(soul, llm=fake_llm)
    before = dict(h.relationship)
    reply = h.chat("我今天加班到八点，有点累", user_mood="tired")
    assert reply == "我在呢。"
    assert h.relationship["total_interactions"] == 1
    assert h.relationship["affection"] >= before["affection"]
    assert h.stage in ("STRANGER", "ACQUAINTANCE")
    system = seen[0][0]
    assert system["role"] == "system" and soul.name in system["content"]
    h.remember("用户喜欢抹茶拿铁")
    h.chat("推荐点喝的", user_mood="neutral")
    assert "抹茶拿铁" in seen[1][0]["content"]
    assert -1 <= h.pad.p <= 1


def test_life_runtime_boots_from_soul():
    from soulforge_harness.runtime import MockBehaviorLLM, WorldState

    soul = make_soul()
    rt = soul and Harness(soul, llm=lambda m: "ok").life_runtime(
        world=WorldState(sim_minute=15 * 60), llm=MockBehaviorLLM()
    )
    actions = rt.tick(15 * 60)
    assert set(actions) == {soul.studio["id"]}


def test_auto_memory_survives_beyond_the_history_window():
    soul = make_soul()
    seen = []
    h = Harness(soul, llm=lambda m: (seen.append(m), "好。")[1], history_turns=3)
    h.chat("对了，你可以叫我小乔。我最喜欢抹茶拿铁，讨厌香菜")
    for i in range(8):  # push the declaration far out of the rolling window
        h.chat(f"随便聊点什么 {i}")
    h.chat("你还记得我喜欢喝什么吗？")
    system = seen[-1][0]["content"]
    assert "抹茶拿铁" in system and "小乔" in system
