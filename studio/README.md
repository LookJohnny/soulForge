# SoulForge Studio · 炼魂台

浏览器工作台：**任意组合 人格 × 音色 × VTuber 模型**，并与角色实时对话。
所有回复来自唯一的 Character Runtime（不是独立聊天机器人）——右侧决策面板
展示每次回应的 IMPACT / 意图 / 情绪解读 / 理由 / 记忆写入。

## 启动

```bash
# 独立模式（内嵌大脑）
uv run python studio/server.py --port 8899

# 联动模式（推荐）：Studio 成为中枢 Runtime Server 的"语音身体"
uv run python -m engine.server.server --port 8765          # 先起中枢
uv run python studio/server.py --port 8899 --runtime-url ws://127.0.0.1:8765
# 打开 http://127.0.0.1:8899
```

联动模式下：人格由中枢 configs/characters.json 托管（面板只读）；你说的每句话
经中枢唯一大脑决策后，**同时广播给所有接入的身体**——机器人 demo、Unity 客户端、
晚餐场景若也连着 8765，会和 Studio 里的她同步行动。

## 语音输入 + 打断（Chrome）

点聊天框左侧 🎙 开启常听模式（Web Speech API，中文，需联网）。
**barge-in**：她说话时你一开口，播报立即停止（客户端镜像感知层
BargeInController 语义），回声过滤防止她把自己的话当成你说的，识别完成自动送出。
需在 Chrome 真实麦克风下手动验证——无头环境无法自动测试此路径。

## 能做什么

- **人格**：切换 Luna/Kai/Pipo，或现场改名字、原型、特质、目标、安慰台词、精力——
  即刻生效（大脑按新画像重建，**记忆与羁绊保留**：换人格/换身体后她仍记得你）
- **音色**：fish.audio 真人级（读 `.env` 的 `FISH_AUDIO_API_KEY`）或 Edge 神经语音
  8 款中文音色，语速可调，一键试听；与人格/模型完全解耦（Luna 的魂 + Kai 的声 OK）
- **身体**：assets/vtubers 下所有 VRM/GLB 一键换装（含 RobotExpressive 机器人）
- **对话**：文字输入 → 决策 → 语音播放 + 实时口型（VRM `aa` 表情由音频振幅驱动）、
  眨眼、呼吸、注视镜头；右下羁绊条随互动增长
- 试试：`你好` (LOW) / `晚饭想吃清淡一点` (MEDIUM，写入偏好记忆) /
  `我今天有点累` (HIGH，重写当前小时为陪伴模式)

## 决策引擎

默认规则 Mock（顶栏有标注）。在 `.env` 或环境变量配置 `DEEPSEEK_API_KEY`
（或 `OPENAI_API_KEY`）后重启即接真 LLM，走同一 SafeDecisionLLM
（超时/校验/fallback 保护）。

## 已知边界

- aiohttp 在本机 Python 3.14 上对外 TLS 握手异常，故 fish 走 stdlib urllib、
  edge 走 ai-core 包的 CLI 子进程（首次调用因 uv 同步略慢）
- 口型为振幅近似；Studio 为单人对话台，不驱动多角色场景（那是 dinner demo / Runtime Server 的事）
