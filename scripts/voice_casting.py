"""Joi 音色选角：搜 Fish Audio 音色库，同一句自然台词各合成一段试音。

用法：
    .venv/bin/python scripts/voice_casting.py            # 搜索+合成到 outputs/tts_bench/cast/
    .venv/bin/python scripts/voice_casting.py --play      # 合成后逐个播放
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "tts_bench" / "cast"
KEYWORDS = ["温柔", "女友", "治愈", "御姐", "少女音", "妈妈"]
# 自然对话感的试音台词——考验停顿、语气词与口语韵律，不是朗诵
LINE = "嗯……我刚在看窗外下雨来着。你回来啦？今天过得怎么样，跟我说说呗。"
PER_KEYWORD = 3
MIN_TASKS = 3000  # 用量太低的克隆质量普遍不稳


def api_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("FISH_AUDIO_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("FISH_AUDIO_API_KEY not in .env")


def get(url: str, key: str) -> object:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search(key: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for kw in KEYWORDS:
        query = urllib.parse.urlencode(
            {"language": "zh", "title": kw, "sort_by": "task_count", "page_size": 8}
        )
        data = get(f"https://api.fish.audio/model?{query}", key)
        items = data if isinstance(data, list) else data.get("items", [])
        kept = 0
        for model in items:
            if kept >= PER_KEYWORD:
                break
            if (model.get("task_count") or 0) < MIN_TASKS:
                continue
            model_id = model.get("_id")
            if model_id and model_id not in seen:
                seen[model_id] = model
                kept += 1
    return sorted(seen.values(), key=lambda m: -(m.get("task_count") or 0))


def synthesize(model_id: str, key: str) -> bytes | None:
    body = json.dumps(
        {
            "text": LINE,
            "reference_id": model_id,
            "format": "mp3",
            "normalize": True,
            "latency": "normal",
            "prosody": {"speed": 1.0, "volume": 0},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.fish.audio/v1/tts",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "model": "s1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except Exception as exc:  # 单个音色失败不拦选角
        print(f"  ✗ {model_id}: {exc}")
        return None


def main() -> None:
    key = api_key()
    OUT.mkdir(parents=True, exist_ok=True)
    candidates = search(key)
    print(f"候选 {len(candidates)} 个：")
    manifest = []
    for i, model in enumerate(candidates, 1):
        title = re.sub(r"[^\w一-鿿]+", "_", model.get("title") or "untitled")[:20]
        model_id = model["_id"]
        print(f"{i:02d}. {title}  tasks={model.get('task_count')}  id={model_id}")
        audio = synthesize(model_id, key)
        if not audio:
            continue
        path = OUT / f"{i:02d}_{title}.mp3"
        path.write_bytes(audio)
        manifest.append({"file": path.name, "title": model.get("title"), "id": model_id})
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    print(f"\n{len(manifest)} 段试音已生成到 {OUT}")
    if "--play" in sys.argv:
        for entry in manifest:
            print("▶", entry["title"])
            subprocess.run(["afplay", str(OUT / entry["file"])], check=False)


if __name__ == "__main__":
    main()
