"""Tests for deterministic companion memory policy rules."""

from ai_core.services.memory_policy import MemoryPolicyEngine


def test_sensitive_memory_requires_confirmation_on_write():
    engine = MemoryPolicyEngine()
    candidate = {
        "memory_type": "EPISODIC",
        "content": "我的身份证号码是123456199901011234",
        "confidence_score": 0.9,
    }

    decision = engine.evaluate_write(candidate)

    assert decision.decision == "REQUIRE_CONFIRMATION"
    assert decision.use_mode == "REQUIRE_CONFIRMATION"


def test_relational_preference_is_assigned_to_relational_layer():
    engine = MemoryPolicyEngine()

    layer = engine.assign_layer("PREFERENCE", "不要迎合我，先指出风险")

    assert layer == "RELATIONAL"
    assert engine.relation_axis("不要迎合我，先指出风险") == "directness"


def test_one_time_mood_is_not_profile_memory():
    engine = MemoryPolicyEngine()

    layer = engine.assign_layer("PREFERENCE", "今天有点焦虑")

    assert layer == "EPISODIC"


def test_companion_importance_scores_major_events_above_trivia():
    engine = MemoryPolicyEngine()

    major = engine.score_importance("用户说明天要参加重要考试", "EPISODIC")
    trivia = engine.score_importance("用户今天午饭吃了面条", "EPISODIC")

    assert major >= 8
    assert trivia < major


def test_implicit_memory_stays_implicit_on_read():
    engine = MemoryPolicyEngine()
    memory = {
        "content": "用户喜欢先结论后论证",
        "sensitivity_level": "LOW",
        "permission_level": "AUTO",
        "conflict_status": "NONE",
        "implicit_only": True,
        "can_surface_directly": False,
    }

    decision = engine.evaluate_read(memory, context={"user_mood": "neutral"})

    assert decision.decision == "IMPLICIT_ONLY"
    assert decision.use_mode == "IMPLICIT_ONLY"


def test_child_sensitive_memory_is_blocked_on_read():
    engine = MemoryPolicyEngine()
    memory = {
        "content": "用户说自己很焦虑",
        "sensitivity_level": "MEDIUM",
        "permission_level": "AUTO",
        "conflict_status": "NONE",
        "implicit_only": True,
    }

    decision = engine.evaluate_read(memory, context={"is_child": True})

    assert decision.decision == "BLOCKED"
