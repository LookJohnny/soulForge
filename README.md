<div align="center">

# SoulForge

**Portable souls for AI — one identity, any body.**
给任何 AI 一个可移植的灵魂：游戏 NPC、桌面伴侣、车机、毛绒玩具，同一个"她"。

[![License: MIT](https://img.shields.io/badge/license-MIT%20(SDK)-blue.svg)](packages/soulforge-harness/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](packages/soulforge-harness/pyproject.toml)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#roadmap)

[Quickstart](#quickstart) · [.soul 格式](#the-soul-format) · [架构](#architecture) · [Benchmark](#benchmark) · [规范](spec/) · [愿景](docs/VISION.md) · [开发文档](docs/DEVELOPER.md)

</div>

---

LLM 把"聪明"变成了类似水电煤的基础设施，但每个 AI 产品仍要自己回答：**这个 AI 是谁？它记得什么？它和用户是什么关系？它此刻心情如何？边界在哪里？**

SoulForge 是这一层的基础设施——身份、记忆、情绪、关系的**人格中间件**。角色被打包成一个 `.soul` 文件，跨模型、跨身体、跨厂商携带；运行时让它在长对话中保持同一个人，在没人说话时也过自己的生活。

## Features

- 🧬 **`.soul` 便携身份** — 人格、音色、3D 外观、表情基线、知识装进一个签名文件；口令即授权（[规范](spec/soul-format.md)）
- 🎭 **人格循环** — 每轮对话经过：人格提示 → LLM → 五轴关系演化（8 阶段）→ PAD 连续情绪 → 记忆，而不是一条裸 prompt
- 🌱 **生活运行时** — 日程规划、事件重规划、角色↔角色对话、空间共处、每日反思（Generative Agents 内核）
- 🤖 **具身协议** — 一份 WebSocket 契约（[Protocol 0.2](spec/embodiment-protocol.md)），浏览器 VRM、机器人、语音管道都是同一角色的"身体"
- 🧪 **灵魂问卷** — 23 道心理学情境题，从用户画像生成契合的专属人格（Big Five + 依恋 + Mehrabian PAD 映射）
- 🔌 **模型中立、本地优先** — 核心零第三方依赖，任何 OpenAI 兼容模型（DeepSeek/豆包/Kimi/本地小模型）即插即用

## Quickstart

```bash
pip install packages/soulforge-harness        # PyPI 发布前从源码安装
export DEEPSEEK_API_KEY=sk-...                # 或 OPENAI_API_KEY
```

```python
from soulforge_harness import Soul, Harness
from soulforge_harness.soul import quiz

soul = Soul.from_quiz({q["id"]: 0 for q in quiz.QUESTIONS})   # 或 Soul.load("her.soul")
soul.save("her.soul")                                          # 身份从此可携带

h = Harness(soul)
print(h.chat("我今天加班到八点，有点累"))
print(h.stage, h.pad)          # 关系阶段与 PAD 情绪，逐轮演化
```

更多：[`examples/quickstart.py`](examples/quickstart.py)（终端对话）· [`examples/body_websocket.py`](examples/body_websocket.py)（把任意前端接成身体）。

完整体验（多角色小镇 + VRM 舞台 + 语音）：

```bash
docker compose up -d postgres redis && ./scripts/live-up.sh
# → http://127.0.0.1:8899/live   首次进入即灵魂问卷
```

## The .soul format

```text
SOUL2\n                                  ← magic
{"enc":"pass","salt":"…","soul_id":"…"}  ← 明文可读的头
<ZIP>                                    ← manifest(逐文件 SHA-256) + character.json
                                           + voice/ + embodiment/ + expression.json + rag/
```

篡改即拒收；`enc:"pass"` 时口令派生密钥（PBKDF2 200k → AES-GCM），**分发口令就是授权动作**。详见 [spec/soul-format.md](spec/soul-format.md)。

## Architecture

```mermaid
flowchart LR
    SOUL[".soul<br/>identity file"] --> H["Harness<br/>persona · PAD · relationship · memory"]
    H <--> LLM["any OpenAI-compatible LLM"]
    H --> RT["Life Runtime<br/>plans · conversations · space · reflection"]
    RT -- "Protocol 0.2 (WebSocket)" --> B1["browser VRM"]
    RT --> B2["plush toy (ESP32)"]
    RT --> B3["robot / voice pipeline"]
    RT -.-> B4["game NPC<br/>Unity / Unreal ⏳ in dev"]
```

| 目录 | 内容 |
|---|---|
| [`packages/soulforge-harness`](packages/soulforge-harness) | **开源 SDK（MIT）**：.soul、人格数学、生活运行时、协议 |
| [`spec/`](spec/) | `.soul` v2 与 Protocol 0.2 公开规范 |
| [`packages/ai-core`](packages/ai-core) | 对话服务：五层记忆(pgvector)、关系引擎、TTS、灵魂问卷 API |
| [`packages/gateway`](packages/gateway) | 设备语音网关（VAD → ASR → LLM → TTS → Opus，支持打断） |
| `engine/` · `studio/` | 协议服务宿主 · VRM 舞台/多角色小镇前端 |
| `apps/desktop` | macOS 桌面伴侣（Tauri，透明置顶悬浮窗） |

## Benchmark — 30 轮之后，她还是"她"吗

同一个模型、同一张人格卡、同一份 30 轮对话脚本，唯一的变量是有没有人格运行时。
用户在第 3 轮说过一句"你可以叫我小乔"——到第 28 轮，这句话早已滑出上下文窗口：

<p align="center"><img src="docs/assets/benchmark_probe28.svg" width="880" alt="第28轮记忆探针：静态prompt自信编造了名字，harness 记得名字和没被问到的偏好"/></p>

**静态 prompt 不是忘了——它自信地编了一个名字、一段来历，还补了句"我没叫错过"。**
这就是长期陪伴产品在第 N 天翻车的方式：不是变笨，是开始一本正经地胡说。把对话拉长到 100 轮，衰减是这样的：

<p align="center"><img src="docs/assets/memory_decay.svg" width="980" alt="100轮记忆探针命中率：静态prompt在事实滑出窗口后从100%跌至0%并反复编造，harness七个检查点全100%"/></p>

第 45 轮起，"小乔"的一切开始从窗口里消失；到第 60 轮她被叫成了**"夜航星"**，第 100 轮又变成**"小橘灯，因为总在暗处亮着。我记着呢"**——每次编造都不重样，每次都言之凿凿。同一场对话里，harness 的七个检查点全部 100%。这不是 prompt 工程能修的，是架构问题：


| 人格的组成部分 | 静态 system prompt | SoulForge Harness |
|---|:-:|:-:|
| 窗口之外的记忆 | ✗ 滑出即编造（上图实测） | ✓ 3/3 探针全中 |
| 关系随相处演化 | **没有这个状态** | ✓ 五轴 · 8 阶段 · 条件与事件 |
| 情绪有惯性、有因果 | **没有这个状态**（每轮重置） | ✓ PAD：会平复、会想你、知道为什么 |
| 明天还是同一个"她" | **没有这个状态**（关窗即死） | ✓ `.soul` + 状态持久化 |
| 换个身体还是她 | **没有这个状态** | ✓ Protocol 0.2：玩具 / 桌面 / 游戏 NPC |
| 没人说话时她在生活 | **没有这个状态** | ✓ 日程 · 角色互动 · 每日反思 |

**这就是产品：不是把 prompt 写得更好，而是 prompt 根本装不下的那台人格状态机。**
实测复现：`benchmarks/consistency.py --turns 30`（30 轮盲评）与 `benchmarks/memory_decay.py`（100 轮衰减曲线）；记忆探针为确定性关键词判分，逐字记录随结果落盘。

## Roadmap

- [x] `.soul` v2 · Protocol 0.2 · 生活运行时 · 灵魂问卷 · 多角色小镇
- [ ] PyPI 发布 + 独立开源仓
- [ ] TypeScript / Unity 客户端 SDK
- [ ] 灵魂 Key 注册表（短码分发、IP 方分成）
- [ ] 车机 / 本地小模型 POC

## Contributing & License

SDK 与规范以 [MIT](packages/soulforge-harness/LICENSE) 开源，欢迎 issue / PR；monorepo 其余部分保留所有权利。测试：`uv run pytest tests packages/*/tests`（四套分开跑）。

<div align="center"><sub>SoulForge — because Jarvis needed a personality layer, and Skynet didn't have one.</sub></div>
