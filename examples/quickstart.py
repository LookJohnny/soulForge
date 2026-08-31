"""soulforge-harness quickstart — 给任何 LLM 一个灵魂，20 行以内。

    export DEEPSEEK_API_KEY=sk-...          # 或 OPENAI_API_KEY
    uv run python examples/quickstart.py    # 或普通 venv: pip install -e packages/soulforge-harness

没有现成 .soul？本脚本先用灵魂问卷即时生成一个（全选直觉答案），
然后进入终端对话：她的性格、你们的关系阶段、她的心情都在逐轮演化。
"""

from soulforge_harness import Harness, Soul
from soulforge_harness.soul import quiz

answers = {q["id"]: 0 for q in quiz.QUESTIONS}  # 演示用：全选第一个选项
soul = Soul.from_quiz(answers, seed="quickstart")
soul.save("companion.soul")  # 她的身份从此可携带：跨模型、跨身体、跨机器
print(
    f"✦ {soul.name} 醒来了（{soul.studio.get('role_label', '')}）。输入 quit 退出。\n"
)

h = Harness(soul)
while (text := input("你> ").strip()) not in ("quit", "exit"):
    if not text:
        continue
    print(f"{soul.name}> {h.chat(text)}")
    print(f"   [关系 {h.stage} · 心情 P{h.pad.p:+.2f} A{h.pad.a:+.2f} D{h.pad.d:+.2f}]")
