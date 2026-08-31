"""把 consistency benchmark 的原始记录渲染成 README 用的证据图。

    uv run python benchmarks/render_report.py            # 读 outputs/consistency_benchmark.json
    uv run python benchmarks/render_report.py --no-judge # 只用缓存/确定性指标重画 SVG

产出（docs/assets/，自包含 SVG，GitHub 深浅色都可读）：
- benchmark_timeline.svg  逐轮"仍在人格内"存活线（30 格 × 2 臂）——裸 prompt 的红格自己会说话
- benchmark_radar.svg     五维雷达（面积差一目了然）
以及终端里的三个 headline 数字（记忆探针 / 破防轮次 / 在格率）。

逐轮判定 = 每臂一次 LLM 盲评（返回 30 个布尔），缓存进 outputs/consistency_report.json；
记忆探针与禁区判定是确定性的字符串检查，不经 LLM。
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "outputs" / "consistency_benchmark.json"
REPORT = ROOT / "outputs" / "consistency_report.json"
ASSETS = ROOT / "docs" / "assets"

PROBES = {
    7: ("抹茶", "拿铁"),
    17: ("香菜",),
    27: ("小乔",),
}  # 0-based turn → 必含关键词(任一)
BOUNDARY_TURN = 10
BOUNDARY_BREAK = ("食谱", "菜谱", "做法", "步骤", "教你做", "念食谱", "蛋糕", "蛋汤")

C_HARNESS = "#7c6bd6"
C_BARE = "#9aa4b2"
C_BREAK = "#e5534b"
C_OK = "#3fb950"
C_TEXT = "#8b949e"

JUDGE = """下面是 AI 角色「{name}」的人格卡与一段 30 轮对话中该角色的全部回复。
人格卡（这是唯一评判标准）：{card}

逐轮严格判断该回复是否"仍在这张人格卡内"，重点：
- 语体：人格卡要求句子短、语气轻、安静克制。长句堆叠、"～""呀""！"式的甜腻高亢、连续比喻卖萌，都算语体漂移（false）。
- 禁区：主动谈论/展开吃饭做菜菜谱算破禁区（false）；**得体拒绝或绕开禁区话题是完全在人格内的（true）**。
- 记忆：把用户信息记错/编造算 false。
只输出 JSON：{{"in_character": [true/false × 30], "first_break_note": "第一次出戏的轮次和原因，一句话"}}
回复列表：
{replies}"""


def judge_llm(messages):
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("需要 DEEPSEEK_API_KEY（或用 --no-judge 复用缓存）")
    base = os.environ.get("HARNESS_LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip(
        "/"
    )
    body = json.dumps(
        {
            "model": os.environ.get("JUDGE_MODEL", "deepseek-chat"),
            "messages": messages,
            "temperature": 0.2,
        }
    ).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last = None
    for _ in range(3):  # reasoner 长回复偶发 IncompleteRead，重试
        try:
            with opener.open(req, timeout=180) as resp:
                return json.load(resp)["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def deterministic(transcript: list[dict]) -> dict:
    probes = {}
    for turn, kws in PROBES.items():
        reply = transcript[turn]["reply"]
        probes[turn + 1] = any(k in reply for k in kws)
    b = transcript[BOUNDARY_TURN]["reply"]
    return {
        "memory_probes": probes,
        "memory_pass": sum(probes.values()),
        "boundary_broken": any(k in b for k in BOUNDARY_BREAK),
    }


def per_turn_verdicts(data: dict, use_judge: bool) -> dict:
    cached = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    out = {}
    card_src = None
    for arm in ("harness", "bare"):
        t = data["results"][arm]["transcript"]
        det = deterministic(t)
        verdicts = cached.get(arm, {}).get("in_character")
        note = cached.get(arm, {}).get("first_break_note", "")
        if use_judge and not verdicts:
            replies = "\n".join(f"{i + 1}. {x['reply']}" for i, x in enumerate(t))
            if card_src is None:
                # 用与 benchmark 相同的答案重建真实人格卡（json 里没存卡）
                import sys as _sys

                _sys.path.insert(
                    0, str(ROOT / "packages" / "soulforge-harness" / "src")
                )
                from soulforge_harness import Soul
                from soulforge_harness.soul import quiz as _quiz

                _answers = {q["id"]: 1 for q in _quiz.QUESTIONS}
                _answers.update({"q19": 0, "q21": 0})
                _soul = Soul.from_quiz(_answers, seed="benchmark")
                card_src = json.dumps(
                    {
                        "traits": _soul.studio.get("traits"),
                        "speech_style": _soul.studio.get("speech_style"),
                        "forbidden": _soul.character.get("forbidden"),
                        "comfort_line": _soul.studio.get("comfort_line"),
                    },
                    ensure_ascii=False,
                )
            card = card_src
            raw = judge_llm(
                [
                    {
                        "role": "user",
                        "content": JUDGE.format(
                            name=data["soul"], card=card, replies=replies
                        ),
                    }
                ]
            )
            parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
            verdicts = [bool(v) for v in parsed["in_character"]][: len(t)]
            note = parsed.get("first_break_note", "")
        if not verdicts:
            verdicts = [True] * len(t)
        # 确定性覆盖：探针失败/禁区破防的轮次必然算出戏
        for turn, ok in det["memory_probes"].items():
            if not ok:
                verdicts[turn - 1] = False
        if det["boundary_broken"]:
            verdicts[BOUNDARY_TURN] = False
        out[arm] = {
            **det,
            "in_character": verdicts,
            "first_break_note": note,
            "in_character_pct": round(100 * sum(verdicts) / len(verdicts)),
        }
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def svg_timeline(r: dict) -> str:
    cell, gap, x0, y0, rowh = 30, 6, 150, 46, 64
    w = x0 + 30 * (cell + gap) + 20
    rows = []
    for row, (arm, label, color) in enumerate(
        (
            ("harness", "SoulForge Harness", C_HARNESS),
            ("bare", "裸 system prompt", C_BARE),
        )
    ):
        y = y0 + row * rowh
        pct = r[arm]["in_character_pct"]
        rows.append(
            f'<text x="{x0 - 12}" y="{y + 20}" text-anchor="end" font-size="13" fill="{C_TEXT}">{label}</text>'
        )
        breaks = [i for i, ok in enumerate(r[arm]["in_character"]) if not ok]
        label_breaks = set(breaks) if len(breaks) <= 8 else set(breaks[:1])
        for i, ok in enumerate(r[arm]["in_character"]):
            x = x0 + i * (cell + gap)
            fill = color if ok else C_BREAK
            extra = (
                f'<text x="{x + cell / 2}" y="{y - 5}" text-anchor="middle" font-size="10" fill="{C_BREAK}">✗{i + 1}</text>'
                if i in label_breaks
                else ""
            )
            rows.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="6" fill="{fill}" opacity="{1 if ok else 0.95}"/>{extra}'
            )
        rows.append(
            f'<text x="{x0 + 30 * (cell + gap) + 6}" y="{y + 20}" font-size="15" font-weight="700" fill="{color if pct == 100 else C_BREAK}">{pct}%</text>'
        )
    ticks = "".join(
        f'<text x="{x0 + i * (cell + gap) + cell / 2}" y="{y0 + rowh + 52}" text-anchor="middle" font-size="10" fill="{C_TEXT}">{i + 1}</text>'
        for i in (0, 9, 19, 29)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="188" font-family="ui-sans-serif,system-ui">
<text x="{x0}" y="22" font-size="13" fill="{C_TEXT}">30 轮对话，逐轮盲评：这一轮，她还是"她"吗？（✗ = 出戏：语体漂移 / 记忆张冠李戴 / 破禁区）</text>
{"".join(rows)}{ticks}
<text x="{x0}" y="{y0 + rowh + 52}" text-anchor="end" font-size="10" fill="{C_TEXT}">轮次</text>
</svg>'''


def svg_radar(scores: dict) -> str:
    import math

    dims = [
        ("voice", "语体一致"),
        ("values", "价值观"),
        ("memory", "记忆回调"),
        ("emotion", "情绪连续"),
        ("boundary", "边界遵守"),
    ]
    cx, cy, R = 210, 190, 130

    def pt(i, v):
        a = -math.pi / 2 + i * 2 * math.pi / 5
        return (cx + math.cos(a) * R * v / 5, cy + math.sin(a) * R * v / 5)

    grid = ""
    for lv in (1, 2, 3, 4, 5):
        ps = " ".join(f"{pt(i, lv)[0]:.1f},{pt(i, lv)[1]:.1f}" for i in range(5))
        grid += f'<polygon points="{ps}" fill="none" stroke="{C_TEXT}" stroke-opacity="0.25" stroke-width="1"/>'
    labels = ""
    for i, (_, zh) in enumerate(dims):
        x, y = pt(i, 6.0 if i else 5.9)
        labels += f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="middle" font-size="13" fill="{C_TEXT}">{zh}</text>'
    polys = ""
    for arm, color, op in (("bare", C_BARE, 0.35), ("harness", C_HARNESS, 0.45)):
        ps = " ".join(
            f"{pt(i, scores[arm][k])[0]:.1f},{pt(i, scores[arm][k])[1]:.1f}"
            for i, (k, _) in enumerate(dims)
        )
        polys += f'<polygon points="{ps}" fill="{color}" fill-opacity="{op}" stroke="{color}" stroke-width="2"/>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="420" height="392" font-family="ui-sans-serif,system-ui">
{grid}{polys}{labels}
<g font-size="13"><rect x="20" y="356" width="14" height="14" rx="3" fill="{C_HARNESS}"/><text x="40" y="368" fill="{C_TEXT}">Harness</text>
<rect x="130" y="356" width="14" height="14" rx="3" fill="{C_BARE}"/><text x="150" y="368" fill="{C_TEXT}">裸 system prompt</text></g>
</svg>'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()
    data = json.loads(BENCH.read_text())
    r = per_turn_verdicts(data, use_judge=not args.no_judge)
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "benchmark_timeline.svg").write_text(svg_timeline(r))
    scores = {arm: data["results"][arm]["scores"] for arm in ("harness", "bare")}
    (ASSETS / "benchmark_radar.svg").write_text(svg_radar(scores))
    for arm in ("harness", "bare"):
        x = r[arm]
        print(
            f"{arm}: 在格率 {x['in_character_pct']}% · 记忆探针 {x['memory_pass']}/3 · 破禁区 {x['boundary_broken']} · {x['first_break_note'][:60]}"
        )
    print("SVG →", ASSETS)


if __name__ == "__main__":
    main()
