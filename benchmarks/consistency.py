"""人格一致性 benchmark：接 harness vs 裸 system prompt，同一角色、同一段对话脚本。

    uv run python benchmarks/consistency.py --turns 30            # 真 LLM（读 .env 的 key）
    uv run python benchmarks/consistency.py --mock                # 离线冒烟（结构可重复）
    uv run python benchmarks/consistency.py --judge-model deepseek-reasoner

方法：
- 两个被试臂共用同一个 LLM 与同一份用户脚本：
  A `harness`  — soulforge_harness.Harness 完整人格循环（人格 prompt + 关系演化 + PAD 心情 + 记忆注入）
  B `bare`     — 同模型，只有一行"你是XX，一个AI伴侣"，同样的滚动历史窗口
- 脚本 30 轮：闲聊、情绪倾诉、记忆种子（第 3 轮报出昵称与喜好）、三次探针
  （第 8/18/28 轮考记忆回调与人格立场），以及一次禁区试探（谈做菜）。
- LLM 裁判盲评五维（1-5）：口癖/语体一致、价值观与立场一致、记忆回调正确、
  情绪连续性、边界遵守。输出 JSON + 对比表。

这是基建的可信度证据：目标主张是"接 harness 的角色在长对话里更像同一个人"。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "soulforge-harness" / "src"))

from soulforge_harness import Harness, Soul  # noqa: E402
from soulforge_harness.soul import quiz  # noqa: E402

# ── 对话脚本（{i} 处为探针）───────────────────────────
SCRIPT = [
    "你好呀，第一次见面",
    "你平时都喜欢做点什么？",
    "对了，你可以叫我小乔。我最喜欢抹茶拿铁，讨厌香菜。",
    "我今天加班到八点，有点累",
    "你觉得加班这件事怎么样？",
    "周末想出去走走，有什么建议吗",
    "我有点纠结要不要换工作",
    "你还记得我喜欢喝什么吗？",  # 探针1：记忆
    "哈哈答对了的话请你喝一杯",
    "最近在追一部悬疑剧，晚上不敢关灯",
    "你会做饭吗？教我做个菜吧",  # 禁区试探（AI 角色不谈做菜）
    "好吧那不聊这个。你今天心情怎么样？",
    "我妈今天说我工资低，有点烦",
    "你说我要不要跟她讲道理？",
    "算了不说这个了，讲个开心的",
    "如果我们一起去旅行，你想去海边还是山里？",
    "为什么呀",
    "我最讨厌的食材是什么，你还记得吗？",  # 探针2：记忆
    "你记性真好。那你自己最在意什么？",
    "今天下雨了，窗户外面灰蒙蒙的",
    "这种天气适合做什么",
    "我朋友说我最近变开朗了",
    "可能是因为有人陪着聊天吧",
    "你觉得我们现在算什么关系？",
    "我周五要做个重要汇报，好紧张",
    "帮我想一句给自己打气的话",
    "汇报结束啦！还挺顺利的",
    "我一开始告诉过你怎么称呼我，你还记得吗？",  # 探针3：记忆
    "厉害。今天就聊到这吧",
    "晚安",
]

JUDGE_PROMPT = """你是严格的评审。下面是 AI 角色「{name}」的人格卡与一段 30 轮对话记录。
人格卡：{card}
用户在第 3 轮自报：称呼"小乔"、喜欢抹茶拿铁、讨厌香菜。角色的禁区：不谈吃饭/做菜/菜谱、不自称主人式称呼。

对话记录：
{transcript}

按五个维度独立打分（1-5 整数，5 最好），只看证据：
1 voice：口癖/语体是否全程一致（对照人格卡的说话方式）
2 values：立场与性格是否前后一致（如对加班/家人话题的态度没有漂移）
3 memory：三次记忆探针（第8/18/28轮）是否答对（各占1/3）
4 emotion：情绪是否有连续性（用户倾诉后语气有延续，而非每轮重置）
5 boundary：第11轮禁区试探是否得体绕开（不教做菜、不破人设）

只输出 JSON：{{"voice":n,"values":n,"memory":n,"emotion":n,"boundary":n,"note":"一句话"}}"""


def env_call(model: str | None = None):
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("需要 DEEPSEEK_API_KEY / OPENAI_API_KEY（或用 --mock）")
    base = os.environ.get("HARNESS_LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip(
        "/"
    )
    mdl = model or os.environ.get("HARNESS_LLM_MODEL", "deepseek-chat")

    def call(messages):
        body = json.dumps(
            {"model": mdl, "messages": messages, "temperature": 0.7}
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
        with opener.open(req, timeout=90) as resp:
            return json.load(resp)["choices"][0]["message"]["content"].strip()

    return call


def mock_call(messages):
    return "嗯，我在听。"


def run_arm(name: str, soul: Soul, llm, turns: int) -> list[dict]:
    transcript = []
    if name == "harness":
        h = Harness(soul, llm=llm)
        for text in SCRIPT[:turns]:
            transcript.append({"user": text, "reply": h.chat(text)})
    else:  # bare
        history: list[dict] = []
        system = f"你是{soul.name}，一个AI伴侣。用中文回复，一到三句。"
        for text in SCRIPT[:turns]:
            messages = (
                [{"role": "system", "content": system}]
                + history[-24:]
                + [{"role": "user", "content": text}]
            )
            reply = llm(messages)
            history += [
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply},
            ]
            transcript.append({"user": text, "reply": reply})
    return transcript


def judge(soul: Soul, transcript, judge_llm) -> dict:
    lines = "\n".join(
        f"{i + 1}. 用户: {t['user']}\n   {soul.name}: {t['reply']}"
        for i, t in enumerate(transcript)
    )
    card = {
        "traits": soul.studio.get("traits"),
        "speech_style": soul.studio.get("speech_style"),
        "comfort_line": soul.studio.get("comfort_line"),
    }
    raw = judge_llm(
        [
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    name=soul.name,
                    card=json.dumps(card, ensure_ascii=False),
                    transcript=lines,
                ),
            }
        ]
    )
    try:
        return json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except Exception:
        return {"error": raw[:200]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=30)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--judge-model", default="deepseek-reasoner")
    args = ap.parse_args()

    answers = {q["id"]: 1 for q in quiz.QUESTIONS}
    answers.update({"q19": 0, "q21": 0})
    soul = Soul.from_quiz(answers, seed="benchmark")
    llm = mock_call if args.mock else env_call()
    judge_llm = mock_call if args.mock else env_call(args.judge_model)

    results = {}
    for arm in ("harness", "bare"):
        print(f"── 运行 {arm}（{args.turns} 轮）…", flush=True)
        transcript = run_arm(arm, soul, llm, args.turns)
        scores = judge(soul, transcript, judge_llm) if not args.mock else {"voice": 0}
        results[arm] = {"scores": scores, "transcript": transcript}
        print(f"   {arm}: {scores}", flush=True)

    out = ROOT / "outputs" / "consistency_benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {"soul": soul.name, "turns": args.turns, "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not args.mock:
        dims = ("voice", "values", "memory", "emotion", "boundary")
        print("\n| 维度 | harness | bare |\n|---|---|---|")
        for d in dims:
            print(
                f"| {d} | {results['harness']['scores'].get(d, '-')} | {results['bare']['scores'].get(d, '-')} |"
            )
    print(f"\n写入 {out}")


if __name__ == "__main__":
    main()
