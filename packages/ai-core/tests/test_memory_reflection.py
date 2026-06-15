"""Tests for evidence-backed memory reflection proposals."""

from ai_core.services.memory import build_reflection_proposals
from ai_core.services.memory_policy import MemoryPolicyEngine


def test_build_reflection_proposals_keeps_evidence_refs():
    memories = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "content": "用户说自己今天很累，希望安静一点",
            "sensitivity_level": "LOW",
            "importance_score": 6,
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "content": "用户说不要空泛鼓励，先指出风险",
            "sensitivity_level": "LOW",
            "importance_score": 7,
        },
    ]

    proposals = build_reflection_proposals(memories, MemoryPolicyEngine())

    low_disturbance = next(p for p in proposals if p["rule_type"] == "interaction_rhythm")
    directness = next(p for p in proposals if p["rule_type"] == "reasoning_strategy")

    assert low_disturbance["target_layer"] == "private_state"
    assert low_disturbance["policy_action"] == "private_only"
    assert low_disturbance["evidence_refs"] == ["00000000-0000-0000-0000-000000000001"]
    assert "不要直说来自记忆" in low_disturbance["rule_content"]

    assert directness["target_layer"] == "relationship"
    assert directness["evidence_refs"] == ["00000000-0000-0000-0000-000000000002"]
    assert directness["status"] == "applied"


def test_build_reflection_proposals_requires_evidence():
    proposals = build_reflection_proposals(
        [
            {
                "id": "00000000-0000-0000-0000-000000000003",
                "content": "用户今天午饭吃了面条",
                "sensitivity_level": "LOW",
                "importance_score": 3,
            }
        ],
        MemoryPolicyEngine(),
    )

    assert proposals == []


def test_parasocial_boundary_reflection_is_pending_for_review():
    proposals = build_reflection_proposals(
        [
            {
                "id": "00000000-0000-0000-0000-000000000004",
                "content": "用户说你是我唯一的朋友",
                "sensitivity_level": "HIGH",
                "importance_score": 9,
            }
        ],
        MemoryPolicyEngine(),
    )

    assert len(proposals) == 1
    assert proposals[0]["rule_type"] == "safety_guardrail"
    assert proposals[0]["status"] == "pending_apply"
    assert proposals[0]["policy_action"] == "private_only"
