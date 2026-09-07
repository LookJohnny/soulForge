"""三幕融资 demo 组装器：录屏段 + 字幕卡 + 台词音轨（按时间戳对位）→ 成片。

输入 outputs/demo_shoot/shots.json：
    [{"file": "act1.mov", "start": 1757000000.0, "title": "第一幕 · 她先注意到你",
      "sub": "没有脚本。她的每一句话都由她的人格当场决定。"}, ...]
音轨来自 TTS_DUMP_DIR 里以合成时刻命名的 mp3（<epoch>.mp3），
落进对应段的时间窗即按 (mtime - seg_start + LAG) 偏移混入。

用法：.venv/bin/python scripts/assemble_demo.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOOT = ROOT / "outputs" / "demo_shoot"
AUDIO = SHOOT / "audio"
OUT = SHOOT / "soulforge_demo.mp4"
CARD_SECONDS = 3.2
LAG = 0.6  # 合成完成 → 浏览器实际出声的经验补偿
W, H, FPS = 1920, 1080, 30
FONT = "PingFang SC"


def run(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def title_card(index: int, title: str, sub: str) -> Path:
    path = SHOOT / f"card{index}.mp4"
    draw = (
        f"drawtext=font='{FONT}':text='{title}':fontsize=64:fontcolor=0xF2EFF6:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-40:alpha='min(1,t/0.8)',"
        f"drawtext=font='{FONT}':text='{sub}':fontsize=30:fontcolor=0x9A93A8:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+56:alpha='min(1,max(0,(t-0.4)/0.8))'"
    )
    run("ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=0x050308:s={W}x{H}:d={CARD_SECONDS}:r={FPS}",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={CARD_SECONDS}",
        "-vf", draw, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path))
    return path


def segment_with_audio(index: int, spec: dict) -> Path:
    src = SHOOT / spec["file"]
    duration = probe_duration(src)
    start = float(spec["start"])
    clips = []
    for mp3 in sorted(AUDIO.glob("*.mp3")):
        try:
            at = float(mp3.stem)
        except ValueError:
            continue
        offset = at - start + LAG
        if 0 <= offset < duration - 0.5:
            clips.append((offset, mp3))

    out = SHOOT / f"seg{index}.mp4"
    scale = f"scale={W}:{H}:force_original_aspect_ratio=decrease," \
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x050308,fps={FPS}"
    if not clips:
        run("ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", scale, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(out))
        return out

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    for _, mp3 in clips:
        cmd += ["-i", str(mp3)]
    chains = []
    labels = []
    for i, (offset, _) in enumerate(clips):
        ms = int(offset * 1000)
        chains.append(f"[{i + 1}]adelay={ms}|{ms}[a{i}]")
        labels.append(f"[a{i}]")
    chains.append(
        "".join(labels) + f"amix=inputs={len(clips)}:normalize=0[mix]"
    )
    cmd += ["-filter_complex", ";".join(chains),
            "-map", "0:v", "-map", "[mix]",
            "-vf", scale, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(out)]
    run(*cmd)
    return out


def main() -> None:
    shots = json.loads((SHOOT / "shots.json").read_text("utf-8"))
    parts: list[Path] = []
    for i, spec in enumerate(shots):
        parts.append(title_card(i, spec["title"], spec.get("sub", "")))
        parts.append(segment_with_audio(i, spec))

    concat = SHOOT / "concat.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in parts), "utf-8")
    run("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat), "-c", "copy", str(OUT))
    print("✓ 成片:", OUT)


if __name__ == "__main__":
    main()
