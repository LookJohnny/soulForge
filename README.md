# SoulForge - AI 灵魂注入平台

> 为任何设备注入独一无二的 AI 灵魂：性格、声音、情感、记忆，一个都不少。

SoulForge 是一个通用 AI 人格引擎平台。为毛绒玩具、耳机、手机 App、桌面应用、智能音箱等任何设备注入有灵魂的 AI 角色——不只是问答，而是有情感、有记忆、有关系进化的真实陪伴。

**支持的设备类型**: 小智 ESP32-S3 / 毛绒玩具 / 蓝牙耳机 / 手机 App / 桌面客户端 (Tauri) / 智能音箱 / 网页 / **VRM 虚拟形象 (浏览器 + 桌面悬浮伴侣)**
**支持的角色类型**: 动物角色 / 人类角色(学长/朋友) / 幻想角色(精灵/机器人) / 抽象助手

## 架构

```
┌─────────────────────────────────────────────────────┐
│      设备端 (玩具/耳机/手机/电脑/音箱/网页)            │
└────────────────────┬────────────────────────────────┘
                     │ WebSocket / HTTPS
┌────────────────────▼────────────────────────────────┐
│              Gateway (协议适配层)                      │
│   Xiaozhi / WebAudio / GenericWS 协议自动识别          │
└────────────────────┬────────────────────────────────┘
                     │ HTTP + Service Token
┌────────────────────▼────────────────────────────────┐
│               AI Core (灵魂引擎)                      │
│                                                      │
│  ┌───────────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 结构化JSON回复  │ │ PAD情感  │ │ 内容安全  │        │
│  │ (dialogue/    │ │ (3D连续  │ │          │        │
│  │  action/pad/  │ │  情绪空间)│ │          │        │
│  │  voice/stance)│ │          │ │          │        │
│  └───────────────┘ └──────────┘ └──────────┘        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │ Prompt   │ │ 对话记忆  │ │ PersonaContext│        │
│  │ Builder  │ │          │ │ (通用称呼系统) │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │ LLM 客户端│ │ TTS 合成  │ │ 硬件指令映射  │        │
│  │ (6家厂商) │ │(Fish/Cosy)│ │ (LED/电机/  │        │
│  │          │ │          │ │  振动)       │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
└─────┬──────────┬──────────┬──────────┬──────────────┘
      │          │          │          │
 PostgreSQL    Redis     Milvus    Fish Audio
  (数据)      (缓存)    (向量)    / DashScope
```

### 第二视图：Character Runtime（一个大脑，多个身体）

上图是**商用设备管线**（设备 → Gateway → AI Core）。仓库里还有第二套并行架构——**Character Runtime**（`engine/`），面向"任何身体都能接入同一个灵魂"的通用引擎愿景：

```
                    ┌──────────────────────────────┐
                    │   Character Runtime (大脑)     │
                    │  engine/planner   三层规划+四级重规划
                    │  engine/perception 多模态感知   │
                    │  engine/server    Protocol 0.2  │
                    └──────┬───────┬───────┬────────┘
                    JSON over WS (/body /control, 能力协商)
                      ┌────┴──┐ ┌──┴────┐ ┌┴─────────┐
                      │ Unity │ │ Web/  │ │ 语音网关  │ ← gateway 作为
                      │ 场景  │ │Studio │ │(xiaozhi) │   "voice body" 接入
                      └───────┘ └───────┘ └──────────┘
                                 ┌──────────────────┐
                                 │ engine/embodiment │→ engine/legacy 伺服栈 → 真机
                                 └──────────────────┘
```

- 权威架构文档：[`docs/engine_architecture.md`](docs/engine_architecture.md)
- 权威线协议规格：[`docs/protocol_0.2_spec.md`](docs/protocol_0.2_spec.md)（JSON over WebSocket，能力协商、回执防伪、重连顶替）
- 角色单一来源：[`configs/characters.json`](configs/characters.json)（人格 × 音色 × 模型，换角色零代码）
- 可视化对话台：`studio/`（`uv run python studio/server.py --port 8899`，人格×音色×VRM 自由组合）
- `engine/legacy/` 是已退役的 Gen1 行为/伺服栈，仅作为 `embodiment/robot_adapter` 背后的执行层存活，不再添加新功能

两套架构通过 `CHARACTER_RUNTIME_URL` 打通：设置后，网关把语音决策交给 Character Runtime（网关自身成为一个 voice body），TTS 仍复用 AI Core。

## 核心特性

### 人格化设计理念：是角色，不是扮演角色

SoulForge 的所有模板和引擎围绕一个原则：**让用户相信这个 AI 玩具就是那个角色本身，而不是在 cosplay**。

- **Prompt 写法**：不是"你要扮演 X"的规则列表，而是**第二人称内心代入**（"你叫 X。你是一只...，有体温、有呼吸"），内嵌 3 条微型示例而不是 20 条"不要做 Y"
- **允许不完整回复**：dialogue 可以为空（只用动作回应）、可以是"……"、可以有结巴（"那个、就是……算了"）和自我修正
- **身体感受注入** (`embodiment.py`)：根据时间/PAD/触摸时长生成"有点困了""心跳有点快""被抱着暖暖的"等感官片段，让角色有**身体**
- **中途唤起**：长时间静默或用户情绪翻转时，注入"刚冒出来的念头"，角色不再机械回应最后一句
- **安全是本能不是规则**：被问"你是AI吗"—— 角色"听不懂这个词"，绝不说"作为AI我不能..."破壁台词
- **PAD 优先**：结构化输出时 LLM 的 PAD 值直接驱动情绪，不再被关键词扫描覆盖

详见 `packages/ai-core/src/ai_core/templates/system_prompt.jinja2` 和 `embodiment.py`。

### 结构化 AI 回复

LLM 不再输出纯文本——每次回复都是结构化 JSON：

```json
{
  "dialogue": "嗯，你好啊。今天怎么突然找我？",
  "action": "嘴角微微上扬，目光温柔",
  "thought": "又来了，装作不在意的样子",
  "pad": {"p": 0.5, "a": 0.3, "d": 0.6},
  "voice": {"speed": 1.05, "pitch": 0.02, "tone": "teasing"},
  "stance": "teasing"
}
```

- **dialogue** — 说出的话 → TTS 语音合成 + 聊天气泡
- **action** — 肢体/表情 → 手机端旁白 / 玩具端 LED 表情
- **thought** — 内心独白 → 手机端可展开查看
- **PAD** — 3D 情绪坐标 → 驱动 TTS 情感 + 硬件动作
- **voice** — 语速/音调/语气 → 直接控制 TTS 参数
- **stance** — 行为姿态 → 角色一致性 anchor

三层容错解析器：标准 JSON → YAML-like → 拼接 JSON，兼容 7B 模型的各种输出格式。

### PAD 连续情感引擎

不用离散标签——用 3D 连续空间精确表达情绪：

- **P (Pleasure)** -1 到 +1 — 难过 ↔ 开心
- **A (Arousal)** -1 到 +1 — 平静 ↔ 兴奋
- **D (Dominance)** -1 到 +1 — 害羞 ↔ 自信

LLM 直接输出 PAD 值，驱动一切下游系统：

| PAD 值 | 效果 |
|--------|------|
| p=0.8, a=0.5 | 语音轻快 + LED 暖黄 + 弹跳动作 |
| p=-0.4, a=-0.3 | 语速放慢 + LED 冷蓝 + 无动作 |
| d=-0.5 | 语音变轻 + LED 粉色 + 歪头动作 |

### VRM 虚拟身体 (`/live`) — 2026-08 新增

VRM 形象是 gateway 的一个**身体**，和小智 ESP32 平级：语音 / 记忆 / 关系 / 事件全部走同一条管道，页面只负责渲染。

- **一个共享身体库** `studio/web/lib/vrm_body.js`：idle 动捕轮换（不连续重复、忙时推迟、crossfade）、说话动捕、注视"眼先头后"、呼吸/眨眼/fidget、PAD 情绪→表情+头姿阻尼、五视素口型、坐/跪/忙手等姿态叠加、缺表情通道自动退化
- **Protocol 0.2 `backend:"web"`**：`lib/body_client.js` 连 Runtime Server `/body`，规划器 ActionCommand 经 `engine/embodiment/web_adapter.py` ↔ `lib/action_map.js` 同一张步表变成 clip/gaze/pose 原语（JS/Python 表由测试钉死）
- **完整陪伴 UI**：头部跟随气泡、五轴关系 HUD、情绪与原因、视觉小说事件卡（选项经 gateway 回传并念出台词）、记忆图（力导向）、陪伴/恋爱模式切换、存档导出导入
- **桌面壳** `apps/desktop/`（Tauri 2）：主窗 + ⌘⇧U 透明置顶可拖拽的悬浮伴侣；WKWebView 无 WebCodecs → Rust `cpal` 原生麦克风
- 冒烟：`pnpm test:studio`（假 gateway + 假 ai-core + 假 Runtime，Playwright 无头 Chromium）

### 五轴关系 + 事件 + 语义记忆 — 从 aikeya 移植的设计

设计取自开源项目 [aikeya](https://github.com/aikeyaorg/aikeya)（MIT），在 Python 大脑里重写并修掉了它未实现/有错的部分：

- **关系**：affection(0–1000) + trust/intimacy/comfort/respect/energy，8 阶段合取门控（含必需事件）；"应用是 GM"——启发式基线 + LLM 建议夹钳；按轴墙钟衰减；`companion` / `dating_sim` 双模式；SSE `relationship` 事件、`GET/PATCH /relationship/{u}/{c}`
- **情绪因果**：PAD "为什么这样"5 条环 + 离线墙钟衰减；久别小时级提示
- **事件**：28 个里程碑/随机/恋爱/时段事件、21 种条件；每轮最多 1 个，随机每日 1 个；**事件结果进入下一轮 prompt**；`POST .../events/{id}/choice`
- **语义记忆**：本地 `BAAI/bge-small-zh-v1.5` + pgvector 接入五层记忆检索（保留记忆策略审计），`GET /memory/graph`，全量存档 `export/import`

### 声优级 TTS (Fish Audio S1)

**告别合成味——用声优级语音引擎**：

- **Fish Audio S1** — TTS-Arena 盲测排名第一，中文质量 9.5/10
- **通用声音匹配** — 基于性格 4D 向量 (warmth/energy/maturity/gravity) + 性别自动匹配最佳声音
- **任何角色都适配** — DIY 角色也能自动匹配，无需手动选声音
- **情绪驱动语音** — PAD 值自动映射为情绪标签 + 语速语量调节
- **URL 声音克隆** — 粘贴 10 秒以上原声 URL，一键生成角色专属音色 refId（无需本地上传）
- **预录音效片段** — audioClips 映射让特定拟声词直接播放原版音频，跳过 TTS 合成
- **智能文本清洗** — 处理 `~`、重叠语气词、重复标点，让语音更自然
- **DashScope CosyVoice 备选** — 24 种预设声音 + SSML 音效引擎

### 非语言角色 (Vocalized Mode)

**让只会"咕咕嘎嘎""doro~"的角色拥有完整灵魂**：

- **VOCALIZED 模式** — 设 `languageMode=VOCALIZED`，LLM 的 dialogue 只能从你定义的拟声词库里选
- **拟声词库 (palette)** — 角色能发出的全部音节（如 `["咕","嘎","咕咕","嘎嘎"]` / `["doro","哆啰"]`）
- **语义分离** — thought 字段记录角色心里真正想的（完整中文），dialogue 只出拟声；PAD + action 正常表达
- **专属动作** — species 含"企鹅/鸭"解锁 waddle，含"doro/团子/史莱姆"解锁 wiggle
- **声音克隆绑定** — voiceCloneRefId 直接挂在角色上，TTS 自动优先使用克隆音色
- **原声片段** — audioClips 把 `"doro~" → 原声 MP3 URL` 一一对应，保留真实 IP 音色

示例：咕咕嘎嘎企鹅（明日方舟：终末地风格）
```json
{
  "dialogue": "咕咕！嘎——",
  "action": "拍了拍圆滚滚的肚子，左右摇晃两下",
  "thought": "主人今天回来啦，好开心",
  "pad": {"p": 0.6, "a": 0.5, "d": 0.2},
  "stance": "excited"
}
// → motor.action = "waddle"（企鹅专属）
```

### PersonaContext 通用称呼系统

不同角色类型自动使用合适的语言风格：

| Archetype | 称呼用户 | 关系描述 | 示例 |
|-----------|---------|---------|------|
| ANIMAL | 主人 | 和主人的关系 | "主人今天心情好吗？" |
| HUMAN | 你/对方 | 和对方的关系 | "你今天怎么突然找我？" |
| FANTASY | 主人 | 和主人的关系 | "主人，今天想去冒险吗？" |
| ABSTRACT | 你/用户 | 和用户的关系 | "你需要什么帮助？" |

覆盖系统 prompt、情绪提示、触摸响应、时间感知、记忆模板、场景提示——零硬编码。

### 硬件指令映射 (PAD → 玩具动作)

PAD 情绪值直接驱动物理硬件：

```json
{
  "led": {"expression": "happy", "color": [255, 210, 90], "brightness": 0.85},
  "motor": {"action": "nod", "speed": 0.5, "intensity": 0.48},
  "vibration": {"pattern": "pulse", "intensity": 0.46, "duration_ms": 300}
}
```

- **LED** — 8 种表情 + RGB 颜色 + 亮度，评分制匹配防止情绪闪烁
- **Motor** — nod/shake/tilt/sway/bounce + 物种专属 waddle（企鹅/鸭）/ wiggle（doro/史莱姆）
- **Vibration** — pulse/steady/double/heartbeat，梯度强度

### 手机端聊天

仿 iMessage 风格的移动聊天界面：

- **角色列表** `/chat` — 骨架屏加载、入场动画、archetype 标签
- **聊天页** `/chat/[id]` — 混合流式（实时流文本 + 完成后追加元数据）
- **角色旁白** — action 显示为斜体、thought 显示为内心独白
- **个性化** — 欢迎语和提示按钮根据角色性格定制
- **Cloudflare Tunnel** — 无拦截页，手机直接访问

### 5 维性格系统

外向、幽默、温暖、好奇、活力，每个 0-100 可调。
3 层融合：设计师基础 → 用户偏移 → 互动微漂移。

### 五层记忆系统（Companion Memory）

从简单的 topic/preference/event 记忆升级为可审计、可管理、可安全过滤的五层记忆系统：

底层保留不可变 `raw_event_logs` 事件流；五层记忆、反思和行为规则是可回滚、可审计的派生层。

| Layer | 记什么 | 用途 |
|-------|--------|------|
| `identity` | 用户身份、长期稳定背景 | 保持角色对用户的长期认识 |
| `preference` | 喜好、厌恶、习惯 | 个性化回复和主动关怀 |
| `event` | 重要事件、约定、共同经历 | 后续对话可自然回忆 |
| `relationship` | 关系阶段、称呼、互动模式 | 关系进化和语气调整 |
| `private_state` | 敏感状态、情绪低谷、隐私信息 | 受策略保护，只在安全场景读取 |

- **五层模型** — `identity` / `preference` / `event` / `relationship` / `private_state` 分层存储
- **原始事件流** — `/memory/events` 记录对话、触摸、设备状态等 raw event，派生记忆通过 id 溯源
- **隐式/显式区分** — `source=IMPLICIT|EXPLICIT|SYSTEM`，敏感记忆默认需要确认
- **儿童安全读取策略** — child profile 下自动屏蔽高敏感 private_state
- **三因子检索** — Generative Agents 风格 `recency × importance × relevance` 精排，返回 score 分解
- **反思编译** — `/memory/reflect` 从高重要度事件生成带 `evidence_refs` 的 relationship/private_state 行为规则
- **事件反应** — `/memory/reaction` 对低电量、硬件失败、打断、触摸、静默、定时器做低成本 react/ignore 决策
- **人格适配** — reaction 自动读取 `personality`、`language_mode`、`vocalization_palette`；非语言角色输出拟声词并保留 `semantic_text`
- **Prompt 注入** — pipeline 检索角色+用户相关记忆，压缩成 `memory_context` 注入系统提示
- **管理后台** — `/dashboard/memories` 可按角色、用户、layer、敏感级别检索和停用记忆
- **API** — AI Core `/memory` 负责写入/检索；Admin Web `/api/memories` 负责后台查询和软删除
- **持久化** — PostgreSQL 新增 companion memory 表和 schema，支持审计字段、置信度、过期时间

### ActionPlan DSL 与硬件安全门

- **DSL Preview API** — AI Core `/actions/preview` 预览 plan/react 输出的 `speech` + `actions`
- **能力降级** — 根据 `device_manifest` 判断通道可用性，缺 motor/haptic 时按 fallback 链降级到 LED/静默
- **物理安全** — 音量、LED 亮度、频闪、motor speed/intensity/angle、haptic 强度和时长确定性裁剪
- **状态安全** — 低电量、过温、夜间/安静模式自动禁止或弱化高功耗/高打扰动作
- **审计输出** — 每次裁剪、替换、拒绝都返回 `audit` 与 `safety_flags`，可用于 digital twin 和硬件验收

实现入口：

- `packages/ai-core/src/ai_core/services/memory.py`
- `packages/ai-core/src/ai_core/services/memory_policy.py`
- `packages/ai-core/src/ai_core/services/companion_reaction.py`
- `packages/ai-core/src/ai_core/services/action_plan.py`
- `packages/ai-core/src/ai_core/api/memory.py`
- `packages/ai-core/src/ai_core/api/actions.py`
- `apps/admin-web/src/app/dashboard/memories/page.tsx`
- `packages/database/prisma/migrations/20260603090000_companion_memory_mvp/migration.sql`
- `packages/database/prisma/migrations/20260612090000_memory_importance_scoring/migration.sql`
- `packages/database/prisma/migrations/20260612100000_memory_reflections/migration.sql`
- `packages/database/prisma/migrations/20260612110000_raw_event_log/migration.sql`

### 关系进化

5 阶段关系线：STRANGER → ACQUAINTANCE → FAMILIAR → FRIEND → BESTFRIEND
亲密度 0-1000，情绪互动/触摸/对话时长自动累积。

### 虚拟偶像模块

8 大人设预设 (暮影司/铃奈/陆辰逸等)，恋爱关系 5 阶段，场景互动 (早安/晚安/吃醋/表白)。

### 小智 ESP32-S3 设备接入

**开箱即用的硬件接入——小智设备连上就能说话**：

- **Opus 双向编解码** — 入站: opuslib 逐帧解码 Opus→PCM；出站: MP3→PCM 24kHz→裸 Opus 帧，前5帧预缓冲+60ms帧率控制
- **Silero VAD 神经网络降噪** — 精准区分人声与环境噪音，只在说话时触发处理
- **流式 ASR** — 边听边识别（DashScope Recognition 流式模式），说完即出结果，降级到批量 ASR 兜底
- **流式语音响应** — LLM 流式输出 → 逐句断句 → 每句即时 TTS → Opus 帧推送
- **流式 TTS（边合成边播）** — Fish Audio 逐块吐 MP3，Gateway 用 `StreamingMp3OpusEncoder` 滚动窗口增量解码（复用 ffmpeg+opuslib，留 1 帧 overlap 余量防边界抖动），首个 Opus 帧在第一个窗口即推送，不再等整句合成完。由 `TTS_STREAMING` 总开关 + 请求级 `audio_streaming` 双重门控，失败自动回退整段路径
- **低延迟管道** — ai-core `_prepare_context` 把记忆检索/关系/角色/Redis 读 collapse 成单个 `asyncio.gather`（连接池安全），从 LLM 前的关键路径上削掉数次串行网络往返；分阶段延迟见 `GET /metrics/latency`
- **语音中断 (Barge-in)** — TTS 播放时检测用户说话，立即停止播放恢复监听
- **设备事件反应桥接** — Generic/WebAudio 设备可上报 `event/device_event`，Gateway 调用 `/memory/reaction` + `/actions/preview` 返回安全后的 reaction commands
- **多轮对话记忆** — 会话内最近 10 轮历史传给 LLM，支持上下文连续对话
- **插件系统** — 关键词匹配跳过 LLM（"几点了""今天星期几""3加5"秒回），插件自动发现
- **播放/监听状态机** — TTS 播放时抑制回声，420ms 延迟发 stop 信号（匹配官方协议时序）
- **设备自动注册** — 新设备首次连接自动绑定默认角色，零配置
- **OTA 劫持** — 内置 `/ota/` 端点 + 固件 NVS/OTA URL 二进制修补
- **空闲超时** — 120 秒无语音自动断开，节省资源

```
小智 ESP32-S3  ──(WebSocket)──►  Gateway (:8080)
   │                                │ XiaozhiAdapter 协议自动识别
   │ Opus 16kHz 裸帧               │ opuslib 逐帧解码 → PCM
   │                                │ Silero VAD + 流式ASR (并行)
   ▼                                ▼
 麦克风 → Opus帧 ──────►  [插件匹配?] ──命中──► 秒回 (跳过LLM)
                              │ 未命中
                          DeepSeek LLM (带10轮历史)
                              │ 流式输出逐句断句
                          Fish Audio TTS → MP3 (流式逐块)
                              │
                          滚动窗口增量解码 ffmpeg 24kHz PCM → opuslib Opus帧
                              │ 前5帧预缓冲 + 60ms帧率控制
 扬声器 ◄── Opus帧 ◄────── 逐帧发送 (支持中途打断)
```

### 儿童安全

- **200+ 关键词过滤** — 覆盖自伤、涉黄、暴力、毒品
- **反绕过** — NFKC 归一化 + 零宽字符检测
- **LLM 输出双过滤** — 输入拦截 + 输出检查
- **PII 脱敏** — 自动过滤身份证、手机号、银行卡

### 商用安全

- **三重认证** — NextAuth JWT / API Key / 内部服务令牌
- **CORS 白名单** / 安全响应头 / Redis 限流 / License 分级

## 项目结构

```
soulForge/
├── apps/
│   ├── admin-web/              # Next.js 管理后台
│   │   └── src/app/
│   │       ├── chat/           # 手机端聊天 (角色列表 + 聊天页)
│   │       ├── api/chat/       # 公开聊天 API (角色列表 + 流式对话)
│   │       ├── api/memories/   # 后台记忆查询/停用 API
│   │       └── dashboard/      # 设计师管理面板 (含 /dashboard/memories)
│   ├── mini-program/           # 微信小程序 (WIP)
│   └── desktop/                # Tauri 2 桌面壳 (主窗 + 透明悬浮伴侣, cpal 原生麦克风)
├── packages/
│   ├── ai-core/                # Python FastAPI 灵魂引擎
│   │   └── src/ai_core/
│   │       ├── api/            # REST 端点 (chat/pipeline/memory/actions/tts/rag/idol/voice_clone)
│   │       ├── services/
│   │       │   ├── response_parser.py    # 结构化 JSON 回复解析
│   │       │   ├── persona_context.py    # 通用称呼系统
│   │       │   ├── hardware_mapper.py    # PAD → 硬件指令 (含 waddle/wiggle)
│   │       │   ├── emotion.py            # 情感状态机
│   │       │   ├── pad_model.py          # PAD 3D 连续情感
│   │       │   ├── embodiment.py         # 身体感受注入 + 中途念头
│   │       │   ├── prompt_builder.py     # Prompt 组装引擎 (三模板路由)
│   │       │   ├── voice_matcher.py      # 4D 声音匹配
│   │       │   ├── voice_clone.py        # Fish Audio 声音克隆 (文件+URL)
│   │       │   ├── proactive_trigger.py  # 开场 + 中途静默触发
│   │       │   ├── tts/
│   │       │   │   ├── fish_audio_tts.py # Fish Audio S1 (克隆 refId + audio_clips)
│   │       │   │   ├── dashscope_tts.py  # CosyVoice (备选)
│   │       │   │   └── edge_tts_provider.py # Edge TTS (免费降级)
│   │       │   ├── relationship.py       # 五轴关系 / 8 阶段 / 衰减 / LLM 夹钳
│   │       │   ├── events/               # 视觉小说事件 (definitions/conditions/engine)
│   │       │   ├── embeddings.py         # 本地句向量 (bge-small-zh, pgvector)
│   │       │   ├── memory.py             # 五层陪伴记忆服务 (向量检索 + 记忆图 + 存档)
│   │       │   ├── memory_policy.py      # 敏感度/读写策略
│   │       │   ├── companion_reaction.py # 事件 → react/ignore 决策
│   │       │   ├── action_plan.py        # ActionPlan DSL 预览 + Safety Gate
│   │       │   └── ...                   # content-filter/cache/rag
│   │       └── templates/      # Jinja2 系统 Prompt 模板
│   │           ├── system_prompt.jinja2       # 通用角色 (第二人称代入)
│   │           ├── idol_prompt.jinja2         # 偶像/恋爱角色
│   │           └── vocalized_prompt.jinja2    # 非语言角色 (咕咕嘎嘎/doro)
│   ├── gateway/                # WebSocket 网关 (设备连接)
│   │   └── src/gateway/
│   │       ├── protocols/
│   │       │   ├── xiaozhi.py          # 小智ESP32协议 (Opus编解码)
│   │       │   ├── web_audio.py        # Web音频流协议
│   │       │   └── generic_ws.py       # 通用WebSocket协议
│   │       ├── handlers/
│   │       │   ├── audio.py            # 音频帧缓冲
│   │       │   └── audio_codec.py      # Opus/PCM/MP3转码 (ffmpeg)
│   │       ├── pipeline/
│   │       │   ├── orchestrator.py     # AI Core调用 (阻塞+流式)
│   │       │   └── character_bridge.py # Character Runtime 桥 (gateway 作为 voice body)
│   │       ├── playback.py             # 设备播放协议舞蹈的唯一实现 (节奏/打断/缓冲)
│   │       ├── life/                   # "活着"层: 空闲状态机 (无聊哼歌/夜间困倦/思考填充音)
│   │       ├── session.py              # 会话管理 + 设备自动注册
│   │       └── server.py               # WebSocket服务 (流式推送)
│   ├── database/               # Prisma Schema + 迁移
│   └── shared/                 # 共享类型
├── engine/                     # Character Runtime (第二视图, 见上文)
│   ├── planner/                # 三层规划 (day/hour/minute) + 四级重规划 + 记忆适配
│   ├── server/                 # Protocol 0.2 运行时服务器 (/body /control)
│   ├── perception/             # 多模态感知 (vision/audio/fusion, 确定性安全钳制)
│   ├── embodiment/             # IR → 身体适配器 (robot_adapter 真机 / web_adapter 浏览器 VRM)
│   └── legacy/                 # Gen1 行为/伺服栈 (已退役, 仅供 embodiment 调用)
├── studio/                     # /live 陪伴应用 + 工作台 (aiohttp + three-vrm)
│   ├── web/lib/                # vrm_body / lipsync / pad_expression / body_client / action_map / memory_graph
│   └── tests/                  # fake_gateway.py (假 gateway+ai-core+Runtime) + Playwright 冒烟
├── configs/
│   └── characters.json         # 角色单一来源 (人格/音色/模型/原型)
├── docs/
│   ├── engine_architecture.md  # Character Runtime 权威架构
│   └── protocol_0.2_spec.md    # 权威线协议规格
├── tests/                      # Character Runtime 测试套件 (197 项)
├── demo/                       # 晚餐 demo 管线 + 融资样片生成
├── hardware/                   # 硬件接入测试
├── scripts/
│   ├── dev.sh                  # 一键启动开发环境
│   ├── live-up.sh              # ai-core + gateway + Runtime Server + studio (VRM 全链路)
│   └── mobile.sh               # 手机测试模式 (ngrok/cloudflared)
└── .env.example                # 环境变量模板
```

## 快速开始

### 前置条件

- Node.js >= 18, Python >= 3.12
- Docker Desktop (PostgreSQL + Redis)
- [uv](https://docs.astral.sh/uv/) (Python 包管理)
- [DashScope API Key](https://dashscope.console.aliyun.com/) (LLM)
- [Fish Audio API Key](https://fish.audio/) (TTS, 可选)

### 1. 克隆 & 配置

```bash
git clone https://github.com/LookJohnny/soulForge.git
cd soulForge
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY、FISH_AUDIO_API_KEY 等
```

### 2. 安装依赖

```bash
uv sync --all-packages --dev   # Python (workspace 全部成员)
pnpm install                   # Node.js
```

> ⚠️ **macOS + iCloud**：若仓库位于 iCloud 同步目录（Desktop/Documents），iCloud 会向 `.venv` 注入 `foo 2.dist-info` 副本文件并损坏环境。本仓库的 `.venv` 是指向 `.venv.nosync` 的符号链接（`*.nosync` 不被 iCloud 同步）——重建环境时保持这个结构：`rm -rf .venv.nosync && mkdir .venv.nosync && uv sync --all-packages --dev`。最彻底的方案是把仓库移出 iCloud 目录。

### 3. 一键启动

```bash
./scripts/dev.sh
```

自动完成：Docker 服务 → 数据库迁移 → Prisma 生成 → AI Core (8100) + Gateway (8080) + Next.js (3000)。

### 3b. VRM 虚拟形象 / 桌面伴侣

```bash
./scripts/live-up.sh                    # ai-core 8100 + gateway (GATEWAY_PORT, 默认 8080) + Runtime 8765 + studio 8899
open http://127.0.0.1:8899/live         # 浏览器：语音/记忆/关系/事件 + 引擎动作驱动
# 桌面壳（需 cargo install tauri-cli --version '^2'）：
cd apps/desktop/src-tauri && cargo tauri build --debug --bundles app && open "target/debug/bundle/macos/SoulForge Live.app"
```

语义记忆需要 `pgvector/pgvector:pg16` 镜像（compose 已切换）+ 迁移 005–007 + `uv sync --all-packages --extra semantic`（首次下载约 95 MB 模型，国内可设 `HF_ENDPOINT=https://hf-mirror.com`）；缺任一项自动退回词法检索。页面默认连接的 gateway/runtime 地址由 `.env` 的 `GATEWAY_WS_URL` / `RUNTIME_WS_URL` 决定。

### 4. 手机测试

```bash
./scripts/mobile.sh
```

启动内网穿透，手机扫码即可聊天。

### 5. 验证

```bash
curl http://localhost:8100/health       # 健康检查
make test-py                            # 全部 Python 测试 (~800 项, 三套分开跑)
pnpm --dir apps/admin-web build         # 管理后台构建
```

> 测试命令**都从仓库根目录跑**。`make test-py` 依次执行三套：ai-core (655)、gateway (65)、Character Runtime (204)；前端 `pnpm test:studio` / `pnpm test:studio:workbench`。ai-core 和 gateway 的 `tests/` 目录同名，**不能合并进一条 pytest 命令**（模块名冲突）；根目录的 `tests/test_gateway_*` 同理不能与 `packages/gateway/tests` 同跑。

单套/单文件验证示例：

```bash
uv run pytest packages/ai-core/tests/test_memory_policy.py   # 记忆策略
uv run pytest packages/gateway/tests/test_playback.py        # 设备播放协议
uv run pytest tests/test_planner.py                          # 规划引擎
uv tool run ruff check packages/ai-core/src packages/gateway/src engine tests studio
```

## SSE 流式事件

### 设备管道 `POST /pipeline/chat/stream`

为硬件设备优化的流式端点——逐句生成文本+音频，最小化首句延迟：

| 事件类型 | 时机 | 内容 |
|---------|------|------|
| `sentence` | 每句完成 | `{text, audio_data (base64\|null), index}` |
| `audio_chunk` | 流式 TTS 边合成边推 | `{index, audio_data (base64)}` — 仅当请求带 `audio_streaming:true` |
| `audio_end` | 某句音频结束 | `{index}` — 流式 TTS 的收尾标记 |
| `emotion` | 情绪更新 | `{emotion, pad, hardware, causes[], energy}` |
| `relationship` | 关系轴变化 | `{stage, app_mode, axes{}, deltas{}, stage_changed, near_stage}` |
| `event` | 视觉小说事件触发 | `{event_id, name, scene{intro,dialogue,choices[]}, state_changes}` |
| `done` | 全部完成 | `{full_text, emotion, pad, relationship_stage, relationship, latency_ms, stages}` |

请求带 `audio_streaming:true`（且 `TTS_STREAMING` 开启、provider 支持）时，音频以 `audio_chunk` 逐块下发，`sentence` 只携带文本（`audio_data:null`）；否则走 legacy 整段路径——`sentence` 直接带完整 `audio_data`。

示例响应流（流式 TTS）：
```
data: {"type":"sentence","text":"嘿嘿，太棒啦！","audio_data":null,"index":0}
data: {"type":"audio_chunk","index":0,"audio_data":"//uQxA..."}
data: {"type":"audio_chunk","index":0,"audio_data":"SUQzBA..."}
data: {"type":"audio_end","index":0}
data: {"type":"done","full_text":"嘿嘿，太棒啦！","emotion":"curious","latency_ms":4051,"stages":{...}}
```

### Web 预览 `POST /chat/preview/stream`

为前端 UI 优化的流式端点——实时流文本 + 完成后追加元数据：

| 事件类型 | 时机 | 内容 |
|---------|------|------|
| `text` | 实时 | LLM 生成的 token (含 JSON 残留) |
| `text_replace` | LLM 完成 | 干净的 dialogue 文本 |
| `action` | LLM 完成 | 角色动作/表情描述 |
| `thought` | LLM 完成 | 角色内心独白 |
| `emotion` | LLM 完成 | 情绪标签 + PAD 值 + stance |
| `hardware` | LLM 完成 | LED/电机/振动指令 (opt-in) |
| `audio` | TTS 完成 | 逐句 base64 音频 |
| `error` | 异常 | 错误消息 |
| `done` | 结束 | 流结束信号 |

## LLM / TTS 提供商

### LLM (6 家)

| 提供商 | 配置值 | 说明 |
|--------|--------|------|
| DashScope/通义千问 | `dashscope` | 默认 |
| DeepSeek | `deepseek` | 性价比 |
| Moonshot/Kimi | `moonshot` | 长上下文 |
| 智谱 GLM | `glm` | 国产替代 |
| OpenAI | `openai` | GPT 系列 |
| Ollama | `ollama` | 本地部署 |

### TTS (3 家)

| 提供商 | 配置值 | 特点 |
|--------|--------|------|
| **Fish Audio** | `fish` | 声优级音质，10 秒声音克隆，PAD 情绪驱动 |
| DashScope CosyVoice | `dashscope` | 24 声音预设，SSML 精调 |
| Edge TTS | `edge` | 免费降级方案 |

通过 `TTS_PROVIDER` 环境变量切换。

## 技术栈

**后端**: Python 3.12+ / FastAPI / asyncpg / Redis / Milvus
**前端**: Next.js 16 / NextAuth v5 / Prisma / React 19
**AI**: DeepSeek (LLM) / DashScope (ASR) / Fish Audio (TTS) / Silero (VAD)
**引擎**: Character Runtime (零三方依赖可嵌入) / Protocol 0.2 (JSON over WS, robot + web 身体) / three-vrm + VRMA (Studio & /live)
**桌面**: Tauri 2 / cpal / WKWebView (透明悬浮窗)
**记忆**: pgvector / sentence-transformers (bge-small-zh-v1.5)
**硬件**: 小智 ESP32-S3 (Opus 16kHz / WebSocket) / opuslib / ffmpeg
**基建**: PostgreSQL / Redis / Milvus / MinIO / Docker / ffmpeg
**质量**: ~920 项 Python 测试 (make test-py: ai-core 655 / gateway 65 / Runtime 204) + 2 套 Playwright 冒烟 / ruff / GitHub Actions CI (lint + 三套测试 + Docker build)

## License

Private - All rights reserved.
