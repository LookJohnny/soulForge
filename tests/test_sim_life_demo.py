import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from demo.sim_life_vtuber_demo import (
    AGENT_SPECS,
    SELECTED_AVATARS,
    SimLifePlanner,
    build_sim_life_mjcf,
    select_avatar_records,
)


def test_sim_life_scene_contains_three_named_agents():
    mjcf = build_sim_life_mjcf()

    for spec in AGENT_SPECS:
        assert f'name="{spec.agent_id}_root"' in mjcf
        assert f'name="{spec.agent_id}_head_yaw"' in mjcf


def test_sim_life_planner_returns_distinct_nonstatic_agent_frames():
    planner = SimLifePlanner(duration_s=30 * 60)

    start_positions = planner.positions_at(0.0)
    later_positions = planner.positions_at(8 * 60)

    assert set(start_positions) == {spec.agent_id for spec in AGENT_SPECS}
    assert any(start_positions[key] != later_positions[key] for key in start_positions)

    frame = planner.frame_for(AGENT_SPECS[0], 8 * 60, later_positions)
    assert frame.activity.label
    assert frame.pose_deg["head_yaw"] != 0.0
    assert all(0.0 <= value <= 1.0 for value in frame.needs.values())


def test_select_avatar_records_finds_representative_assets():
    catalog = [
        {"name": "Lydia"},
        {"name": "Robert"},
        {"name": "Polybot"},
    ]

    selected = select_avatar_records(catalog, SELECTED_AVATARS)

    assert [item["name"] for item in selected] == list(SELECTED_AVATARS)
