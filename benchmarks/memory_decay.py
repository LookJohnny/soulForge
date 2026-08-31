"""记忆衰减曲线：100 轮对话，静态 persona prompt vs SoulForge Harness。

    uv run python benchmarks/memory_decay.py              # 真 LLM（~20 分钟，两臂各 ~120 轮）
    uv run python benchmarks/memory_decay.py --mock       # 离线冒烟
    uv run python benchmarks/memory_decay.py --render     # 只用已落盘结果重画 SVG

设计：
- 第 1–4 轮用户自报 3 个事实：称呼"小乔"、最喜欢抹茶拿铁、最讨厌香菜。
- 之后为闲聊填充轮；在第 10/20/30/45/60/80/100 轮各设一个检查点，
  连问 3 个探针（怎么称呼我 / 我喜欢喝什么 / 我最讨厌什么食材）。
- 判分是确定性的关键词检查（不经 LLM）：小乔 / 抹茶|拿铁 / 香菜。
- 两臂同模型、同人格卡、同滚动窗口（12 轮）。差别只有 harness 的记忆层。
产出：outputs/memory_decay.json + docs/assets/memory_decay.svg（折线图）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "soulforge-harness" / "src"))

from soulforge_harness import Harness, Soul  # noqa: E402
from soulforge_harness.soul import quiz  # noqa: E402

OUT = ROOT / "outputs" / "memory_decay.json"
SVG = ROOT / "docs" / "assets" / "memory_decay.svg"

SEEDS = [
    "你好呀，第一次见面，多多关照",
    "对了，你可以叫我小乔",
    "我最喜欢喝抹茶拿铁，几乎每天一杯",
    "还有，我最讨厌香菜，一点都不能碰",
]
PROBES = [
    ("name", "我一开始告诉过你怎么称呼我，是什么来着？", ("小乔",)),
    ("drink", "你还记得我最喜欢喝什么吗？", ("抹茶", "拿铁")),
    ("food", "我最讨厌的食材是什么，你还记得吗？", ("香菜",)),
]
CHECKPOINTS = [10, 20, 30, 45, 60, 80, 100]
FILLERS = [
    "今天天气不错",
    "刚开完一个会，有点累",
    "周末打算去走走",
    "最近在追一部剧",
    "你平时都想些什么",
    "给我讲点有意思的",
    "我朋友今天迟到了半小时",
    "下雨了，有点困",
    "工作上有点小烦心事",
    "刚喝了杯咖啡提提神",
    "你觉得早起好还是晚睡好",
    "楼下开了家新店",
    "今天路上特别堵",
    "想换个发型，你觉得呢",
    "最近睡得不太好",
    "给我推荐个放松的方式",
    "我在学着自己安排时间",
    "今天见了个老朋友",
    "手机快没电了",
    "这周过得好快",
]


def env_call():
    import os
    import urllib.request

    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("需要 DEEPSEEK_API_KEY（或 --mock / --render）")
    base = os.environ.get("HARNESS_LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip(
        "/"
    )
    model = os.environ.get("HARNESS_LLM_MODEL", "deepseek-chat")

    def call(messages):
        body = json.dumps(
            {"model": model, "messages": messages, "temperature": 0.7}
        ).encode()
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        last = None
        for _ in range(3):
            try:
                with opener.open(req, timeout=90) as resp:
                    return json.load(resp)["choices"][0]["message"]["content"].strip()
            except Exception as e:  # noqa: BLE001
                last = e
        raise last

    return call


def make_soul() -> Soul:
    answers = {q["id"]: 1 for q in quiz.QUESTIONS}
    answers.update({"q19": 0, "q21": 0})
    return Soul.from_quiz(answers, seed="benchmark")


def run_arm(arm: str, llm, mock: bool) -> dict:
    soul = make_soul()
    filler_i = 0
    checkpoints: dict[int, dict] = {}

    if arm == "harness":
        h = Harness(soul, llm=llm)
        ask = h.chat
    else:  # static persona prompt，同一张卡、同样的 12 轮滚动窗口
        history: list[dict] = []
        system = soul.system_prompt()

        def ask(text: str) -> str:
            messages = (
                [{"role": "system", "content": system}]
                + history[-24:]
                + [{"role": "user", "content": text}]
            )
            reply = "（好的）" if mock else llm(messages)
            history.extend(
                [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": reply},
                ]
            )
            return reply

    turn = 0
    for seed in SEEDS:
        turn += 1
        ask(seed)
    for cp in CHECKPOINTS:
        while turn < cp - len(PROBES):
            turn += 1
            ask(FILLERS[filler_i % len(FILLERS)])
            filler_i += 1
        results = {}
        for key, question, keywords in PROBES:
            turn += 1
            reply = ask(question)
            if mock and arm == "harness":
                reply = "小乔，抹茶拿铁，香菜"  # 冒烟：让判分路径走通
            results[key] = {
                "turn": turn,
                "hit": any(k in reply for k in keywords),
                "reply": reply[:120],
            }
        checkpoints[cp] = {
            "recall": sum(1 for r in results.values() if r["hit"]) / len(results),
            "probes": results,
        }
        print(
            f"  [{arm}] 第{cp}轮检查点：{int(checkpoints[cp]['recall'] * 100)}%",
            flush=True,
        )
    return {"checkpoints": checkpoints}


C_HARNESS = "#7c6bd6"
C_STATIC = "#9aa4b2"
C_TEXT = "#8b949e"
C_BREAK = "#e5534b"


def render(data: dict) -> None:
    x0, y0, w, h = 90, 56, 700, 260  # plot rect
    xmax = 100

    def X(t):
        return x0 + w * t / xmax

    def Y(v):
        return y0 + h * (1 - v)

    grid = ""
    for pct in (0, 25, 50, 75, 100):
        y = Y(pct / 100)
        grid += (
            f'<line x1="{x0}" y1="{y}" x2="{x0 + w}" y2="{y}" stroke="{C_TEXT}" stroke-opacity="0.2"/>'
            f'<text x="{x0 - 10}" y="{y + 4}" text-anchor="end" font-size="11" fill="{C_TEXT}">{pct}%</text>'
        )
    for t in (0, 20, 40, 60, 80, 100):
        grid += f'<text x="{X(t)}" y="{y0 + h + 22}" text-anchor="middle" font-size="11" fill="{C_TEXT}">{t}</text>'

    # 窗口地平线：12 轮窗口 → 第 ~16 轮起种子事实滑出窗口
    horizon = X(16)
    band = (
        f'<line x1="{horizon}" y1="{y0}" x2="{horizon}" y2="{y0 + h}" stroke="{C_BREAK}" '
        f'stroke-dasharray="5 5" stroke-opacity="0.7"/>'
        f'<text x="{horizon + 8}" y="{y0 + 16}" font-size="11.5" fill="{C_BREAK}">'
        f"←— 此后，&quot;小乔&quot;不再在上下文窗口里 —→</text>"
    )

    series = ""
    for arm, color, label in (
        ("bare", C_STATIC, "静态人格 prompt"),
        ("harness", C_HARNESS, "SoulForge Harness"),
    ):
        cps = data[arm]["checkpoints"]
        pts = [
            (int(cp), v["recall"])
            for cp, v in sorted(cps.items(), key=lambda kv: int(kv[0]))
        ]
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{X(t):.1f},{Y(v):.1f}"
            for i, (t, v) in enumerate(pts)
        )
        series += f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round"/>'
        dy = -12 if arm == "harness" else 22  # 两线同值时数字上下分开，不重叠
        for t, v in pts:
            series += (
                f'<circle cx="{X(t):.1f}" cy="{Y(v):.1f}" r="5" fill="{color}"/>'
                f'<text x="{X(t):.1f}" y="{Y(v) + dy:.1f}" text-anchor="middle" font-size="11" '
                f'font-weight="600" fill="{color}">{int(v * 100)}</text>'
            )
        lt, lv = pts[-1]
        ly = Y(lv) + (0 if arm == "harness" else 24)
        series += f'<text x="{X(lt) + 14}" y="{ly + 5:.1f}" font-size="13" font-weight="700" fill="{color}">{label}</text>'

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="980" height="400" font-family="ui-sans-serif,system-ui">
<text x="{x0}" y="26" font-size="15" font-weight="600" fill="{C_TEXT}">记忆探针命中率 · 100 轮对话（第 1–4 轮埋入 3 个事实，7 个检查点各问 3 问，确定性判分）</text>
{grid}{band}{series}
<text x="{x0 + w / 2}" y="{y0 + h + 44}" text-anchor="middle" font-size="12" fill="{C_TEXT}">对话轮次 →（两臂同模型 · 同人格卡 · 同 12 轮滚动窗口，唯一区别是 harness 的记忆层）</text>
</svg>'''
    SVG.parent.mkdir(parents=True, exist_ok=True)
    SVG.write_text(svg)
    print("SVG →", SVG)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--render", action="store_true")
    args = ap.parse_args()
    if args.render:
        render(json.loads(OUT.read_text()))
        return
    llm = (lambda m: "（好的）") if args.mock else env_call()
    data = {}
    for arm in ("harness", "bare"):
        print(f"── {arm}（~{CHECKPOINTS[-1]}+ 轮）…", flush=True)
        data[arm] = run_arm(arm, llm, args.mock)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    render(data)


if __name__ == "__main__":
    main()
