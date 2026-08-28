#!/usr/bin/env python3
"""LLM bake-off for character dialogue: same seeds, several providers, blind-review output.

For each provider it runs the real engine conversation loop (Luna ↔ Kai, per-agent
decisions, the roommate prompt) on fixed topic seeds and a user-utterance reaction,
then prints the lines with per-line latency and a token/cost estimate.

    uv run python scripts/llm_bakeoff.py                 # all configured providers
    uv run python scripts/llm_bakeoff.py deepseek kimi   # subset

Providers are read from .env: DEEPSEEK_API_KEY, MOONSHOT_API_KEY (Kimi),
DASHSCOPE_API_KEY (Qwen), VOLC_API_KEY (Doubao, needs VOLC_MODEL endpoint id).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.planner import CompanionRuntime, Event, EventKind, WorldState, load_personas  # noqa: E402
from engine.planner.conversation import SocialPolicy  # noqa: E402
from engine.planner.llm_interface import OpenAICompatibleBehaviorLLM  # noqa: E402

SEEDS = [
    "认真辩一次：机器人会不会做梦",
    "如果能给用户准备一个小惊喜，做什么、怎么藏",
]
USER_LINES = ["我今天加班到八点，有点累", "你觉得我该怎么放松一下？"]

# price per 1M tokens (in+out averaged, CNY) — rough public list prices, for a feel only
PROVIDERS = {
    "deepseek": dict(
        env="DEEPSEEK_API_KEY",
        base="https://api.deepseek.com/v1",
        models=["deepseek-chat"],
        price=1.5,
    ),
    "deepseek-v4-flash": dict(
        env="DEEPSEEK_API_KEY",
        base="https://api.deepseek.com/v1",
        models=["deepseek-v4-flash"],
        price=1.0,
    ),
    "deepseek-v4-pro": dict(
        env="DEEPSEEK_API_KEY",
        base="https://api.deepseek.com/v1",
        models=["deepseek-v4-pro"],
        price=4.0,
    ),
    "deepseek-reasoner": dict(
        env="DEEPSEEK_API_KEY",
        base="https://api.deepseek.com/v1",
        models=["deepseek-reasoner"],
        price=8.0,
    ),
    # Kimi: one entry per model so each shows up as its own column
    "kimi-k2-turbo": dict(
        env="MOONSHOT_API_KEY",
        base="https://api.moonshot.cn/v1",
        models=["kimi-k2-turbo-preview"],
        price=6.0,
    ),
    "kimi-k2": dict(
        env="MOONSHOT_API_KEY",
        base="https://api.moonshot.cn/v1",
        models=["kimi-k2-0905-preview", "kimi-k2-0711-preview"],
        price=4.0,
    ),
    "kimi-k2-thinking": dict(
        env="MOONSHOT_API_KEY",
        base="https://api.moonshot.cn/v1",
        models=["kimi-k2-thinking"],
        price=8.0,
    ),
    "moonshot-v1": dict(
        env="MOONSHOT_API_KEY",
        base="https://api.moonshot.cn/v1",
        models=["moonshot-v1-8k"],
        price=12.0,
    ),
    "qwen": dict(
        env="DASHSCOPE_API_KEY",
        base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=["qwen-plus", "qwen3-235b-a22b-instruct-2507"],
        price=1.2,
    ),
    "doubao": dict(
        env="VOLC_API_KEY",
        base="https://ark.cn-beijing.volces.com/api/v3",
        models=[os.environ.get("VOLC_MODEL", "")],
        price=1.0,
    ),
}


def _dotenv():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


class Timed(OpenAICompatibleBehaviorLLM):
    """Wraps the engine client to record wall time + rough token count per call."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls: list[dict] = []

    def _chat(self, prompt: str) -> str:
        t0 = time.perf_counter()
        raw = super()._chat(prompt)
        self.calls.append(
            {"s": time.perf_counter() - t0, "tokens": (len(prompt) + len(raw)) / 1.6}
        )
        return raw


def pick_model(name: str, cfg: dict) -> tuple[Timed, str] | None:
    key = os.environ.get(cfg["env"])
    if not key:
        return None
    for model in cfg["models"]:
        if not model:
            continue
        llm = Timed(key, cfg["base"], model)
        try:
            llm._chat('Reply with the single word OK. {"ping":1}')
            return llm, model
        except Exception as exc:  # wrong model id / auth / network
            print(f"   {name}:{model} unavailable ({str(exc)[:80]})")
    return None


def run(name: str, cfg: dict) -> dict | None:
    picked = pick_model(name, cfg)
    if picked is None:
        print(f"── {name}: no key / no reachable model, skipped")
        return None
    llm, model = picked
    print(f"\n══ {name} · {model}")
    out = {"provider": name, "model": model, "conversations": [], "user": []}
    for i, seed in enumerate(SEEDS):
        rt = CompanionRuntime(
            load_personas(),
            WorldState(sim_minute=21 * 60 + i * 30),
            llm=llm,
            social_policy=SocialPolicy(cooldown_min=0),
        )
        rt.tick(21 * 60 + i * 30)
        rt.world.space.move("luna", "sofa")
        rt.world.space.move("kai", "sofa")
        n0 = len(llm.calls)
        conv = rt.start_conversation("luna", "kai", topic=seed, max_turns=4)
        rt.run(21 * 60 + i * 30, 6)
        lines = [
            (
                ln.agent_id,
                ln.text,
                llm.calls[n0 + j]["s"] if n0 + j < len(llm.calls) else None,
            )
            for j, ln in enumerate(conv.lines)
        ]
        out["conversations"].append(
            {"seed": seed, "lines": lines, "end": conv.end_reason}
        )
        print(f"  ▸ 种子：{seed}")
        for agent, text, s in lines:
            print(
                f"    [{agent}] {text}   ({s:.1f}s)" if s else f"    [{agent}] {text}"
            )
    rt = CompanionRuntime(load_personas(), WorldState(sim_minute=20 * 60), llm=llm)
    rt.tick(20 * 60)
    for text in USER_LINES:
        n0 = len(llm.calls)
        rt.push_event(
            Event(
                t_min=20 * 60 + 1,
                kind=EventKind.USER_UTTERANCE,
                source="user",
                text=text,
                target_agent="luna",
            )
        )
        rt.run(20 * 60 + 1, 2)
        said = [
            t.detail["dialogue"]
            for t in rt.trace
            if t.kind == "dialogue" and t.agent_id == "luna"
        ][-1:]
        s = llm.calls[n0]["s"] if n0 < len(llm.calls) else None
        out["user"].append({"q": text, "a": said[0] if said else "", "s": s})
        print(
            f"  ▸ 用户：{text}\n    [luna] {said[0] if said else '(无台词)'}   ({s:.1f}s)"
            if s
            else f"  ▸ 用户：{text}\n    [luna] {said[0] if said else '(无台词)'}"
        )
    calls = llm.calls
    lat = sorted(c["s"] for c in calls)
    tokens = sum(c["tokens"] for c in calls)
    out["stats"] = {
        "calls": len(calls),
        "p50_s": round(lat[len(lat) // 2], 2) if lat else None,
        "max_s": round(lat[-1], 2) if lat else None,
        "est_tokens": int(tokens),
        "est_cost_cny": round(tokens / 1e6 * cfg["price"], 4),
    }
    print(
        f"  ── {len(calls)} 次调用 · p50 {out['stats']['p50_s']}s · 最慢 {out['stats']['max_s']}s · ≈{int(tokens)} tokens ≈ ¥{out['stats']['est_cost_cny']}"
    )
    return out


if __name__ == "__main__":
    _dotenv()
    names = sys.argv[1:] or list(PROVIDERS)
    results = [r for n in names if (r := run(n, PROVIDERS[n]))]
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "llm_bakeoff.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2)
    )
    print("\n写入 outputs/llm_bakeoff.json")
