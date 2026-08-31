"""灵魂问卷：计分、映射规则、身份与角色包的单元测试（纯函数，无 IO）。"""

import pytest

from ai_core.services import soul_quiz as sq


def fill(default=0, **overrides):
    """answers: 全部选 default，按题号覆盖。"""
    a = {q["id"]: default for q in sq.QUESTIONS}
    a.update(overrides)
    return a


def test_questions_shape():
    assert len(sq.QUESTIONS) == 23
    for q in sq.QUESTIONS:
        assert q["id"] and q["text"] and len(q["options"]) >= 2
        for o in q["options"]:
            assert o.get("scores") or o.get("pref")


def test_score_extremes_and_bounds():
    hi = sq.score(fill(0))
    lo = sq.score(fill(1))
    for d in sq.TRAIT_DIMS:
        assert 0.0 <= hi[d] <= 1.0 and 0.0 <= lo[d] <= 1.0
    assert hi["E"] == 1.0 and lo["E"] == 0.0  # q1-3 全 A / 全 B
    assert hi["ANX"] > lo["ANX"]


def test_score_missing_answers_neutral_and_bad_index_raises():
    assert sq.score({"q1": 0})["A"] == 0.5  # 没答的维度回中性
    with pytest.raises(ValueError):
        sq.score({"q1": 9})


def test_similarity_with_shrink_and_no_neuroticism():
    ai_hi = sq.derive_ai_personality(sq.score(fill(0)))
    ai_lo = sq.derive_ai_personality(sq.score(fill(1)))
    assert ai_hi["E"] > ai_lo["E"]  # 相似方向
    assert ai_hi["E"] < 1.0 and ai_lo["E"] > 0.0  # 收缩，不复制极端
    assert ai_hi["N"] == ai_lo["N"] == 0.2  # AI 永远稳定


def test_dominance_is_complementary():
    bossy = sq.score(fill(1, q13=0, q14=0))  # 用户强支配
    meek = sq.score(fill(1))  # 用户全选 B → 低支配
    assert sq.derive_ai_personality(bossy)["DOM"] < sq.derive_ai_personality(meek)["DOM"]


def test_pad_formula_range_and_direction():
    warm = sq.derive_pad({"E": 0.7, "A": 0.9, "O": 0.5, "C": 0.5, "N": 0.2, "DOM": 0.5})
    cold = sq.derive_pad({"E": 0.3, "A": 0.2, "O": 0.5, "C": 0.5, "N": 0.2, "DOM": 0.5})
    for pad in (warm, cold):
        assert all(-1.0 <= v <= 1.0 for v in pad.values())
    assert warm["p"] > cold["p"] and warm["d"] > cold["d"] - 1e-9


def test_attachment_drives_behavior_monotonically():
    anxious = sq.derive_behavior(sq.score(fill(1, q15=0, q16=0, q17=0)))
    avoidant = sq.derive_behavior(sq.score(fill(0, q16=1, q17=1, q18=0)))
    assert anxious["proactive"] > avoidant["proactive"]
    assert anxious["reassure"] and not anxious["give_space"]
    assert avoidant["give_space"]


def test_voice_pool_and_rate_follow_extraversion():
    intro = sq.score(fill(1, q21=2))  # 内向 + 沉稳男声
    extro = sq.score(fill(0, q21=2))
    vi = sq.derive_voice(intro, sq.derive_ai_personality(intro))["edge"]
    ve = sq.derive_voice(extro, sq.derive_ai_personality(extro))["edge"]
    assert vi["voice"] == ve["voice"] == "zh-CN-YunxiNeural"
    assert vi["rate"] < ve["rate"]


def test_identity_stable_per_seed_and_gendered():
    p = sq.score(fill(0, q21=3))  # 少年音 → 男名
    i1 = sq.generate_identity(p, sq.derive_ai_personality(p), seed="u1")
    i2 = sq.generate_identity(p, sq.derive_ai_personality(p), seed="u1")
    i3 = sq.generate_identity(p, sq.derive_ai_personality(p), seed="u2")
    assert i1["name"] == i2["name"] and i1["gender"] == "m"
    assert i3["name"]  # 换 seed 可能换名，但总有名字
    assert i1["archetype_label"] in dict(sq.ARCHETYPES.values()) or any(
        i1["archetype_label"] == lbl for lbl, _ in sq.ARCHETYPES.values()
    )


def test_build_character_bundle_is_pipeline_shaped():
    b = sq.build_character(sq.score(fill(1)), seed="t")
    c = b["character"]
    assert set(c["personality"]) == {"extrovert", "humor", "warmth", "curiosity", "energy"}
    assert all(0 <= v <= 100 for v in c["personality"].values())
    assert c["archetype"] == "HUMAN" and "主人" in c["forbidden"]
    assert c["relationship"] == "专属陪伴"  # 不能撞上 8 个恋爱关系值（会切 idol 模板）
    e = b["engine_entry"]
    assert e["id"].startswith("soul-") and e["voice"]["edge"]["voice"]
    assert b["expression"]["pad_baseline"] == b["pad"]
    # 安静型用户 → 低唤醒基线、低表情烈度
    assert b["expression"]["intensity"] <= 0.5


def test_extreme_profiles_read_differently():
    quiet_anxious = sq.build_character(sq.score(fill(1, q15=0, q16=0)), seed="a")
    lively_bossy = sq.build_character(sq.score(fill(0, q16=1, q19=1, q20=1)), seed="b")
    assert quiet_anxious["behavior"]["reassure"]
    assert (
        quiet_anxious["character"]["personality"]["energy"]
        < lively_bossy["character"]["personality"]["energy"]
    )
    assert (
        quiet_anxious["identity"]["archetype_label"] != lively_bossy["identity"]["archetype_label"]
    )


def test_companion_never_cold_even_for_blunt_users():
    blunt = sq.score(fill(1))  # 全 B：低宜人
    ai = sq.derive_ai_personality(blunt)
    assert ai["A"] >= 0.35
    assert sq.five_traits(ai, blunt)["warmth"] > 30  # 不触发 prompt 的"低温"人格描述


def test_neutral_options_score_half():
    p = sq.score(fill(0, q13=2, q14=2, q15=2, q16=2, q17=2, q18=2))
    assert (
        p["DOM"] == 0.5
        and p["ANX"] == pytest.approx(0.5, abs=0.2)
        and p["AVO"] == pytest.approx(0.5, abs=0.2)
    )


def test_auto_voice_follows_personality_and_sets_gender():
    quiet = sq.score(fill(1, q21=4))  # 内向低支配 + 让TA自己决定
    v = sq.derive_voice(quiet, sq.derive_ai_personality(quiet))["edge"]
    assert v["voice"] in ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural")
    assert quiet["prefs"]["voice"] != "auto"  # 性别已定，名字/模型不会错配
    lively = sq.score(fill(0, q21=4))
    assert (
        sq.derive_voice(lively, sq.derive_ai_personality(lively))["edge"]["voice"]
        == "zh-CN-XiaoyiNeural"
    )
