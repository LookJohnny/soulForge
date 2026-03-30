# SoulForge - AI 灵魂注入平台

> 为任何设备注入独一无二的 AI 灵魂：性格、声音、情感、记忆，一个都不少。

SoulForge 是一个通用 AI 人格引擎平台。为毛绒玩具、耳机、手机 App、桌面应用、智能音箱等任何设备注入有灵魂的 AI 角色——不只是问答，而是有情感、有记忆、有关系进化的真实陪伴。

**支持的设备类型**: 小智 ESP32-S3 / 毛绒玩具 / 蓝牙耳机 / 手机 App / 桌面客户端 / 智能音箱 / 网页
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

## 核心特性

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

### 声优级 TTS (Fish Audio S1)

**告别合成味——用声优级语音引擎**：

- **Fish Audio S1** — TTS-Arena 盲测排名第一，中文质量 9.5/10
- **通用声音匹配** — 基于性格 4D 向量 (warmth/energy/maturity/gravity) + 性别自动匹配最佳声音
- **任何角色都适配** — DIY 角色也能自动匹配，无需手动选声音
- **情绪驱动语音** — PAD 值自动映射为情绪标签 + 语速语量调节
- **10 秒声音克隆** — 上传声优样本即可创建角色专属音色
- **智能文本清洗** — 处理 `~`、重叠语气词、重复标点，让语音更自然
- **DashScope CosyVoice 备选** — 24 种预设声音 + SSML 音效引擎

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
- **Motor** — nod/shake/tilt/sway/bounce，arousal 驱动
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

### 对话记忆

- **LLM 自动提取** — topic / preference / event 三类记忆
- **长期持久化** — PostgreSQL 存储，跨会话保留
- **主动回忆** — "上次你说喜欢恐龙，今天想聊什么？"
- **异步非阻塞** — 记忆提取在响应发送后后台执行

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
- **流式语音响应** — LLM 流式输出 → 逐句断句 → 每句即时 TTS → Opus 帧推送，首句延迟 ~2 秒
- **语音中断 (Barge-in)** — TTS 播放时检测用户说话，立即停止播放恢复监听
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
                          Fish Audio TTS → MP3
                              │
                          ffmpeg 24kHz PCM → opuslib Opus帧
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
│   │       └── dashboard/      # 设计师管理面板
│   └── mini-program/           # 微信小程序 (WIP)
├── packages/
│   ├── ai-core/                # Python FastAPI 灵魂引擎
│   │   └── src/ai_core/
│   │       ├── api/            # REST 端点 (chat/pipeline/tts/rag/idol)
│   │       ├── services/
│   │       │   ├── response_parser.py    # 结构化 JSON 回复解析
│   │       │   ├── persona_context.py    # 通用称呼系统
│   │       │   ├── hardware_mapper.py    # PAD → 硬件指令
│   │       │   ├── emotion.py            # 情感状态机
│   │       │   ├── pad_model.py          # PAD 3D 连续情感
│   │       │   ├── prompt_builder.py     # Prompt 组装引擎
│   │       │   ├── voice_matcher.py      # 4D 声音匹配
│   │       │   ├── tts/
│   │       │   │   ├── fish_audio_tts.py # Fish Audio S1 (主力)
│   │       │   │   ├── dashscope_tts.py  # CosyVoice (备选)
│   │       │   │   └── edge_tts_provider.py # Edge TTS (免费降级)
│   │       │   └── ...                   # memory/content-filter/cache/rag
│   │       └── templates/      # Jinja2 系统 Prompt 模板
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
│   │       │   └── orchestrator.py     # AI Core调用 (阻塞+流式)
│   │       ├── session.py              # 会话管理 + 设备自动注册
│   │       └── server.py               # WebSocket服务 (流式推送)
│   ├── database/               # Prisma Schema + 迁移
│   └── shared/                 # 共享类型
├── hardware/                   # 硬件接入测试
├── scripts/
│   ├── dev.sh                  # 一键启动开发环境
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
uv sync           # Python
pnpm install      # Node.js
```

### 3. 一键启动

```bash
./scripts/dev.sh
```

自动完成：Docker 服务 → 数据库迁移 → Prisma 生成 → AI Core (8100) + Gateway (8080) + Next.js (3000)。

### 4. 手机测试

```bash
./scripts/mobile.sh
```

启动内网穿透，手机扫码即可聊天。

### 5. 验证

```bash
curl http://localhost:8100/health       # 健康检查
uv run pytest packages/ai-core/tests/  # 测试
```

## SSE 流式事件

### 设备管道 `POST /pipeline/chat/stream`

为硬件设备优化的流式端点——逐句生成文本+音频，最小化首句延迟：

| 事件类型 | 时机 | 内容 |
|---------|------|------|
| `sentence` | 每句完成 | `{text, audio_data (base64), index}` |
| `done` | 全部完成 | `{full_text, emotion, pad, relationship_stage, latency_ms}` |

示例响应流：
```
data: {"type":"sentence","text":"嘿嘿，太棒啦！","audio_data":"//uQxA...","index":0}
data: {"type":"sentence","text":"我是快乐小鼠呀！","audio_data":"SUQzBA...","index":1}
data: {"type":"done","full_text":"嘿嘿，太棒啦！我是快乐小鼠呀！","emotion":"curious","latency_ms":4051}
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
**硬件**: 小智 ESP32-S3 (Opus 16kHz / WebSocket) / opuslib / ffmpeg
**基建**: PostgreSQL / Redis / Milvus / MinIO / Docker / ffmpeg

## License

Private - All rights reserved.
