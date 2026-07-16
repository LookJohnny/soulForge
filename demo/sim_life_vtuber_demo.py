"""Record a Sims-like three-agent SoulForge physical AI demo.

The demo downloads three CC0 VRM avatars from Open Source Avatars, preserves
their asset metadata, then drives three MuJoCo proxy bodies through a shared
living-space schedule. The rendered video includes a game-style UI overlay:
clock, agent portraits, need bars, speech bubbles, action queues, and
plumbob-like status diamonds.

Example:
  python demo/sim_life_vtuber_demo.py --duration-minutes 30
  python demo/sim_life_vtuber_demo.py --duration-minutes 0.2 --record-fps 4
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.legacy.action_units import DEFAULT_ACTION_TEMPLATES, sample_pose
from engine.legacy.vtuber_model import load_vtuber_model


PROJECTS_URL = "https://raw.githubusercontent.com/ToxSam/open-source-avatars/main/data/projects.json"
AVATARS_URL = "https://raw.githubusercontent.com/ToxSam/open-source-avatars/main/data/avatars/100avatars-r1.json"
SELECTED_AVATARS = ("Lydia", "Robert", "Polybot")


@dataclass(frozen=True)
class DownloadedAsset:
    avatar_name: str
    model_path: Path
    thumbnail_path: Path
    license: str
    source_url: str
    thumbnail_url: str
    project_id: str


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    display_name: str
    avatar_name: str
    role: str
    body_rgba: tuple[float, float, float, float]
    accent_rgba: tuple[float, float, float, float]
    phase: float
    pace: float


@dataclass(frozen=True)
class Activity:
    start_s: float
    end_s: float
    label: str
    target: tuple[float, float]
    template_id: str
    bubble: str
    queue: tuple[str, ...]
    mood: str


@dataclass(frozen=True)
class AgentFrame:
    x: float
    y: float
    heading: float
    pose_deg: dict[str, float]
    activity: Activity
    needs: dict[str, float]


AGENT_SPECS = (
    AgentSpec(
        agent_id="nova",
        display_name="Lydia",
        avatar_name="Lydia",
        role="female creative lead",
        body_rgba=(0.72, 0.32, 0.88, 1.0),
        accent_rgba=(1.00, 0.72, 0.25, 1.0),
        phase=0.0,
        pace=1.08,
    ),
    AgentSpec(
        agent_id="mira",
        display_name="Robert",
        avatar_name="Robert",
        role="male calm neighbor",
        body_rgba=(0.26, 0.58, 0.92, 1.0),
        accent_rgba=(0.38, 0.95, 0.78, 1.0),
        phase=1.7,
        pace=0.94,
    ),
    AgentSpec(
        agent_id="kite",
        display_name="Polybot",
        avatar_name="Polybot",
        role="robot tinkerer",
        body_rgba=(0.24, 0.82, 0.70, 1.0),
        accent_rgba=(0.95, 0.38, 0.95, 1.0),
        phase=3.2,
        pace=0.86,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-minutes", type=float, default=30.0)
    parser.add_argument("--record-fps", type=float, default=6.0)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--out", type=Path, default=Path("outputs/mujoco/sim_life_30min.mp4"))
    parser.add_argument("--mjcf-out", type=Path, default=Path("outputs/mujoco/sim_life_house.xml"))
    parser.add_argument("--asset-dir", type=Path, default=Path("assets/vtubers/open_source_avatars"))
    parser.add_argument("--no-download", action="store_true", help="Use already-downloaded assets only.")
    parser.add_argument("--metadata-out", type=Path, default=Path("outputs/mujoco/sim_life_assets.json"))
    return parser.parse_args()


def fetch_vtuber_assets(asset_dir: Path, *, allow_download: bool = True) -> list[DownloadedAsset]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = asset_dir / "asset_manifest.json"

    if manifest_path.exists() and not allow_download:
        return _load_downloaded_manifest(manifest_path)

    if not allow_download and not manifest_path.exists():
        raise FileNotFoundError(f"No asset manifest found: {manifest_path}")

    catalog = _fetch_json(AVATARS_URL)
    projects = {item["id"]: item for item in _fetch_json(PROJECTS_URL)}
    selected = select_avatar_records(catalog, SELECTED_AVATARS)
    downloaded: list[DownloadedAsset] = []

    for record in selected:
        name = record["name"]
        slug = _slug(name)
        model_path = asset_dir / f"{slug}.vrm"
        thumbnail_path = asset_dir / f"{slug}_thumbnail.gif"

        _download_if_missing(record["model_file_url"], model_path)
        _download_if_missing(record["thumbnail_url"], thumbnail_path)

        project = projects.get(record["project_id"], {})
        downloaded.append(
            DownloadedAsset(
                avatar_name=name,
                model_path=model_path,
                thumbnail_path=thumbnail_path,
                license=str(project.get("license") or "unknown"),
                source_url=record["model_file_url"],
                thumbnail_url=record["thumbnail_url"],
                project_id=record["project_id"],
            )
        )

    manifest_path.write_text(
        json.dumps([_asset_to_json(asset) for asset in downloaded], indent=2),
        encoding="utf-8",
    )
    return downloaded


def select_avatar_records(catalog: list[dict[str, Any]], names: tuple[str, ...]) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): item for item in catalog}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise KeyError(f"Missing avatar records: {missing}")
    return [by_name[name] for name in names]


def build_sim_life_mjcf(agent_specs: tuple[AgentSpec, ...] = AGENT_SPECS) -> str:
    materials = [
        f'<material name="{spec.agent_id}_body" rgba="{_rgba(spec.body_rgba)}"/>'
        f'\n    <material name="{spec.agent_id}_accent" rgba="{_rgba(spec.accent_rgba)}"/>'
        for spec in agent_specs
    ]
    agents = [_agent_mjcf(spec) for spec in agent_specs]
    return f"""
<mujoco model="soulforge_sim_life_house">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.01" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="1280" offheight="720"/>
    <headlight diffuse="0.72 0.70 0.66" ambient="0.28 0.30 0.34" specular="0.18 0.18 0.18"/>
    <rgba haze="0.90 0.94 0.98 1"/>
  </visual>
  <asset>
    <material name="floor_mat" rgba="0.78 0.76 0.70 1"/>
    <material name="wall_mat" rgba="0.82 0.86 0.88 1"/>
    <material name="wood_mat" rgba="0.46 0.31 0.20 1"/>
    <material name="sofa_mat" rgba="0.25 0.36 0.40 1"/>
    <material name="rug_mat" rgba="0.86 0.38 0.25 1"/>
    <material name="eye_mat" rgba="0.02 0.025 0.03 1"/>
    <material name="skin_mat" rgba="0.96 0.88 0.78 1"/>
    {' '.join(materials)}
  </asset>
  <worldbody>
    <light name="window_key" pos="-2.8 -3.2 4.2" dir="0.8 1 -1.2" directional="true"/>
    <light name="ceiling_fill" pos="1.8 1.6 3.0" dir="-0.4 -0.2 -1" directional="true"/>
    <geom name="floor" type="plane" pos="0 0 0" size="3.0 2.5 0.02" material="floor_mat"/>
    <geom name="back_wall" type="box" pos="0 1.62 0.75" size="3.0 0.04 0.75" material="wall_mat"/>
    <geom name="left_wall" type="box" pos="-2.22 0 0.75" size="0.04 1.65 0.75" material="wall_mat"/>
    <geom name="right_low_wall" type="box" pos="2.22 0.52 0.75" size="0.04 1.10 0.75" material="wall_mat"/>
    <geom name="rug" type="box" pos="0.24 -0.22 0.012" size="1.18 0.72 0.012" material="rug_mat"/>
    <geom name="sofa_base" type="box" pos="1.10 0.98 0.18" size="0.58 0.20 0.18" material="sofa_mat"/>
    <geom name="sofa_back" type="box" pos="1.10 1.22 0.42" size="0.62 0.06 0.28" material="sofa_mat"/>
    <geom name="coffee_table" type="box" pos="0.62 0.25 0.16" size="0.38 0.22 0.06" material="wood_mat"/>
    <geom name="desk" type="box" pos="-1.30 0.96 0.28" size="0.45 0.22 0.08" material="wood_mat"/>
    <geom name="desk_leg_l" type="box" pos="-1.62 0.80 0.14" size="0.035 0.035 0.14" material="wood_mat"/>
    <geom name="desk_leg_r" type="box" pos="-0.98 0.80 0.14" size="0.035 0.035 0.14" material="wood_mat"/>
    <geom name="kitchen_counter" type="box" pos="-1.42 -1.02 0.36" size="0.52 0.18 0.18" material="wood_mat"/>
    <geom name="bed" type="box" pos="1.42 -1.10 0.17" size="0.58 0.34 0.15" material="sofa_mat"/>
    <geom name="plant_pot" type="cylinder" pos="-1.92 1.22 0.14" size="0.11 0.14" material="wood_mat"/>
    <geom name="plant_top" type="ellipsoid" pos="-1.92 1.22 0.42" size="0.19 0.19 0.24" rgba="0.22 0.56 0.34 1"/>
    {' '.join(agents)}
  </worldbody>
</mujoco>
""".strip()


class SimLifePlanner:
    def __init__(self, duration_s: float):
        self.duration_s = max(duration_s, 1.0)
        self.schedules = {
            "nova": self._scale_schedule(
                [
                    (0.00, 0.08, "Wake stretch", (1.36, -1.00), "daily_stretch", "New day, new moves."),
                    (0.08, 0.20, "Breakfast chat", (-1.16, -0.82), "greeting_wave", "Kitchen sync?"),
                    (0.20, 0.36, "Practice dance", (-0.30, -0.22), "happy_wiggle", "Beat feels good."),
                    (0.36, 0.50, "Check on Mira", (0.58, 0.22), "look_at_user", "How is the plan?"),
                    (0.50, 0.68, "Group hangout", (0.95, 0.62), "listening_nod", "I am listening."),
                    (0.68, 0.84, "Room loop", (-0.18, 0.50), "curious_scan", "Tiny patrol."),
                    (0.84, 1.00, "Wind down", (1.16, 0.86), "sleep_breathing", "Soft ending."),
                ]
            ),
            "mira": self._scale_schedule(
                [
                    (0.00, 0.10, "Morning check", (1.70, -0.94), "thinking_idle", "Let's make today gentle."),
                    (0.10, 0.24, "Make breakfast", (-1.52, -0.98), "daily_stretch", "Breakfast is ready."),
                    (0.24, 0.42, "Sketch plan", (-1.28, 0.74), "thinking_idle", "Notes first."),
                    (0.42, 0.56, "Talk with Nova", (0.32, 0.18), "listening_nod", "Good idea."),
                    (0.56, 0.72, "Care check", (0.92, 0.92), "look_at_user", "Everyone okay?"),
                    (0.72, 0.88, "Read quietly", (-1.28, 0.92), "micro_nod", "Almost done."),
                    (0.88, 1.00, "Sofa recap", (0.62, 0.88), "sleep_breathing", "Cozy enough."),
                ]
            ),
            "kite": self._scale_schedule(
                [
                    (0.00, 0.12, "Boot up", (-1.10, 0.95), "curious_scan", "Systems online."),
                    (0.12, 0.26, "Coffee observe", (-0.92, -0.68), "look_at_user", "I found a pattern."),
                    (0.26, 0.44, "Tinker desk", (-1.52, 0.90), "thinking_idle", "Testing a small loop."),
                    (0.44, 0.60, "Join talk", (0.10, 0.50), "micro_nod", "That tracks."),
                    (0.60, 0.76, "Debug walk", (-0.62, 0.02), "curious_scan", "Scanning the room."),
                    (0.76, 0.90, "Share result", (0.42, 0.70), "greeting_wave", "Patch accepted."),
                    (0.90, 1.00, "Quiet idle", (-1.10, 0.82), "sleep_breathing", "Low-power mode."),
                ]
            ),
        }

    def frame_for(self, spec: AgentSpec, t: float, all_positions: dict[str, tuple[float, float]] | None = None) -> AgentFrame:
        schedule = self.schedules[spec.agent_id]
        idx = self._activity_index(schedule, t)
        activity = schedule[idx]
        previous = schedule[max(0, idx - 1)]
        x, y, moving = self._position_for(spec, previous, activity, t)
        heading = self._heading_for(spec, x, y, activity, moving, all_positions or {})
        pose = self._pose_for(spec, activity, t, moving)
        needs = self._needs_for(spec, activity, t)
        return AgentFrame(x=x, y=y, heading=heading, pose_deg=pose, activity=activity, needs=needs)

    def positions_at(self, t: float) -> dict[str, tuple[float, float]]:
        positions: dict[str, tuple[float, float]] = {}
        for spec in AGENT_SPECS:
            schedule = self.schedules[spec.agent_id]
            idx = self._activity_index(schedule, t)
            previous = schedule[max(0, idx - 1)]
            activity = schedule[idx]
            x, y, _ = self._position_for(spec, previous, activity, t)
            positions[spec.agent_id] = (x, y)
        return positions

    def _scale_schedule(self, items: list[tuple[float, float, str, tuple[float, float], str, str]]) -> list[Activity]:
        activities: list[Activity] = []
        for start, end, label, target, template_id, bubble in items:
            activities.append(
                Activity(
                    start_s=start * self.duration_s,
                    end_s=end * self.duration_s,
                    label=label,
                    target=target,
                    template_id=template_id,
                    bubble=bubble,
                    queue=(label, "Autonomy", "Observe"),
                    mood=_mood_for_template(template_id),
                )
            )
        return activities

    def _activity_index(self, schedule: list[Activity], t: float) -> int:
        for idx, activity in enumerate(schedule):
            if activity.start_s <= t < activity.end_s:
                return idx
        return len(schedule) - 1

    def _position_for(self, spec: AgentSpec, previous: Activity, activity: Activity, t: float) -> tuple[float, float, bool]:
        transition_s = min(42.0, max(8.0, (activity.end_s - activity.start_s) * 0.24))
        if activity.start_s <= t < activity.start_s + transition_s:
            alpha = smoothstep((t - activity.start_s) / transition_s)
            x = previous.target[0] + (activity.target[0] - previous.target[0]) * alpha
            y = previous.target[1] + (activity.target[1] - previous.target[1]) * alpha
            moving = _distance(previous.target, activity.target) > 0.18
        else:
            x, y = activity.target
            moving = False

        drift = 0.035 + 0.012 * math.sin(spec.phase + t * 0.017)
        x += math.sin(t * 0.033 + spec.phase) * drift
        y += math.cos(t * 0.027 + spec.phase * 0.7) * drift
        return x, y, moving

    def _heading_for(
        self,
        spec: AgentSpec,
        x: float,
        y: float,
        activity: Activity,
        moving: bool,
        all_positions: dict[str, tuple[float, float]],
    ) -> float:
        if moving:
            tx, ty = activity.target
        elif "Talk" in activity.label or "Group" in activity.label or "chat" in activity.label.lower():
            others = [pos for agent_id, pos in all_positions.items() if agent_id != spec.agent_id]
            tx = sum(pos[0] for pos in others) / max(len(others), 1)
            ty = sum(pos[1] for pos in others) / max(len(others), 1)
        elif "Sofa" in activity.label or "hangout" in activity.label.lower():
            tx, ty = 0.55, 0.35
        else:
            tx, ty = 0.0, -0.18

        dx, dy = tx - x, ty - y
        if abs(dx) + abs(dy) < 0.01:
            base = 0.0
        else:
            base = math.atan2(dx, -dy)
        return base + math.radians(2.5 * math.sin(tiny_phase(spec, 0.021)))

    def _pose_for(self, spec: AgentSpec, activity: Activity, t: float, moving: bool) -> dict[str, float]:
        template = DEFAULT_ACTION_TEMPLATES[activity.template_id]
        duration = max(template.keyframes[-1][0], 0.5)
        phase_t = ((t * spec.pace) + spec.phase) % duration
        pose = sample_pose(template.keyframes, phase_t)

        gait = math.sin((t * 2.2 + spec.phase) * math.pi * 2.0)
        breath = math.sin(t * 1.22 + spec.phase)
        saccade = math.sin(t * 0.47 + spec.phase * 1.9)

        pose["body_roll"] = pose.get("body_roll", 0.0) + 1.2 * breath + 0.6 * math.sin(t * 0.73 + spec.phase)
        pose["head_yaw"] = pose.get("head_yaw", 0.0) + 2.8 * saccade
        pose["head_pitch"] = pose.get("head_pitch", 0.0) + 1.4 * math.sin(t * 0.39 + spec.phase)
        pose["head_roll"] = pose.get("head_roll", 0.0) + 1.8 * math.sin(t * 0.31 + spec.phase)

        if moving:
            pose["left_arm_pitch"] = pose.get("left_arm_pitch", 0.0) + 20.0 * gait
            pose["right_arm_pitch"] = pose.get("right_arm_pitch", 0.0) - 20.0 * gait
            pose["body_yaw"] = pose.get("body_yaw", 0.0) + 3.5 * math.sin(t * 3.8 + spec.phase)
            pose["head_pitch"] += 2.0 * abs(gait)

        return {
            "body_yaw": clamp(pose.get("body_yaw", 0.0), -16.0, 16.0),
            "body_roll": clamp(pose.get("body_roll", 0.0), -12.0, 12.0),
            "left_arm_pitch": clamp(pose.get("left_arm_pitch", 0.0), -18.0, 72.0),
            "right_arm_pitch": clamp(pose.get("right_arm_pitch", 0.0), -18.0, 72.0),
            "head_yaw": clamp(pose.get("head_yaw", 0.0), -34.0, 34.0),
            "head_pitch": clamp(pose.get("head_pitch", 0.0), -20.0, 22.0),
            "head_roll": clamp(pose.get("head_roll", 0.0), -14.0, 14.0),
        }

    def _needs_for(self, spec: AgentSpec, activity: Activity, t: float) -> dict[str, float]:
        progress = t / self.duration_s
        social = 0.46 + 0.28 * math.sin(progress * math.pi + spec.phase * 0.2)
        fun = 0.48 + 0.22 * math.sin(progress * math.pi * 1.6 + spec.phase)
        energy = 0.84 - 0.22 * progress + 0.04 * math.sin(t * 0.01 + spec.phase)
        focus = 0.58 + 0.20 * math.sin(progress * math.pi * 2.1 + spec.phase)

        if activity.template_id in {"greeting_wave", "listening_nod", "micro_nod"}:
            social += 0.22
        if activity.template_id == "happy_wiggle":
            fun += 0.30
        if activity.template_id in {"thinking_idle", "curious_scan"}:
            focus += 0.20
        if activity.template_id == "sleep_breathing":
            energy += 0.10

        return {
            "Energy": clamp01(energy),
            "Social": clamp01(social),
            "Fun": clamp01(fun),
            "Focus": clamp01(focus),
        }


def render_sim_life_video(
    out_path: Path,
    *,
    duration_s: float,
    record_fps: float,
    width: int,
    height: int,
    assets: list[DownloadedAsset],
    mjcf_out: Path | None = None,
) -> dict[str, Any]:
    try:
        import imageio.v2 as imageio
        import mujoco
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Missing demo dependencies. Run: uv sync --all-packages --all-groups") from exc

    mjcf = build_sim_life_mjcf()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if mjcf_out is not None:
        mjcf_out.parent.mkdir(parents=True, exist_ok=True)
        mjcf_out.write_text(mjcf + "\n", encoding="utf-8")

    model = mujoco.MjModel.from_xml_string(mjcf)
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height=height, width=width)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = [0.0, 0.10, 0.58]
    camera.distance = 4.35
    camera.azimuth = 138
    camera.elevation = -34

    qpos = {
        model.joint(i).name: model.joint(i).qposadr[0]
        for i in range(model.njnt)
        if model.joint(i).name
    }
    asset_by_name = {asset.avatar_name: asset for asset in assets}
    portraits = {
        spec.agent_id: load_portrait(asset_by_name.get(spec.avatar_name), 64)
        for spec in AGENT_SPECS
    }
    planner = SimLifePlanner(duration_s)
    frames = max(1, int(round(duration_s * record_fps)))
    writer = imageio.get_writer(
        out_path,
        fps=record_fps,
        codec="libx264",
        quality=8,
        macro_block_size=1,
    )

    try:
        for frame_idx in range(frames):
            t = frame_idx / record_fps
            positions = planner.positions_at(t)
            frames_by_agent: dict[str, AgentFrame] = {}
            for spec in AGENT_SPECS:
                agent_frame = planner.frame_for(spec, t, positions)
                frames_by_agent[spec.agent_id] = agent_frame
                apply_agent_frame(data, qpos, spec, agent_frame)

            mujoco.mj_forward(model, data)
            renderer.update_scene(data, camera=camera)
            rgb = renderer.render()
            image = Image.fromarray(rgb).convert("RGBA")
            image = overlay_game_ui(
                image,
                t=t,
                duration_s=duration_s,
                frames_by_agent=frames_by_agent,
                portraits=portraits,
                assets=asset_by_name,
            )
            writer.append_data(np.asarray(image.convert("RGB")))
    finally:
        writer.close()
        renderer.close()

    return {
        "out": str(out_path),
        "duration_s": duration_s,
        "record_fps": record_fps,
        "frames": frames,
        "agents": [spec.display_name for spec in AGENT_SPECS],
        "assets": [_asset_to_json(asset) for asset in assets],
    }


def apply_agent_frame(data: Any, qpos: dict[str, int], spec: AgentSpec, frame: AgentFrame) -> None:
    prefix = spec.agent_id
    values = {
        f"{prefix}_x": frame.x,
        f"{prefix}_y": frame.y,
        f"{prefix}_heading": frame.heading,
        f"{prefix}_body_yaw": math.radians(frame.pose_deg["body_yaw"]),
        f"{prefix}_body_roll": math.radians(frame.pose_deg["body_roll"]),
        f"{prefix}_left_arm_pitch": math.radians(frame.pose_deg["left_arm_pitch"]),
        f"{prefix}_right_arm_pitch": math.radians(frame.pose_deg["right_arm_pitch"]),
        f"{prefix}_head_yaw": math.radians(frame.pose_deg["head_yaw"]),
        f"{prefix}_head_pitch": math.radians(frame.pose_deg["head_pitch"]),
        f"{prefix}_head_roll": math.radians(frame.pose_deg["head_roll"]),
    }
    for name, value in values.items():
        if name in qpos:
            data.qpos[qpos[name]] = value


def overlay_game_ui(
    image: Any,
    *,
    t: float,
    duration_s: float,
    frames_by_agent: dict[str, AgentFrame],
    portraits: dict[str, Any],
    assets: dict[str, DownloadedAsset],
) -> Any:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    font_xs = load_font(12)
    font_sm = load_font(15)
    font_md = load_font(18)
    font_lg = load_font(24)

    draw.rounded_rectangle((18, 16, 344, 86), radius=12, fill=(16, 21, 30, 196), outline=(255, 255, 255, 42))
    draw.text((34, 28), "SoulForge SimLife", font=font_lg, fill=(246, 248, 255, 255))
    draw.text((34, 58), "3 autonomous VTuber agents", font=font_sm, fill=(204, 214, 230, 255))

    sim_minutes = int((7 * 60) + (t / max(duration_s, 1.0)) * 16 * 60)
    hour = (sim_minutes // 60) % 24
    minute = sim_minutes % 60
    clock = f"Day 1  {hour:02d}:{minute:02d}"
    box_w = 190
    draw.rounded_rectangle((width - box_w - 18, 16, width - 18, 72), radius=12, fill=(16, 21, 30, 196), outline=(255, 255, 255, 42))
    draw.text((width - box_w, 32), clock, font=font_md, fill=(246, 248, 255, 255))

    if height >= 420:
        draw.rounded_rectangle((18, 96, 286, 148), radius=12, fill=(16, 21, 30, 172), outline=(255, 255, 255, 36))
        draw.text((34, 108), "Downloaded VRM source:", font=font_xs, fill=(179, 190, 210, 255))
        draw.text((34, 126), "Open Source Avatars / CC0", font=font_sm, fill=(244, 234, 178, 255))

    card_w = (width - 48) // 3
    bottom_y = height - 132
    for idx, spec in enumerate(AGENT_SPECS):
        frame = frames_by_agent[spec.agent_id]
        x0 = 18 + idx * (card_w + 6)
        x1 = x0 + card_w
        draw.rounded_rectangle((x0, bottom_y, x1, height - 14), radius=12, fill=(13, 17, 25, 210), outline=(255, 255, 255, 38))
        portrait = portraits.get(spec.agent_id)
        if portrait is not None:
            image.alpha_composite(portrait, (x0 + 12, bottom_y + 14))
        draw.text((x0 + 86, bottom_y + 14), spec.display_name, font=font_md, fill=(246, 248, 255, 255))
        draw.text((x0 + 86, bottom_y + 38), spec.role, font=font_xs, fill=(172, 184, 202, 255))
        draw.text((x0 + 86, bottom_y + 56), frame.activity.label, font=font_sm, fill=(244, 234, 178, 255))

        bar_x = x0 + 12
        bar_y = bottom_y + 86
        for b_idx, (label, value) in enumerate(frame.needs.items()):
            bx = bar_x + (b_idx % 2) * (card_w // 2 - 6)
            by = bar_y + (b_idx // 2) * 18
            draw.text((bx, by - 1), label, font=font_xs, fill=(184, 195, 212, 255))
            draw.rounded_rectangle((bx + 48, by + 3, bx + 118, by + 11), radius=4, fill=(44, 52, 66, 255))
            fill = _need_color(value)
            draw.rounded_rectangle((bx + 48, by + 3, bx + 48 + int(70 * value), by + 11), radius=4, fill=fill)

        sx, sy = world_to_screen(frame.x, frame.y, 1.25, width, height)
        draw_plumbob(draw, sx, sy - 26, _need_color(sum(frame.needs.values()) / len(frame.needs)))
        if should_show_bubble(t, idx):
            bubble_x = clamp(sx + 12, 8, width - 230)
            bubble_y = clamp(sy - 76, 82, max(84, bottom_y - 48))
            draw_speech_bubble(draw, bubble_x, bubble_y, frame.activity.bubble, font_sm)

    progress = t / max(duration_s, 1.0)
    progress_w = min(360, width - 72)
    progress_x = width // 2 - progress_w // 2
    progress_y = max(84, bottom_y - 18)
    draw.rounded_rectangle((progress_x, progress_y, progress_x + progress_w, progress_y + 12), radius=6, fill=(20, 26, 35, 210))
    draw.rounded_rectangle((progress_x, progress_y, progress_x + int(progress_w * progress), progress_y + 12), radius=6, fill=(96, 204, 144, 240))
    return image


def load_portrait(asset: DownloadedAsset | None, size: int) -> Any:
    from PIL import Image, ImageDraw, ImageOps

    if asset is None:
        return None
    try:
        with Image.open(asset.thumbnail_path) as img:
            img.seek(0)
            img = img.convert("RGBA")
            img = ImageOps.fit(img, (size, size))
    except Exception:
        img = Image.new("RGBA", (size, size), (30, 38, 52, 255))
        draw = ImageDraw.Draw(img)
        draw.text((size // 3, size // 3), asset.avatar_name[:1], fill=(255, 255, 255, 255))

    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, size, size), radius=14, fill=255)
    img.putalpha(mask)
    return img


def draw_plumbob(draw: Any, x: float, y: float, color: tuple[int, int, int, int]) -> None:
    top = (x, y - 18)
    right = (x + 12, y)
    bottom = (x, y + 24)
    left = (x - 12, y)
    draw.polygon([top, right, bottom, left], fill=color, outline=(255, 255, 255, 170))
    draw.line([top, bottom], fill=(255, 255, 255, 70), width=1)


def draw_speech_bubble(draw: Any, x: float, y: float, text: str, font: Any) -> None:
    text = text[:28]
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 28
    h = 34
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=(255, 255, 255, 226), outline=(0, 0, 0, 45))
    draw.polygon([(x + 18, y + h), (x + 28, y + h), (x + 20, y + h + 10)], fill=(255, 255, 255, 226))
    draw.text((x + 14, y + 9), text, font=font, fill=(30, 35, 45, 255))


def should_show_bubble(t: float, idx: int) -> bool:
    window = (t + idx * 13.0) % 72.0
    return 5.0 < window < 22.0


def world_to_screen(x: float, y: float, z: float, width: int, height: int) -> tuple[float, float]:
    return (
        width * 0.50 + (x - y) * width * 0.105,
        height * 0.56 + (x + y) * height * 0.034 - z * height * 0.145,
    )


def load_font(size: int) -> Any:
    from PIL import ImageFont

    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/Library/Fonts/Arial.ttf",
    )
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _agent_mjcf(spec: AgentSpec) -> str:
    prefix = spec.agent_id
    body_mat = f"{prefix}_body"
    accent_mat = f"{prefix}_accent"
    x_offset = {"nova": -0.18, "mira": 0.18, "kite": 0.0}.get(prefix, 0.0)
    return f"""
    <body name="{prefix}_root" pos="{x_offset} 0 0.52">
      <inertial pos="0 0 0" mass="0.01" diaginertia="0.0001 0.0001 0.0001"/>
      <joint name="{prefix}_x" type="slide" axis="1 0 0" range="-2.0 2.0" damping="10"/>
      <joint name="{prefix}_y" type="slide" axis="0 1 0" range="-1.35 1.35" damping="10"/>
      <joint name="{prefix}_heading" type="hinge" axis="0 0 1" range="-3.14159 3.14159" damping="5"/>
      <body name="{prefix}_torso">
        <joint name="{prefix}_body_yaw" type="hinge" axis="0 0 1" range="-0.35 0.35" damping="4"/>
        <joint name="{prefix}_body_roll" type="hinge" axis="0 1 0" range="-0.26 0.26" damping="4"/>
        <geom name="{prefix}_body_geom" type="capsule" fromto="0 0 -0.25 0 0 0.25" size="0.15" material="{body_mat}"/>
        <geom name="{prefix}_chest" type="ellipsoid" pos="0 -0.02 0.08" size="0.18 0.12 0.20" material="{body_mat}"/>
        <body name="{prefix}_left_arm" pos="-0.18 0 0.15">
          <joint name="{prefix}_left_arm_pitch" type="hinge" axis="1 0 0" range="-0.35 1.40" damping="3"/>
          <geom type="capsule" fromto="0 0 0 0 0 -0.28" size="0.035" material="{body_mat}"/>
        </body>
        <body name="{prefix}_right_arm" pos="0.18 0 0.15">
          <joint name="{prefix}_right_arm_pitch" type="hinge" axis="1 0 0" range="-0.35 1.40" damping="3"/>
          <geom type="capsule" fromto="0 0 0 0 0 -0.28" size="0.035" material="{body_mat}"/>
        </body>
        <body name="{prefix}_head_yaw_link" pos="0 0 0.33">
          <inertial pos="0 0 0" mass="0.01" diaginertia="0.0001 0.0001 0.0001"/>
          <joint name="{prefix}_head_yaw" type="hinge" axis="0 0 1" range="-0.65 0.65" damping="4"/>
          <body name="{prefix}_head_pitch_link">
            <inertial pos="0 0 0" mass="0.01" diaginertia="0.0001 0.0001 0.0001"/>
            <joint name="{prefix}_head_pitch" type="hinge" axis="1 0 0" range="-0.42 0.42" damping="4"/>
            <body name="{prefix}_head_roll_link">
              <joint name="{prefix}_head_roll" type="hinge" axis="0 1 0" range="-0.28 0.28" damping="3"/>
              <geom name="{prefix}_head" type="ellipsoid" pos="0 -0.02 0.12" size="0.16 0.13 0.16" material="skin_mat"/>
              <geom name="{prefix}_left_eye" type="sphere" pos="-0.052 -0.132 0.142" size="0.020" material="eye_mat"/>
              <geom name="{prefix}_right_eye" type="sphere" pos="0.052 -0.132 0.142" size="0.020" material="eye_mat"/>
              <geom name="{prefix}_hair" type="capsule" fromto="-0.09 -0.02 0.245 0.09 -0.02 0.245" size="0.026" material="{accent_mat}"/>
              <geom name="{prefix}_badge" type="sphere" pos="0 -0.148 0.052" size="0.018" material="{accent_mat}"/>
            </body>
          </body>
        </body>
      </body>
    </body>
    """


def _fetch_json(url: str) -> Any:
    return json.loads(_download_bytes(url, timeout=45).decode("utf-8"))


def _download_if_missing(url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent) as tmp:
        tmp_path = Path(tmp.name)
    try:
        tmp_path.write_bytes(_download_bytes(url, timeout=120))
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _download_bytes(url: str, *, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SoulForge-SimLife-Demo/1.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            time.sleep(0.75 * (attempt + 1))

    curl = subprocess.run(
        [
            "curl",
            "-L",
            "--retry",
            "3",
            "--connect-timeout",
            "20",
            "--max-time",
            str(timeout),
            "-sSf",
            url,
        ],
        check=False,
        capture_output=True,
    )
    if curl.returncode == 0:
        return curl.stdout
    raise RuntimeError(
        f"Download failed for {url}: {last_error}; curl={curl.stderr.decode(errors='ignore')[:200]}"
    )


def _load_downloaded_manifest(path: Path) -> list[DownloadedAsset]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assets = [
        DownloadedAsset(
            avatar_name=item["avatar_name"],
            model_path=Path(item["model_path"]),
            thumbnail_path=Path(item["thumbnail_path"]),
            license=item["license"],
            source_url=item["source_url"],
            thumbnail_url=item["thumbnail_url"],
            project_id=item["project_id"],
        )
        for item in data
    ]
    for asset in assets:
        if not asset.model_path.exists() or not asset.thumbnail_path.exists():
            raise FileNotFoundError(f"Downloaded asset missing for {asset.avatar_name}")
    return assets


def _asset_to_json(asset: DownloadedAsset) -> dict[str, str]:
    return {
        "avatar_name": asset.avatar_name,
        "model_path": str(asset.model_path),
        "thumbnail_path": str(asset.thumbnail_path),
        "license": asset.license,
        "source_url": asset.source_url,
        "thumbnail_url": asset.thumbnail_url,
        "project_id": asset.project_id,
    }


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _rgba(value: tuple[float, float, float, float]) -> str:
    return " ".join(f"{v:.3f}" for v in value)


def _mood_for_template(template_id: str) -> str:
    return {
        "happy_wiggle": "playful",
        "greeting_wave": "social",
        "listening_nod": "attentive",
        "daily_stretch": "active",
        "sleep_breathing": "calm",
        "thinking_idle": "focused",
        "curious_scan": "curious",
        "micro_nod": "attentive",
    }.get(template_id, "calm")


def _need_color(value: float) -> tuple[int, int, int, int]:
    if value > 0.66:
        return (96, 214, 142, 238)
    if value > 0.38:
        return (238, 202, 88, 238)
    return (238, 96, 96, 238)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def smoothstep(value: float) -> float:
    x = clamp(value, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def clamp01(value: float) -> float:
    return clamp(value, 0.0, 1.0)


def tiny_phase(spec: AgentSpec, rate: float) -> float:
    return spec.phase * 1.37 + rate * 100.0


def main() -> None:
    args = parse_args()
    assets = fetch_vtuber_assets(args.asset_dir, allow_download=not args.no_download)

    for asset in assets:
        loaded = load_vtuber_model(asset.model_path)
        print(f"asset: {asset.avatar_name} mode={loaded.mode} license={asset.license} path={asset.model_path}")

    report = render_sim_life_video(
        args.out,
        duration_s=args.duration_minutes * 60.0,
        record_fps=args.record_fps,
        width=args.width,
        height=args.height,
        assets=assets,
        mjcf_out=args.mjcf_out,
    )
    args.metadata_out.parent.mkdir(parents=True, exist_ok=True)
    args.metadata_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("SoulForge SimLife demo recording complete")
    print(f"out: {args.out}")
    print(f"mjcf: {args.mjcf_out}")
    print(f"metadata: {args.metadata_out}")
    print(f"duration_s: {report['duration_s']}")
    print(f"record_fps: {report['record_fps']}")
    print(f"frames: {report['frames']}")


if __name__ == "__main__":
    main()
