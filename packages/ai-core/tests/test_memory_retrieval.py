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


def _mem(id_, content, layer="EPISODIC", **over):
    from datetime import UTC, datetime

    base = {
        "id": id_,
        "memory_layer": layer,
        "memory_table": f"{layer.lower()}_memories",
        "content": content,
        "importance_score": 5,
        "confidence_score": 0.8,
        "retrieval_weight": 0.6,
        "timestamp": datetime(2026, 8, 26, 10, tzinfo=UTC).isoformat(),
        "sensitivity_level": "LOW",
    }
    base.update(over)
    return base


def test_vector_similarity_overrides_lexical_relevance():
    from datetime import UTC, datetime

    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    # lexically unrelated wording but semantically close (vector_sim high)
    semantic = _mem("sem", "傍晚在沙滩看太阳落下去", vector_sim=0.91)
    lexical = _mem("lex", "海边日落海边日落", vector_sim=0.2)
    ranked = rank_memory_candidates([lexical, semantic], query="海边日落", limit=2, now=now)
    assert ranked[0]["id"] == "sem"
    assert ranked[0]["retrieval_score_parts"]["relevance_source"] == "vector"
    # rows without vector_sim still get lexical relevance
    mixed = rank_memory_candidates([_mem("a", "海边日落"), semantic], query="海边日落", now=now)
    assert {m["retrieval_score_parts"]["relevance_source"] for m in mixed} == {"vector", "lexical"}


def test_recall_cue_boosts_episodic_layer():
    from datetime import UTC, datetime

    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    ep = _mem("ep", "去过游乐园", layer="EPISODIC")
    prof = _mem("pf", "去过游乐园", layer="PROFILE", memory_table="profile_memories")
    plain = rank_memory_candidates([prof, ep], query="游乐园", now=now)
    recall = rank_memory_candidates([prof, ep], query="还记得游乐园吗", now=now)
    assert plain[0]["retrieval_score_parts"]["recall_boost"] == 0
    assert recall[0]["id"] == "ep" and recall[0]["retrieval_score_parts"]["recall_boost"] == 0.15


def test_build_memory_graph_vector_and_lexical_fallback():
    from ai_core.services.embeddings import FakeEmbedder
    from ai_core.services.memory import build_memory_graph

    emb = FakeEmbedder(64)
    texts = ["喜欢喝抹茶拿铁", "抹茶拿铁真好喝", "明天有一场重要考试"]
    vecs = emb.encode(texts)
    rows = [
        {"id": f"m{i}", "layer": "PROFILE", "content": t, "importance": 5, "embedding": v}
        for i, (t, v) in enumerate(zip(texts, vecs, strict=False))
    ]
    g = build_memory_graph(rows, threshold=0.3)
    assert len(g["nodes"]) == 3
    pairs = {(e["a"], e["b"]) for e in g["edges"]}
    assert ("m0", "m1") in pairs  # matcha ↔ matcha
    assert ("m0", "m2") not in pairs  # matcha ↔ exam
    # no embeddings → lexical fallback still connects the matcha pair
    for r in rows:
        r["embedding"] = None
    g2 = build_memory_graph(rows, threshold=0.6)
    assert any({e["a"], e["b"]} == {"m0", "m1"} for e in g2["edges"])


def test_extraction_prompt_formats_without_keyerror():
    # Regression: the JSON example in the prompt was an unescaped {…} → str.format
    # raised KeyError('"type"') on every turn, so no memory was ever extracted.
    from ai_core.services.memory import _EXTRACTION_PROMPT

    out = _EXTRACTION_PROMPT.format(user_input="我喜欢抹茶", ai_response="记住啦")
    assert '{"type": "PREFERENCE"' in out and "我喜欢抹茶" in out
