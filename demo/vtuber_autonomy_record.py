"""Record long-horizon autonomous MuJoCo activity for any Vtuber asset.

Examples:
  python demo/vtuber_autonomy_record.py --model avatar.vrm
  python demo/vtuber_autonomy_record.py --model rig.xml --sim-hours 8 --record-fps 1

For non-MJCF render assets (VRM/GLB/Live2D), this uses the SoulForge proxy
physical rig so the full physical AI engine can still be accepted and recorded.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.legacy.daily_autonomy import DailyAutonomyPlanner
from engine.legacy.environment_events import EnvironmentEvent, ScriptedEnvironmentAdapter
from engine.legacy.mujoco_backend import MuJoCoVideoBackend
from engine.legacy.physical_ai_engine import PhysicalAIEngine
from engine.legacy.vtuber_model import load_vtuber_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=None, help="Vtuber model: MJCF XML, VRM, GLB, GLTF, Live2D model3.json, OBJ, STL, etc.")
    parser.add_argument("--out", type=Path, default=Path("outputs/mujoco/vtuber_8h_autonomy.mp4"))
    parser.add_argument("--mjcf-out", type=Path, default=Path("outputs/mujoco/vtuber_proxy.xml"))
    parser.add_argument("--sim-hours", type=float, default=8.0, help="Simulated autonomy duration.")
    parser.add_argument("--record-fps", type=float, default=1.0, help="Video FPS. 1fps yields a true 8-hour duration with one frame per simulated second.")
    parser.add_argument("--control-hz", type=int, default=10, help="Physical control update rate.")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--start-hour", type=float, default=7.0, help="Local day hour used for the 24h autonomy plan.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    loaded = load_vtuber_model(args.model)

    backend = MuJoCoVideoBackend(
        loaded.mjcf,
        args.out,
        record_fps=args.record_fps,
        width=args.width,
        height=args.height,
        mjcf_out=args.mjcf_out,
        camera={
            "lookat": [0.02, -0.05, 0.82],
            "distance": 1.65,
            "azimuth": 135,
            "elevation": -18,
        },
    )
    engine = PhysicalAIEngine(
        manifest=loaded.manifest,
        backend=backend,
        control_hz=args.control_hz,
    )

    sim_duration_s = args.sim_hours * 3600.0
    scripted_events = [
        EnvironmentEvent(
            t=hour * 3600.0 + 120.0,
            event_type="user_detected",
            payload={"source": "acceptance_schedule"},
        )
        for hour in range(max(1, int(args.sim_hours)))
    ]
    environment = ScriptedEnvironmentAdapter(scripted_events)
    planner = DailyAutonomyPlanner(
        {
            "model": str(loaded.source_path),
            "load_mode": loaded.mode,
        }
    )

    try:
        report = engine.run_daily_autonomy(
            sim_duration_s,
            planner=planner,
            environment=environment,
            start_minute_of_day=int(args.start_hour * 60) % 1440,
        )
    finally:
        engine.close()

    print("SoulForge Vtuber autonomy recording complete")
    print(f"model: {loaded.source_path}")
    print(f"load_mode: {loaded.mode}")
    print(f"description: {loaded.description}")
    print(f"out: {args.out}")
    print(f"mjcf: {args.mjcf_out}")
    print(f"sim_hours_requested: {args.sim_hours}")
    print(f"sim_duration_s: {round(report.duration_s, 2)}")
    print(f"record_fps: {args.record_fps}")
    print(f"frames_written: {backend.frames_written}")
    print(f"units_played: {report.units_played}")
    print(f"intents_submitted: {report.intents_submitted}")
    print(f"safety: {report.safety_status}")
    print(f"max_abs_deg: { {k: round(v, 2) for k, v in backend.max_abs_deg.items()} }")


if __name__ == "__main__":
    main()
