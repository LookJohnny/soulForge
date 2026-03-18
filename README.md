# SoulForge - AI 毛绒玩具灵魂注入平台

> 为毛绒玩具注入独一无二的 AI 灵魂：性格、声音、情感、记忆，一个都不少。

SoulForge 是一个面向儿童智能玩具的 AI 人格引擎平台。品牌设计师通过 Web 后台定义角色的性格、声音和知识库，平台自动为每个毛绒玩具生成有灵魂的对话体验——不只是问答，而是有情感、有记忆、有个性的陪伴。

## 架构

```
┌─────────────────────────────────────────────────────┐
│              设备端 (小程序 / 硬件)                    │
└────────────────────┬────────────────────────────────┘
                     │ WebSocket
┌────────────────────▼────────────────────────────────┐
│              Gateway (协议适配层)                      │
│   Xiaozhi / WebAudio / GenericWS 协议自动识别          │
└────────────────────┬────────────────────────────────┘
                     │ HTTP + Service Token
┌────────────────────▼────────────────────────────────┐
│               AI Core (灵魂引擎)                      │
│                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ 情感状态机 │ │ 对话记忆  │ │ 内容安全  │             │
│  └──────────┘ └──────────┘ └──────────┘             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ Prompt   │ │ 声音匹配  │ │ RAG 知识  │             │
│  │ Builder  │ │ (4D向量)  │ │ 引擎     │             │
│  └──────────┘ └──────────┘ └──────────┘             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ LLM 客户端│ │ TTS 合成  │ │ ASR 识别  │             │
│  │ (6家厂商) │ │ (SSML)   │ │          │             │
│  └──────────┘ └──────────┘ └──────────┘             │
└─────┬──────────┬──────────┬──────────┬──────────────┘
      │          │          │          │
 PostgreSQL    Redis     Milvus    DashScope
  (数据)      (缓存)    (向量)   (LLM/TTS/ASR)
```

## 核心特性

### 灵魂注入

- **5 维性格系统** — 外向、幽默、温暖、好奇、活力，每个 0-100 可调
- **4D 声音人格匹配** — 24 种声音按 warmth/energy/maturity/gravity 四维向量自动匹配
- **SSML 音效引擎** — pitch/rate/effect 按物种、年龄、性格自动调参
- **用户个性化** — 每个用户可叠加性格偏移、设定昵称和兴趣

### 情感引擎

- **8 种情绪状态** — happy / sad / shy / angry / playful / curious / worried / calm
- **跨轮次情感惯性** — 情绪不会每句话重置，自然过渡
- **情绪驱动语音** — 开心时 pitch↑ rate↑，难过时 pitch↓ rate↓
- **情绪注入 Prompt** — "你现在有点害羞，说话吞吞吐吐"

### 对话记忆

- **LLM 自动提取** — 从对话中提取 topic/preference/event 三类记忆
- **长期持久化** — PostgreSQL 存储，跨会话保留
- **主动回忆** — "上次你说喜欢恐龙，今天想聊什么？"
- **异步非阻塞** — 记忆提取在响应发送后后台执行

### 儿童安全

- **200+ 关键词过滤** — 覆盖自伤、涉黄、暴力、毒品、武器、诱导/grooming
- **反绕过** — NFKC 归一化 + 零宽字符/空格/全角字符检测
- **LLM 输出双过滤** — 输入拦截 + 输出检查，两道防线
- **防越狱** — 系统 Prompt 注入安全边界指令
- **PII 脱敏** — 自动过滤身份证、手机号、银行卡、邮箱

### 商用安全

- **三重认证** — NextAuth JWT / API Key / 内部服务令牌
- **CORS 白名单** — 不再 `allow_origins=["*"]`
- **安全响应头** — HSTS / X-Frame-Options / nosniff
- **输入校验** — 文本 2000 字 / 音频 10MB / UUID 格式 / role 枚举
- **Redis 限流** — per-user/brand 分布式限流
- **License 分级** — FREE/TRIAL/PRO/ENTERPRISE 从 DB 查询 + 缓存

### 可靠性

- **指数退避重试** — LLM/TTS/ASR 统一 3 次重试 (tenacity)
- **超时控制** — LLM 30s / TTS 15s / ASR 10s
- **TTS 降级** — DashScope 失败自动 fallback Edge TTS
- **健康检查** — `/health` 检测 DB / Redis / Milvus 连通性
- **请求追踪** — `X-Request-ID` 全链路

## 项目结构

```
soulForge/
├── apps/
│   ├── admin-web/          # Next.js 管理后台 (品牌设计师用)
│   └── mini-program/       # 微信小程序 (用户端, WIP)
├── packages/
│   ├── ai-core/            # Python FastAPI 灵魂引擎
│   │   └── src/ai_core/
│   │       ├── api/        # REST 端点 (chat/pipeline/tts/rag/soul-packs)
│   │       ├── middleware/  # auth/rate-limit/cors/metrics/request-id
│   │       ├── services/    # emotion/memory/content-filter/prompt-builder
│   │       │               # voice-matcher/cache/llm/tts/asr/rag
│   │       └── templates/   # Jinja2 系统 Prompt 模板
│   ├── gateway/            # WebSocket 网关 (设备连接)
│   ├── database/           # Prisma Schema + 迁移
│   └── shared/             # 共享类型
├── docker/
│   └── postgres/migrations/ # SQL 迁移脚本
├── scripts/
│   └── verify_security.py  # 安全验证脚本
└── .env.example            # 环境变量模板
```

## 快速开始

### 前置条件

- Node.js >= 18
- Python >= 3.12
- PostgreSQL, Redis
- [uv](https://docs.astral.sh/uv/) (Python 包管理)
- [DashScope API Key](https://dashscope.console.aliyun.com/) (阿里云 AI)

### 1. 克隆 & 配置

```bash
git clone https://github.com/LookJohnny/soulForge.git
cd soulForge
cp .env.example .env
# 编辑 .env，填入你的 DASHSCOPE_API_KEY、AUTH_SECRET 等
```

### 2. 安装依赖

```bash
# Python (ai-core + gateway)
uv sync

# Node.js (admin-web)
cd apps/admin-web && npm install
```

### 3. 数据库初始化

```bash
cd packages/database
npx prisma migrate dev
```

### 4. 启动服务

```bash
# Terminal 1: AI Core
PYTHONPATH=packages/ai-core/src uv run uvicorn ai_core.main:app --port 8100

# Terminal 2: Gateway
PYTHONPATH=packages/gateway/src uv run uvicorn gateway.main:app --port 8080

# Terminal 3: Admin Web
cd apps/admin-web && npm run dev
```

### 5. 验证

```bash
# 健康检查
curl http://localhost:8100/health

# 安全验证 (25项检查)
uv run python scripts/verify_security.py

# 运行测试 (259个)
uv run pytest packages/ai-core/tests/ -v
```

## API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 (公开) |
| `/metrics` | GET | 监控指标 (公开) |
| `/chat/preview` | POST | 单轮/多轮对话 + 情感追踪 |
| `/chat/preview/stream` | POST | SSE 流式对话 + 逐句 TTS |
| `/pipeline/chat` | POST | 完整管线 (ASR→LLM→TTS + 情感 + 记忆) |
| `/prompt/build` | POST | 构建系统 Prompt |
| `/tts/preview` | POST | TTS 预览 |
| `/tts/voices` | GET | 可用声音列表 |
| `/rag/ingest` | POST | 知识库导入 |
| `/rag/search` | POST | 知识库搜索 |
| `/soul-packs/export` | POST | 导出角色包 |
| `/soul-packs/import` | POST | 导入角色包 |

所有非公开端点需要 `Authorization: Bearer <token>` 认证。

## LLM 提供商

开箱支持 6 家：

| 提供商 | 配置值 | 说明 |
|--------|--------|------|
| DashScope/通义千问 | `dashscope` | 默认，推荐 |
| DeepSeek | `deepseek` | 性价比高 |
| Moonshot/Kimi | `moonshot` | 长上下文 |
| 智谱 GLM | `glm` | 国产替代 |
| OpenAI | `openai` | GPT 系列 |
| Ollama | `ollama` | 本地部署 |

通过 `LLM_PROVIDER` 和 `LLM_MODEL` 环境变量切换。

## 测试

```bash
# 全部测试 (259 个)
uv run pytest packages/ai-core/tests/ -v

# 按模块
uv run pytest packages/ai-core/tests/test_emotion.py       # 情感引擎
uv run pytest packages/ai-core/tests/test_content_filter.py # 内容安全
uv run pytest packages/ai-core/tests/test_voice_matcher.py  # 声音匹配
uv run pytest packages/ai-core/tests/test_auth.py           # 认证鉴权
uv run pytest packages/ai-core/tests/test_schemas.py        # 输入校验
```

## 技术栈

**后端**: Python 3.12+ / FastAPI / asyncpg / Redis / Milvus
**前端**: Next.js 16 / NextAuth v5 / Prisma / TailwindCSS
**AI**: DashScope (通义千问 / CosyVoice / FunASR)
**基建**: PostgreSQL / Redis / Milvus / MinIO

## License

Private - All rights reserved.
