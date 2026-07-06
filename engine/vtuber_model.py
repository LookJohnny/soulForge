"""Vtuber asset loading for MuJoCo-backed physical AI.

MuJoCo cannot directly simulate most Vtuber assets because VRM/GLB/Live2D files
are render rigs, not physical actuator models. The loader therefore has two
paths:

1. Native MJCF/XML: load the supplied physical model directly.
2. Proxy mode: preserve the Vtuber asset identity and drive a generic MuJoCo
   humanoid/mascot proxy with the same physical AI engine.

Proxy mode is the reliable default for "any Vtuber model" acceptance testing.
It proves autonomy, scheduling, safety, and long video recording independent of
the final art-rig conversion pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_PROXY_SUFFIXES = {
    ".vrm",
    ".glb",
    ".gltf",
    ".model3.json",
    ".json",
    ".fbx",
    ".obj",
    ".stl",
}


@dataclass
class LoadedVtuberModel:
    source_path: Path
    mode: str
    mjcf: str
    manifest: dict
    description: str


def load_vtuber_model(path: str | Path | None) -> LoadedVtuberModel:
    source_path = Path(path) if path else Path("proxy://soulforge-vtuber")
    suffix = _compound_suffix(source_path)

    if source_path.exists() and suffix == ".xml":
        return LoadedVtuberModel(
            source_path=source_path,
            mode="native_mjcf",
            mjcf=source_path.read_text(encoding="utf-8"),
            manifest=build_proxy_manifest(source_path.stem),
            description="Native MJCF loaded directly. Manifest uses the standard proxy channel set.",
        )

    if suffix in SUPPORTED_PROXY_SUFFIXES or not source_path.exists():
        label = source_path.stem if source_path.name else "soulforge-vtuber"
        return LoadedVtuberModel(
            source_path=source_path,
            mode="proxy",
            mjcf=build_proxy_mjcf(label),
            manifest=build_proxy_manifest(label),
            description=(
                "Proxy MuJoCo body generated for a Vtuber render asset. "
                "Use this path for VRM/GLB/Live2D acceptance until a dedicated "
                "rig-to-MJCF converter is available."
            ),
        )

    raise ValueError(f"Unsupported Vtuber model format: {source_path}")


def build_proxy_manifest(label: str = "vtuber_proxy") -> dict:
    return {
        "device_id": f"sf-{label}-proxy",
        "form_factor": {
            "type": "rigid",
            "height_cm": 35,
            "weight_g": 900,
            "has_costume": False,
            "costume_friction_factor": 0.0,
        },
        "actuators": [
            _servo("head_yaw", "head", -40, 40, 120),
            _servo("head_pitch", "head", -25, 25, 100),
            _servo("head_roll", "head", -17, 17, 80),
            _servo("body_yaw", "body", -20, 20, 60),
            _servo("body_roll", "body", -15, 15, 60),
            _servo("left_arm_pitch", "left_arm", -20, 80, 90),
            _servo("right_arm_pitch", "right_arm", -20, 80, 90),
        ],
        "sensors": [
            {
                "id": "autonomy_clock",
                "type": "timer",
                "body_part": "body",
                "sample_rate_hz": 1,
                "range_min": 0,
                "range_max": 1,
            }
        ],
        "power": {
            "battery_capacity_mah": 5000,
            "voltage_nominal": 5.0,
            "voltage_cutoff": 4.5,
            "max_continuous_draw_ma": 3000,
            "charging_method": "usb_c",
        },
        "believability_profile": {
            "max_emotion_channels": 7,
            "gesture_fluidity_score": 0.8,
            "audio_visual_sync_capable": True,
            "idle_animation_capable": True,
            "touch_responsive": True,
        },
    }


def build_proxy_mjcf(label: str = "vtuber_proxy") -> str:
    return f"""
<mujoco model="soulforge_{_xml_name(label)}">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.01" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="1280" offheight="960"/>
    <headlight diffuse="0.7 0.7 0.7" ambient="0.25 0.25 0.25" specular="0.2 0.2 0.2"/>
    <rgba haze="0.92 0.95 1 1"/>
  </visual>
  <asset>
    <material name="mat_body" rgba="0.58 0.72 0.92 1"/>
    <material name="mat_head" rgba="0.96 0.90 0.82 1"/>
    <material name="mat_eye" rgba="0.02 0.025 0.03 1"/>
    <material name="mat_accent" rgba="0.95 0.20 0.35 1"/>
    <material name="mat_floor" rgba="0.88 0.90 0.92 1"/>
  </asset>
  <worldbody>
    <light name="key" pos="0 -3 3" dir="0 1 -1" directional="true"/>
    <geom name="floor" type="plane" pos="0 0 0" size="3 3 0.02" material="mat_floor"/>

    <body name="root" pos="0 0 0.55">
      <joint name="body_yaw" type="hinge" axis="0 0 1" range="-0.35 0.35" damping="5.0" armature="0.04"/>
      <joint name="body_roll" type="hinge" axis="0 1 0" range="-0.26 0.26" damping="5.0" armature="0.04"/>
      <geom name="body_geom" type="capsule" fromto="0 0 -0.25 0 0 0.28" size="0.18" material="mat_body"/>

      <body name="left_arm" pos="-0.20 0 0.12">
        <inertial pos="0 0 -0.12" mass="0.08" diaginertia="0.0002 0.0002 0.0002"/>
        <joint name="left_arm_pitch" type="hinge" axis="1 0 0" range="-0.35 1.40" damping="3.0" armature="0.02"/>
        <geom type="capsule" fromto="0 0 0 0 0 -0.25" size="0.04" material="mat_body"/>
      </body>

      <body name="right_arm" pos="0.20 0 0.12">
        <inertial pos="0 0 -0.12" mass="0.08" diaginertia="0.0002 0.0002 0.0002"/>
        <joint name="right_arm_pitch" type="hinge" axis="1 0 0" range="-0.35 1.40" damping="3.0" armature="0.02"/>
        <geom type="capsule" fromto="0 0 0 0 0 -0.25" size="0.04" material="mat_body"/>
      </body>

      <body name="head_yaw_link" pos="0 0 0.32">
        <inertial pos="0 0 0" mass="0.02" diaginertia="0.00002 0.00002 0.00002"/>
        <joint name="head_yaw" type="hinge" axis="0 0 1" range="-0.70 0.70" damping="4.0" armature="0.02"/>
        <body name="head_pitch_link">
          <inertial pos="0 0 0" mass="0.02" diaginertia="0.00002 0.00002 0.00002"/>
          <joint name="head_pitch" type="hinge" axis="1 0 0" range="-0.45 0.45" damping="4.0" armature="0.02"/>
          <body name="head_roll_link">
            <inertial pos="0 0 0" mass="0.02" diaginertia="0.00002 0.00002 0.00002"/>
            <joint name="head_roll" type="hinge" axis="0 1 0" range="-0.30 0.30" damping="3.0" armature="0.02"/>
            <body name="head" pos="0 -0.02 0.15">
              <geom name="head_geom" type="ellipsoid" size="0.19 0.15 0.18" material="mat_head"/>
              <geom name="left_eye" type="sphere" pos="-0.060 -0.130 0.035" size="0.024" material="mat_eye"/>
              <geom name="right_eye" type="sphere" pos="0.060 -0.130 0.035" size="0.024" material="mat_eye"/>
              <geom name="hair_accent" type="capsule" fromto="-0.10 -0.02 0.16 0.10 -0.02 0.16" size="0.025" material="mat_accent"/>
            </body>
          </body>
        </body>
      </body>
    </body>
  </worldbody>
  <actuator>
    <position name="body_yaw_servo" joint="body_yaw" kp="8" ctrlrange="-0.35 0.35"/>
    <position name="body_roll_servo" joint="body_roll" kp="8" ctrlrange="-0.26 0.26"/>
    <position name="left_arm_pitch_servo" joint="left_arm_pitch" kp="8" ctrlrange="-0.35 1.40"/>
    <position name="right_arm_pitch_servo" joint="right_arm_pitch" kp="8" ctrlrange="-0.35 1.40"/>
    <position name="head_yaw_servo" joint="head_yaw" kp="12" ctrlrange="-0.70 0.70"/>
    <position name="head_pitch_servo" joint="head_pitch" kp="12" ctrlrange="-0.45 0.45"/>
    <position name="head_roll_servo" joint="head_roll" kp="8" ctrlrange="-0.30 0.30"/>
  </actuator>
</mujoco>
""".strip()


def _servo(actuator_id: str, body_part: str, min_deg: float, max_deg: float, speed: float) -> dict:
    return {
        "id": actuator_id,
        "type": "servo",
        "body_part": body_part,
        "dof": 1,
        "range_min": min_deg,
        "range_max": max_deg,
        "unit": "degrees",
        "max_speed": speed,
        "thermal_limit_celsius": 65,
        "max_acceleration": speed * 4,
    }


def _compound_suffix(path: Path) -> str:
    if path.name.endswith(".model3.json"):
        return ".model3.json"
    return path.suffix.lower()


def _xml_name(label: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in label.lower())
    return cleaned.strip("_") or "vtuber_proxy"
