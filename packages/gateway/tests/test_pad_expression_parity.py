"""JS 端 PAD→配方 (studio/web/lib/pad_expression.js) 必须与 face_engine.select_recipe 逐点一致。

舵机脸与 VRM 身体共享同一情绪→表情语义；配方表改动必须两边同步，
这个测试用一张 PAD 网格把两个实现钉在一起。需要 node；没有则跳过。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gateway import face_engine

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "studio" / "web" / "lib" / "pad_expression.js"

GRID = [x / 10 for x in range(-10, 11)]  # -1.0 … 1.0 step 0.1


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_select_recipe_matches_python():
    intensity = face_engine.INTENSITY
    script = f"""
    import {{ selectRecipe }} from {json.dumps(JS.as_uri())};
    const grid = {json.dumps(GRID)};
    const out = [];
    for (const p of grid) for (const a of grid) for (const d of grid)
      out.push(selectRecipe(p, a, d, {intensity}));
    process.stdout.write(JSON.stringify(out));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    js_keys = json.loads(proc.stdout)

    py_keys = [
        face_engine.select_recipe(p, a, d).key for p in GRID for a in GRID for d in GRID
    ]
    assert len(js_keys) == len(py_keys) == len(GRID) ** 3

    mismatches = [
        (p, a, d, py, js)
        for (p, a, d), py, js in zip(
            ((p, a, d) for p in GRID for a in GRID for d in GRID), py_keys, js_keys
        )
        if py != js
    ]
    assert not mismatches, f"{len(mismatches)} mismatches, first: {mismatches[:5]}"


def test_every_python_recipe_has_js_preset():
    """每个 Python 配方 key 在 JS 预设表里都要有条目，否则 VRM 端会退回 rest。"""
    keys = {
        face_engine.select_recipe(p, a, d).key for p in GRID for a in GRID for d in GRID
    }
    src = JS.read_text(encoding="utf-8")
    presets_block = src.split("RECIPE_PRESETS = {", 1)[1].split("};", 1)[0]
    missing = [k for k in keys if f"{k}:" not in presets_block]
    assert not missing, missing
