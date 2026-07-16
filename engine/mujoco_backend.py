"""MuJoCo execution backend for SoulForge physical AI."""

from __future__ import annotations

import math
from pathlib import Path


class MuJoCoVideoBackend:
    """Stream safe hardware commands into MuJoCo and record video.

    `control_hz` belongs to the executor. `record_fps` belongs to this backend.
    They can differ, which lets long simulations run with frequent control
    updates but sparse video frames.
    """

    def __init__(
        self,
        mjcf: str,
        out_path: Path,
        *,
        record_fps: float = 30.0,
        width: int = 960,
        height: int = 720,
        mjcf_out: Path | None = None,
        camera: dict | None = None,
    ):
        try:
            import imageio.v2 as imageio
            import mujoco
        except ImportError as exc:
            raise RuntimeError(
                "Missing MuJoCo recording dependencies. Run: "
                "uv sync --all-packages --all-groups"
            ) from exc

        self.mujoco = mujoco
        self.imageio = imageio
        self.elapsed_s = 0.0
        self.record_fps = record_fps
        self.record_dt = 1.0 / record_fps
        self.next_record_s = 0.0
        self.frames_written = 0
        self.max_abs_deg: dict[str, float] = {}

        out_path.parent.mkdir(parents=True, exist_ok=True)
        if mjcf_out is not None:
            mjcf_out.parent.mkdir(parents=True, exist_ok=True)
            mjcf_out.write_text(mjcf + "\n", encoding="utf-8")

        self.model = mujoco.MjModel.from_xml_string(mjcf)
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height=height, width=width)
        self.writer = imageio.get_writer(
            out_path,
            fps=record_fps,
            codec="libx264",
            quality=8,
            macro_block_size=1,
        )

        self.camera = mujoco.MjvCamera()
        self.camera.type = mujoco.mjtCamera.mjCAMERA_FREE
        camera_cfg = camera or {}
        self.camera.lookat[:] = camera_cfg.get("lookat", [0.05, -0.10, 0.78])
        self.camera.distance = camera_cfg.get("distance", 1.55)
        self.camera.azimuth = camera_cfg.get("azimuth", 135)
        self.camera.elevation = camera_cfg.get("elevation", -18)

        self._actuator_ids = {
            self.model.actuator(i).name: i for i in range(self.model.nu)
        }
        self._joint_qpos = {
            self.model.joint(i).name: self.model.joint(i).qposadr[0]
            for i in range(self.model.njnt)
            if self.model.joint(i).name
        }

    def send(self, commands: list[dict], dt: float) -> None:
        for command in commands:
            actuator_id = command.get("actuator_id", "")
            value = command.get("value", 0.0)
            if not isinstance(value, (int, float)):
                continue

            mj_actuator = self._resolve_actuator(actuator_id)
            if mj_actuator is None:
                continue
            self.data.ctrl[mj_actuator] = math.radians(float(value))

        physics_steps = max(1, round(dt / self.model.opt.timestep))
        for _ in range(physics_steps):
            self.mujoco.mj_step(self.model, self.data)

        self.elapsed_s += dt
        self._record_joint_extrema()

        if self.elapsed_s + 1e-9 >= self.next_record_s:
            self.renderer.update_scene(self.data, camera=self.camera)
            self.writer.append_data(self.renderer.render())
            self.frames_written += 1
            self.next_record_s += self.record_dt

    def close(self) -> None:
        self.writer.close()
        self.renderer.close()

    def _resolve_actuator(self, actuator_id: str) -> int | None:
        if actuator_id in self._actuator_ids:
            return self._actuator_ids[actuator_id]
        servo_name = actuator_id + "_servo"
        return self._actuator_ids.get(servo_name)

    def _record_joint_extrema(self) -> None:
        for joint_name, qpos_id in self._joint_qpos.items():
            value = abs(math.degrees(float(self.data.qpos[qpos_id])))
            self.max_abs_deg[joint_name] = max(
                self.max_abs_deg.get(joint_name, 0.0), value
            )
