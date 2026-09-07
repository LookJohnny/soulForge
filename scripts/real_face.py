"""真人脸流水线：万相生成照片级人像 → EMO/LivePortrait 用她的真实台词驱动说话视频。

用法：
    .venv/bin/python scripts/real_face.py portrait          # 生成 3 张候选人像
    .venv/bin/python scripts/real_face.py talk <img> <mp3>  # 人像+台词 → 说话视频
产物在 outputs/real_face/。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "real_face"
BASE = "https://dashscope.aliyuncs.com"

PORTRAIT_PROMPT = (
    "电影感真人肖像照，25岁亚洲女性，温柔而有神的眼睛直视镜头，微微一笑，"
    "黑长发微卷，霓虹夜色环境光（品红与青色轮廓光），浅景深，皮肤质感真实，"
    "肩部以上构图，正面平视，8k 摄影，柔和影棚主光"
)
NEGATIVE = "动漫, 卡通, 插画, 3D渲染, 塑料感, 畸形, 多余手指, 文字, 水印"


def api_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DASHSCOPE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no DASHSCOPE_API_KEY")


def call(path: str, body: dict, *, async_task: bool) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }
    if async_task:
        headers["X-DashScope-Async"] = "enable"
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), headers=headers
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def poll(task_id: str, minutes: float = 10) -> dict:
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        req = urllib.request.Request(
            f"{BASE}/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {api_key()}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        status = data.get("output", {}).get("task_status")
        if status == "SUCCEEDED":
            return data
        if status in ("FAILED", "CANCELED"):
            raise SystemExit(f"task {status}: {json.dumps(data)[:400]}")
        print("…", status)
        time.sleep(5)
    raise SystemExit("task timeout")


def fetch(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as resp:
        target.write_bytes(resp.read())


def portrait() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    task = call(
        "/api/v1/services/aigc/text2image/image-synthesis",
        {
            "model": "wanx2.1-t2i-plus",
            "input": {"prompt": PORTRAIT_PROMPT, "negative_prompt": NEGATIVE},
            "parameters": {"n": 3, "size": "768*1152"},
        },
        async_task=True,
    )
    task_id = task["output"]["task_id"]
    print("portrait task:", task_id)
    done = poll(task_id)
    for i, item in enumerate(done["output"].get("results", []), 1):
        if item.get("url"):
            path = OUT / f"portrait_{i}.png"
            fetch(item["url"], path)
            print("✓", path)


def talk(image: str, audio: str) -> None:
    """EMO 需要公网可访问的 URL：先把素材传到 dashscope 的临时 OSS。"""
    OUT.mkdir(parents=True, exist_ok=True)
    from dashscope.utils.oss_utils import upload_file  # SDK 自带上传

    key = api_key()
    image_url = upload_file("emo-v1", image, key)
    audio_url = upload_file("emo-v1", audio, key)
    # 先做人像检测拿 face bbox（emo 的规范流程）
    detect = call(
        "/api/v1/services/aigc/image2video/face-detect",
        {"model": "emo-detect-v1", "input": {"image_url": image_url}, "parameters": {"ratio": "3:4"}},
        async_task=False,
    )
    ext = detect.get("output", {}).get("ext", {})
    face = detect.get("output", {}) or {}
    task = call(
        "/api/v1/services/aigc/image2video/video-synthesis",
        {
            "model": "emo-v1",
            "input": {
                "image_url": image_url,
                "audio_url": audio_url,
                "face_bbox": face.get("face_bbox") or ext.get("face_bbox"),
                "ext_bbox": face.get("ext_bbox") or ext.get("ext_bbox"),
            },
            "parameters": {"style_level": "normal"},
        },
        async_task=True,
    )
    task_id = task["output"]["task_id"]
    print("talk task:", task_id)
    done = poll(task_id, minutes=20)
    url = done["output"].get("results", {}).get("video_url") or done["output"].get("video_url")
    target = OUT / f"talk_{int(time.time())}.mp4"
    fetch(url, target)
    print("✓", target)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "portrait":
        portrait()
    elif len(sys.argv) >= 4 and sys.argv[1] == "talk":
        talk(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
