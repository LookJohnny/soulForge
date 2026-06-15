"""Tests for Generative Agents-style memory retrieval scoring."""

from datetime import UTC, datetime, timedelta

from ai_core.services.memory import rank_memory_candidates


def test_rank_memory_candidates_prefers_recent_important_relevant_memory():
    now = datetime(2026, 6, 12, 12, tzinfo=UTC)
    old_exam_memory = {
        "id": "old",
        "memory_layer": "EPISODIC",
        "memory_table": "episodic_memories",
        "content": "用户三个月前说自己有一次考试",
        "importance_score": 5,
        "confidence_score": 0.8,
        "retrieval_weight": 0.6,
        "timestamp": (now - timedelta(days=90)).isoformat(),
        "sensitivity_level": "LOW",
    }
    recent_exam_memory = {
        "id": "recent",
        "memory_layer": "EPISODIC",
        "memory_table": "episodic_memories",
        "content": "用户今天早上说下午有一场重要考试",
        "importance_score": 8,
        "confidence_score": 0.75,
        "retrieval_weight": 0.6,
        "timestamp": (now - timedelta(hours=4)).isoformat(),
        "sensitivity_level": "LOW",
    }
    unrelated_memory = {
        "id": "lunch",
        "memory_layer": "EPISODIC",
        "memory_table": "episodic_memories",
        "content": "用户今天午饭吃了面条",
        "importance_score": 3,
        "confidence_score": 0.9,
        "retrieval_weight": 0.6,
        "timestamp": (now - timedelta(hours=1)).isoformat(),
        "sensitivity_level": "LOW",
    }

    ranked = rank_memory_candidates(
        [old_exam_memory, recent_exam_memory, unrelated_memory],
        query="考试怎么样",
        limit=3,
        now=now,
    )

    assert [item["id"] for item in ranked][:2] == ["recent", "old"]
    assert (
        ranked[0]["retrieval_score_parts"]["importance"]
        > ranked[2]["retrieval_score_parts"]["importance"]
    )
    assert "retrieval_score" in ranked[0]


def test_rank_memory_candidates_penalizes_sensitive_memory_before_policy_filter():
    now = datetime(2026, 6, 12, 12, tzinfo=UTC)
    sensitive = {
        "id": "sensitive",
        "memory_layer": "EPISODIC",
        "memory_table": "episodic_memories",
        "content": "用户说自己很焦虑",
        "importance_score": 7,
        "confidence_score": 0.9,
        "retrieval_weight": 1.0,
        "timestamp": now.isoformat(),
        "sensitivity_level": "MEDIUM",
    }
    safe = {
        "id": "safe",
        "memory_layer": "RELATIONAL",
        "memory_table": "relational_memories",
        "content": "用户疲惫时更适合低打扰陪伴",
        "importance_score": 7,
        "confidence_score": 0.9,
        "retrieval_weight": 1.0,
        "timestamp": now.isoformat(),
        "sensitivity_level": "LOW",
    }

    ranked = rank_memory_candidates(
        [sensitive, safe],
        query="用户现在有点累，怎么陪伴",
        context={"relationship_stage": "FAMILIAR"},
        limit=2,
        now=now,
    )

    assert ranked[0]["id"] == "safe"
    assert ranked[1]["retrieval_score_parts"]["sensitivity_penalty"] > 0
