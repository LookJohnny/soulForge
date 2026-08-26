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

## Live 模式：VRM 作为 gateway 的身体（`/live`）

`http://127.0.0.1:8899/live` 不用 Studio 自带大脑，而是以 **web_audio 设备**身份接入
gateway（默认 `ws://<host>:8080/ws`），与小智 ESP32 平级：ASR / 五层记忆 / PAD /
打断 / TTS 全走 gateway 真实管道，本页只做渲染。

```bash
uv run python -m ai_core.main            # 8100
uv run python -m gateway.main            # 8080
uv run python studio/server.py --port 8899 && open http://127.0.0.1:8899/live
```

- 下行：24kHz 裸 Opus 帧 → WebCodecs `AudioDecoder` → 口型（RMS→`aa`）
- 情绪：gateway 每轮推 `{"type":"emotion","pad":{p,a,d}}` → `lib/pad_expression.js`
  （`face_engine.select_recipe` 的逐点等价移植，`test_pad_expression_parity.py` 钉死）
  → 配方 key → VRM 表情权重 + 头部姿态，逐帧指数阻尼；情绪惯性/淡去与舵机脸同一时间常数
- 上行：🎙 用 WebCodecs `AudioEncoder` 编 Opus（服务端 VAD 断句）；需 Chrome/Edge
- 模型缺表情通道（如 open_source_avatars 里多数只有口型+眨眼）时自动退化为只动头部
- 共享库 `web/lib/vrm_body.js`（加载/注视/呼吸/眨眼/fidget/VRMA/表情阻尼）是后续
  studio.js 与 demo 渲染器收敛的目标
- 吸收自 aikeya（MIT，`assets/animations/LICENSE-aikeya.txt`）：5 个 idle 动捕片段
  轮换（不连续重复、1–2 循环后抖动切换、忙时推迟）+ `talking.vrma` 随说话 crossfade；
  VRM0/1 手臂静息姿态符号翻转；`lib/lipsync.js` 四频段→五视素口型；非对称眨眼；
  头部投影气泡；渲染循环内 resize；`utsuwa.vrm` 默认模型
- 页面即完整陪伴应用壳：关系 HUD（`control:relationship`）、情绪与原因、事件场景卡
  （`control:event` → 回传 `event_choice`）、记忆图面板（等 ai-core 接口）、设置抽屉
- 冒烟测试：`pnpm test:studio`（自起 studio + `studio/tests/fake_gateway.py`，Playwright
  无头 Chromium 断言模型/idle/口型/气泡/HUD/事件卡，截图到 `outputs/live_smoke.png`）

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
