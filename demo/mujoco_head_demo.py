"""Record the SoulForge M0 soft-interrupt head demo with MuJoCo.

The demo builds a minimal 3-DOF animatronic head directly from MJCF, drives it
through the existing motion smoothing and safety layers, then records an MP4.
It is intentionally small: the goal is to prove the M0 loop before any real
servo is powered.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motion.smoother import MotionSmoother
from safety.safety_manager import SafetyManager


JOINTS = ("head_yaw", "head_pitch", "head_roll")
INTERRUPT_AT_S = 2.2
RECOVER_AT_S = 3.6


def build_head_mjcf() -> str:
    """Return a compact MJCF scene for a 3-DOF head with visible eyes."""
    return """
<mujoco model="soulforge_m0_head">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.005" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="1280" offheight="960"/>
    <headlight diffuse="0.7 0.7 0.7" ambient="0.25 0.25 0.25" specular="0.2 0.2 0.2"/>
    <rgba haze="0.92 0.95 1 1"/>
  </visual>
  <asset>
    <material name="mat_body" rgba="0.67 0.78 0.88 1"/>
    <material name="mat_head" rgba="0.95 0.90 0.78 1"/>
    <material name="mat_eye" rgba="0.02 0.025 0.03 1"/>
    <material name="mat_target" rgba="0.95 0.12 0.08 1"/>
    <material name="mat_floor" rgba="0.88 0.90 0.92 1"/>
  </asset>
  <worldbody>
    <light name="key" pos="0 -3 3" dir="0 1 -1" directional="true"/>
    <geom name="floor" type="plane" pos="0 0 0" size="2 2 0.02" material="mat_floor"/>
    <camera name="demo" pos="1.25 -2.2 1.25" xyaxes="1 0 0 0 0.45 0.89"/>

    <body name="torso" pos="0 0 0.45">
      <geom name="torso_geom" type="capsule" fromto="0 0 -0.2 0 0 0.25" size="0.18" material="mat_body"/>

      <body name="yaw_link" pos="0 0 0.28">
        <inertial pos="0 0 0" mass="0.01" diaginertia="0.00001 0.00001 0.00001"/>
        <joint name="head_yaw" type="hinge" axis="0 0 1" range="-0.70 0.70" damping="4.0" armature="0.02"/>

        <body name="pitch_link">
          <inertial pos="0 0 0" mass="0.01" diaginertia="0.00001 0.00001 0.00001"/>
          <joint name="head_pitch" type="hinge" axis="1 0 0" range="-0.45 0.45" damping="4.0" armature="0.02"/>

          <body name="roll_link">
            <inertial pos="0 0 0" mass="0.01" diaginertia="0.00001 0.00001 0.00001"/>
            <joint name="head_roll" type="hinge" axis="0 1 0" range="-0.30 0.30" damping="3.0" armature="0.02"/>

            <body name="head" pos="0 -0.02 0.18">
              <geom name="head_geom" type="ellipsoid" size="0.20 0.16 0.18" material="mat_head"/>
              <geom name="left_eye" type="sphere" pos="-0.065 -0.135 0.035" size="0.025" material="mat_eye"/>
              <geom name="right_eye" type="sphere" pos="0.065 -0.135 0.035" size="0.025" material="mat_eye"/>
              <geom name="beak" type="capsule" fromto="0 -0.15 -0.015 0 -0.28 -0.035" size="0.022" rgba="0.98 0.62 0.14 1"/>
            </body>
          </body>
        </body>
      </body>
    </body>

    <body name="reactive_target" pos="0.42 -0.72 0.84">
      <geom name="target_pole" type="capsule" fromto="0 0 -0.18 0 0 0.02" size="0.01" material="mat_target"/>
      <geom name="target_geom" type="sphere" size="0.075" material="mat_target"/>
    </body>
  </worldbody>
  <actuator>
    <position name="head_yaw_servo" joint="head_yaw" kp="12" ctrlrange="-0.70 0.70"/>
    <position name="head_pitch_servo" joint="head_pitch" kp="12" ctrlrange="-0.45 0.45"/>
    <position name="head_roll_servo" joint="head_roll" kp="8" ctrlrange="-0.30 0.30"/>
  </actuator>
</mujoco>
""".strip()


def build_manifest() -> dict:
    return {
        "device_id": "sf-m0-mujoco-head",
        "form_factor": {
            "type": "rigid",
            "height_cm": 25,
            "weight_g": 500,
            "has_costume": False,
            "costume_friction_factor": 0.0,
        },
        "actuators": [
            {
                "id": "head_yaw",
                "type": "servo",
                "body_part": "head",
                "dof": 1,
                "range_min": -40,
                "range_max": 40,
                "unit": "degrees",
                "max_speed": 120,
                "thermal_limit_celsius": 65,
            },
            {
                "id": "head_pitch",
                "type": "servo",
                "body_part": "head",
                "dof": 1,
                "range_min": -25,
                "range_max": 25,
                "unit": "degrees",
                "max_speed": 100,
                "thermal_limit_celsius": 65,
            },
            {
                "id": "head_roll",
                "type": "servo",
                "body_part": "head",
                "dof": 1,
                "range_min": -17,
                "range_max": 17,
                "unit": "degrees",
                "max_speed": 80,
                "thermal_limit_celsius": 65,
            },
        ],
        "power": {
            "battery_capacity_mah": 2500,
            "voltage_nominal": 5.0,
            "voltage_cutoff": 4.5,
            "max_continuous_draw_ma": 2000,
            "charging_method": "usb_c",
        },
    }


def target_pose_degrees(t: float) -> dict[str, float]:
    """Generate idle motion, then a high-priority reactive look-at target."""
    if t < INTERRUPT_AT_S:
        return {
            "head_yaw": 14.0 * math.sin(2.0 * math.pi * 0.22 * t),
            "head_pitch": 5.0 * math.sin(2.0 * math.pi * 0.33 * t + 0.5),
            "head_roll": 4.0 * math.sin(2.0 * math.pi * 0.18 * t + 1.2),
        }
    if t < RECOVER_AT_S:
        return {
            "head_yaw": 24.0,
            "head_pitch": -6.0,
            "head_roll": 0.0,
        }
    return {
        "head_yaw": 10.0 * math.sin(2.0 * math.pi * 0.18 * (t - RECOVER_AT_S)),
        "head_pitch": 3.0 * math.sin(2.0 * math.pi * 0.27 * (t - RECOVER_AT_S)),
        "head_roll": 2.5 * math.sin(2.0 * math.pi * 0.16 * (t - RECOVER_AT_S)),
    }


def build_smoothers(fps: int) -> dict[str, MotionSmoother]:
    return {
        "head_yaw": MotionSmoother(
            policy_rate=fps,
            servo_rate=fps,
            cutoff_hz=10.0,
            max_velocity=120.0,
            max_acceleration=500.0,
        ),
        "head_pitch": MotionSmoother(
            policy_rate=fps,
            servo_rate=fps,
            cutoff_hz=10.0,
            max_velocity=100.0,
            max_acceleration=420.0,
        ),
        "head_roll": MotionSmoother(
            policy_rate=fps,
            servo_rate=fps,
            cutoff_hz=10.0,
            max_velocity=80.0,
            max_acceleration=300.0,
        ),
    }


def filtered_pose_degrees(
    pose: dict[str, float],
    smoothers: dict[str, MotionSmoother],
    safety: SafetyManager,
    dt: float,
) -> dict[str, float]:
    commands = []
    for joint in JOINTS:
        smoothed = smoothers[joint].process(pose[joint])[-1]
        commands.append(
            {
                "actuator_id": joint,
                "command_type": "position",
                "value": smoothed,
            }
        )
    safe_commands = safety.filter(commands, dt=dt)
    return {cmd["actuator_id"]: float(cmd["value"]) for cmd in safe_commands}


def record_demo(
    out_path: Path,
    duration_s: float,
    fps: int,
    width: int,
    height: int,
    mjcf_out: Path | None,
) -> dict:
    try:
        import imageio.v2 as imageio
        import mujoco
    except ImportError as exc:
        raise SystemExit(
            "Missing MuJoCo recording dependencies. Run: "
            "uv sync --all-packages --all-groups"
        ) from exc

    mjcf = build_head_mjcf()
    if mjcf_out:
        mjcf_out.parent.mkdir(parents=True, exist_ok=True)
        mjcf_out.write_text(mjcf + "\n", encoding="utf-8")

    model = mujoco.MjModel.from_xml_string(mjcf)
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height=height, width=width)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = [0.05, -0.10, 0.78]
    camera.distance = 1.45
    camera.azimuth = 135
    camera.elevation = -18

    manifest = build_manifest()
    safety = SafetyManager(manifest)
    smoothers = build_smoothers(fps)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        out_path,
        fps=fps,
        codec="libx264",
        quality=8,
        macro_block_size=1,
    )

    dt = 1.0 / fps
    physics_steps = max(1, round(dt / model.opt.timestep))
    ctrl_ids = {name: model.actuator(name + "_servo").id for name in JOINTS}
    qpos_ids = {name: model.joint(name).qposadr[0] for name in JOINTS}

    max_abs_deg = {name: 0.0 for name in JOINTS}
    sample_rows = []
    try:
        total_frames = int(duration_s * fps)
        for frame_idx in range(total_frames):
            t = frame_idx * dt
            target = target_pose_degrees(t)
            safe = filtered_pose_degrees(target, smoothers, safety, dt)

            for joint in JOINTS:
                data.ctrl[ctrl_ids[joint]] = math.radians(safe[joint])

            for _ in range(physics_steps):
                mujoco.mj_step(model, data)

            actual = {joint: math.degrees(data.qpos[qpos_ids[joint]]) for joint in JOINTS}
            for joint, value in actual.items():
                max_abs_deg[joint] = max(max_abs_deg[joint], abs(value))

            if frame_idx % fps == 0 or abs(t - INTERRUPT_AT_S) < dt:
                sample_rows.append(
                    {
                        "t": round(t, 2),
                        "target_yaw": round(target["head_yaw"], 2),
                        "safe_yaw": round(safe["head_yaw"], 2),
                        "actual_yaw": round(actual["head_yaw"], 2),
                    }
                )

            renderer.update_scene(data, camera=camera)
            writer.append_data(renderer.render())
    finally:
        writer.close()
        renderer.close()

    return {
        "out": str(out_path),
        "duration_s": duration_s,
        "fps": fps,
        "frames": int(duration_s * fps),
        "interrupt_at_s": INTERRUPT_AT_S,
        "recover_at_s": RECOVER_AT_S,
        "max_abs_deg": {k: round(v, 2) for k, v in max_abs_deg.items()},
        "safety": safety.get_safety_status()["overall_status"],
        "samples": sample_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/mujoco/head_soft_interrupt.mp4"),
        help="MP4 output path.",
    )
    parser.add_argument("--duration", type=float, default=5.2, help="Video duration in seconds.")
    parser.add_argument("--fps", type=int, default=30, help="Recorded video frame rate.")
    parser.add_argument("--width", type=int, default=960, help="Rendered frame width.")
    parser.add_argument("--height", type=int, default=720, help="Rendered frame height.")
    parser.add_argument(
        "--mjcf-out",
        type=Path,
        default=Path("outputs/mujoco/head_soft_interrupt.xml"),
        help="Optional path to write the generated MJCF model.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = record_demo(
        out_path=args.out,
        duration_s=args.duration,
        fps=args.fps,
        width=args.width,
        height=args.height,
        mjcf_out=args.mjcf_out,
    )
    print("SoulForge MuJoCo M0 demo recorded")
    for key in ("out", "duration_s", "fps", "frames", "interrupt_at_s", "recover_at_s", "safety"):
        print(f"{key}: {result[key]}")
    print(f"max_abs_deg: {result['max_abs_deg']}")
    print("samples:")
    for row in result["samples"]:
        print(f"  {row}")


if __name__ == "__main__":
    main()
