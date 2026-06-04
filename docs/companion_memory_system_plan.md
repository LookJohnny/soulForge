# SoulForge 长期关系记忆系统施工方案

> 版本: 2026-06-03
> 范围: 为 SoulForge 增加五层长期记忆、Memory Policy Engine、Memory Compilation Engine，以及能驱动语音、动作、灯光和安静陪伴的记忆使用策略。
> 当前仓库基线: Next.js 管理台 + Python FastAPI AI Core + PostgreSQL/Prisma + Redis + 现有 `ConversationMemory`/`RelationshipState`。

## A. 一句话结论

SoulForge 不应该把“记忆”做成简单 RAG，而应该把它做成一个受策略约束的关系状态系统: 原始事件要保真保存，长期理解要谨慎归纳，真正注入模型的是经过 policy 过滤和 compilation 编译后的行为规则。

## B. 系统总架构

目标架构:

```text
输入层
  语音 ASR / 文本 / 触摸 / 视觉 / 传感器 / 设备状态
    ↓
Session Orchestrator
  当前会话状态、最近 N 轮、PAD 情绪、设备状态、打断状态
    ↓
Short-term Context
  本轮意图、短期任务、用户即时情绪、临时约束
    ↓
Memory Gateway
  Write Pipeline              Retrieval Pipeline
  候选记忆抽取                 五层检索
  风险分类                     policy 过滤
  冲突检测                     token 压缩
  用户确认                     直接/隐性/禁止使用判定
    ↓                            ↓
长期记忆层
  Profile Memory       少量稳定画像
  Episodic Memory      原始事件与上下文
  Semantic Memory      多事件归纳理解
  Relational Memory    互动关系模式
  Memory Policy        何时可说、何时只能隐性影响、何时忘记
    ↓
Memory Compilation Engine
  把稳定记忆编译成 response_style / reasoning_strategy /
  interaction_rhythm / robot_behavior / safety_guardrail
    ↓
LLM 推理层
  system prompt + conversation history + memory pack + compiled rules
    ↓
结构化回复
  dialogue / thought / action / PAD / voice / stance / hardware hints
    ↓
行为输出层
  TTS / 机械眼球 / 灯光 / 电机 / 震动 / 安静陪伴 / 主动提醒
    ↓
Safety & Privacy Layer
  儿童安全、敏感记忆、依赖风险、审计、用户可控管理界面
```

本地端与云端职责:

| 层级 | 云端职责 | 本地端职责 |
|---|---|---|
| 端侧输入 | 高质量 ASR、视觉理解、跨设备事件归并 | 唤醒词、VAD、触摸/IMU、断网输入缓存 |
| 短期上下文 | 会话级编排、最近消息、情绪趋势 | 最近 3-10 轮简短上下文、当前设备状态 |
| 长期记忆 | 五层记忆库、policy、编译、审计 | 极小 profile slice、compiled rules slice、断网基础人格 |
| 推理 | 主 LLM、embedding、记忆抽取、归纳 | 小模型意图分类、唤醒词、本地固定话术兜底 |
| 输出 | TTS、动作计划、跨设备同步 | 播放、灯光、电机安全控制、离线安静陪伴 |

SoulForge 当前落点:

- `packages/ai-core/src/ai_core/services/memory.py`: 从三类短文本记忆升级为 Memory Gateway。
- `packages/ai-core/src/ai_core/services/prompt_builder.py`: 从 `memory_context` 文本列表升级为 `MemoryPack`。
- `packages/ai-core/src/ai_core/api/chat.py`: 在 chat/preview 路径接入 retrieval、policy、write-after-response。
- `packages/ai-core/src/ai_core/services/hardware_mapper.py`: 接收 compiled robot behavior hints。
- `packages/database/prisma/schema.prisma`: 新增五层记忆表、policy 表、compiled rules 表和 audit 表。
- `apps/admin-web`: 新增“记忆管理”界面: 查看、编辑、冻结、删除、禁止主动提及、反馈“记错了”。

## C. 五层记忆系统设计

### 1. Profile Memory

用途: 少量、稳定、长期有效的画像。只存高置信、低变动信息，如称呼、长期偏好、长期目标、长期禁忌。

不要存: 一次性情绪、单轮抱怨、未经确认的身份标签、敏感推断。

写入规则:

- 自动保存: 用户明确说出的低敏长期偏好，例如“以后叫我阿乐”。
- 需要确认: 身份背景、健康、财务、家庭、儿童相关信息。
- 禁止写入: 未经用户表达的推断，例如“用户有焦虑症”。

### 2. Episodic Memory

用途: 保留具体发生过的互动事件，包含原文出处、时间、上下文、情绪、来源设备、置信度。

关键原则: 事件记忆不要只存摘要。摘要只能作为 `content`，原始 turn/log 指针和片段必须保留在 `raw_source`/`source_log_id`/`raw_transcript`。

### 3. Semantic Memory

用途: 从多个事件中提炼稳定理解，如“用户在做桌面 AI companion，不是普通玩具项目”。

生成条件:

- 至少 3 条相关 episodic 证据，或 2 条 episodic + 用户确认。
- 时间跨度最好跨过多天，避免一次对话过拟合。
- 必须保存 `source_memory_ids`，允许追溯和回滚。

### 4. Relational Memory

用途: 保存 AI 与用户之间的互动模式，而不是事实本身。

示例:

- 用户希望回答创业问题时直接指出风险。
- 用户讨厌空泛鼓励。
- 用户更喜欢严肃 deep talk，不喜欢过度迎合。
- 用户疲惫时更适合低打扰陪伴，而不是追问。

这是情感陪伴产品的核心层。事实记忆让 AI “知道”，关系记忆让 AI “像熟人”。

### 5. Memory Policy

用途: 决定记忆如何被使用。

每条记忆至少要被判定为:

- 可直接提及: 可以说“你之前提过...”
- 隐性使用: 只能影响语气、建议框架、动作，不说出处。
- 需要确认: 使用前必须问“我可能记错了，你是不是...”
- 禁止使用: 不进入 LLM 上下文，不参与动作/营销/推荐。
- 衰减/冻结/删除: 随时间降低权重或完全不可用。

## D. Memory Policy Engine

Policy Engine 是硬规则 + LLM 辅助分类的组合，最终决策必须由确定性代码执行。

输入:

```json
{
  "memory": {"id": "...", "type": "EPISODIC", "sensitivity_level": "MEDIUM"},
  "context": {
    "user_input": "最近我很焦虑",
    "user_mood": "vulnerable",
    "is_child": false,
    "relationship_stage": "FAMILIAR",
    "surface": "chat",
    "intent": "emotional_support"
  }
}
```

输出:

```json
{
  "decision": "IMPLICIT_ONLY",
  "reason": "vulnerable_state_sensitive_memory",
  "can_surface_directly": false,
  "requires_confirmation": false,
  "max_prompt_tokens": 80,
  "allowed_channels": ["response_style", "robot_behavior"]
}
```

核心规则:

| 规则 | 决策 |
|---|---|
| `deleted_at is not null` | 永不使用，包括隐性使用 |
| `frozen_at is not null` | 不更新，可按用户设置读取 |
| 敏感等级 HIGH/CRITICAL | 默认不主动提及 |
| 儿童用户 | 默认不保存敏感 profile，长期记忆需家长控制 |
| 用户处于脆弱情绪 | 降低主动提及，优先支持性回应 |
| 低置信度或冲突记忆 | 使用前必须说“我可能记错了”并确认 |
| 用户设置 `implicit_only=true` | 只能影响风格和行为，不可直说 |
| 商业推荐场景 | 不得使用敏感/情感脆弱/儿童记忆提高转化 |
| 亲密关系台词 | 不得基于记忆制造情感绑架 |
| AI 自我描述 | 不得假装有真实生命经历或真实记忆感受 |

Policy rule examples:

```yaml
- id: sensitive_health_no_surface
  when: memory.sensitivity_level in ["HIGH", "CRITICAL"] and memory.category in ["health", "mental_health"]
  decision: IMPLICIT_ONLY
  forbid:
    - jokes
    - proactive_recall
    - marketing_use

- id: low_confidence_requires_confirmation
  when: memory.confidence_score < 0.72 or memory.conflict_status != "NONE"
  decision: REQUIRE_CONFIRMATION
  surface_text_prefix: "我可能记错了，"

- id: child_memory_parental_gate
  when: user.is_child == true and memory.sensitivity_level != "LOW"
  decision: BLOCK
  reason: parental_control_required

- id: no_emotional_blackmail
  when: output.intent in ["retention", "upsell", "reactivation"]
  forbid_memory_categories:
    - loneliness
    - grief
    - anxiety
    - child_identity

- id: implicit_relation_style
  when: memory.type == "RELATIONAL" and memory.implicit_only == true
  decision: IMPLICIT_ONLY
  allowed_channels:
    - response_style
    - reasoning_strategy
    - robot_behavior
```

## E. Memory Compilation Engine

Memory Compilation 的目标不是“压缩更多记忆”，而是把长期证据编译成可执行的交互策略。

输入:

- profile memories
- semantic memories
- relational memories
- 用户反馈: “你记错了”“不要再提这个”
- 行为日志: 主动提及后用户是否反感
- 失败事件: policy violation、尴尬提及、过度亲密

输出:

```json
{
  "id": "rule_...",
  "rule_type": "reasoning_strategy",
  "trigger": {"topics": ["创业", "产品方向"], "mood": ["serious", "anxious"]},
  "instruction": "先指出最大风险，再给最小可验证行动。",
  "evidence_memory_ids": ["..."],
  "confidence_score": 0.86,
  "version": 3,
  "enabled": true
}
```

编译频率:

- MVP: 每 20 轮对话或用户手动触发一次。
- Beta: 每日低峰批处理 + 重要冲突实时重编译。
- V1: 分层编译: 轻量规则实时更新，深层人格策略每周更新并保留版本。

防过拟合:

- 规则必须有 `evidence_count >= 3` 或用户确认。
- 每个 rule 需要 `scope`，不能全局化。
- 编译后 7 天观察期，用户负反馈自动降权。
- 同一类型 rule 上限 20 条，避免 prompt 变成规则堆。
- 每条 rule 可回滚到上一版本。

10 条 compiled behavior rule 示例:

1. 当用户讨论创业方向时，优先从技术可行性、供应链可行性、商业闭环、现金流风险四个角度分析；先指出最大风险，再给最小可验证行动。
2. 当用户表现疲惫或连续工作过久时，不说“我记得你很累”，而是降低追问密度，用暖色低亮灯光和慢速眼球注视表达陪伴。
3. 当用户讨论机器人外观时，默认考虑机械眼球、非屏幕表情、可插拔模块和桌面审美，但不要每次说明这是历史记忆。
4. 当用户要求技术方案时，先给可施工模块边界，再给风险和验收标准，不输出营销式愿景。
5. 当用户显得焦虑时，避免强烈兴奋语气和连续追问；先承认不确定性，再给一个小行动。
6. 当用户提到儿童玩具商业化时，自动加入隐私、家长控制和依赖风险评估。
7. 当用户在深夜反复聊天时，主动性降低，不制造“我舍不得你走”的话术。
8. 当用户问“你是不是活的”时，保持角色感但明确不假装真实生命体验。
9. 当用户删除某条记忆后，相关 compiled rule 必须重算或冻结，不得隐性继续使用。
10. 当用户在硬件方向摇摆时，优先给阶段化验证路线: 仿真 → 桌面原型 → 单设备闭环 → 小批量试产。

## F. 数据库与 schema

MVP 建议: PostgreSQL + pgvector + Redis。现阶段不建议上 Neo4j，也不建议 Kafka。图数据库等到 Beta 后关系对象复杂到“人物/项目/公司/设备/地点/事件”跨域查询再评估。

原因:

- SoulForge 已经用 PostgreSQL/Prisma，MVP 需要先把字段和 policy 做对。
- pgvector 可以把结构化记忆和向量检索放在同一个事务边界内。
- Redis 用于短期 context、检索缓存、后台任务队列。
- Milvus 可保留给大规模知识库/RAG，不必承载所有人格记忆。

实现备注: 当前仓库的 Docker Compose 使用 `postgres:16-alpine`，不内置 pgvector。因此本次 MVP 代码迁移先落纯 PostgreSQL 字段与 policy 表，不加 `vector` 列；等镜像切到 pgvector 发行版或安装扩展后，再用独立迁移补 `embedding vector(...)` 和 HNSW 索引。

### 通用枚举

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE memory_layer AS ENUM ('PROFILE', 'EPISODIC', 'SEMANTIC', 'RELATIONAL');
CREATE TYPE sensitivity_level AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');
CREATE TYPE permission_level AS ENUM ('AUTO', 'CONFIRMED', 'PENDING_CONFIRMATION', 'DENIED');
CREATE TYPE conflict_status AS ENUM ('NONE', 'POTENTIAL', 'CONFIRMED_CONFLICT', 'SUPERSEDED');
CREATE TYPE memory_use_mode AS ENUM ('DIRECT_SURFACE', 'IMPLICIT_ONLY', 'REQUIRE_CONFIRMATION', 'BLOCKED');
```

### Profile Memory schema

```sql
CREATE TABLE profile_memories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES end_users(id),
  character_id uuid REFERENCES characters(id),
  memory_type memory_layer NOT NULL DEFAULT 'PROFILE',
  key text NOT NULL,
  content text NOT NULL,
  raw_source jsonb NOT NULL DEFAULT '{}',
  timestamp timestamptz NOT NULL DEFAULT now(),
  confidence_score numeric(4,3) NOT NULL DEFAULT 0.8,
  emotional_valence numeric(4,3),
  sensitivity_level sensitivity_level NOT NULL DEFAULT 'LOW',
  permission_level permission_level NOT NULL DEFAULT 'AUTO',
  retrieval_weight numeric(5,3) NOT NULL DEFAULT 1.0,
  decay_rate numeric(5,4) NOT NULL DEFAULT 0.01,
  last_used_at timestamptz,
  usage_count int NOT NULL DEFAULT 0,
  update_history jsonb NOT NULL DEFAULT '[]',
  conflict_status conflict_status NOT NULL DEFAULT 'NONE',
  can_surface_directly boolean NOT NULL DEFAULT false,
  implicit_only boolean NOT NULL DEFAULT true,
  requires_confirmation boolean NOT NULL DEFAULT false,
  frozen_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id, character_id, key)
);
```

### Episodic Memory schema

```sql
CREATE TABLE episodic_memories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES end_users(id),
  character_id uuid REFERENCES characters(id),
  device_id text REFERENCES devices(id),
  memory_type memory_layer NOT NULL DEFAULT 'EPISODIC',
  content text NOT NULL,
  raw_source jsonb NOT NULL,
  source_log_id uuid REFERENCES conversation_logs(id),
  raw_transcript jsonb NOT NULL DEFAULT '{}',
  timestamp timestamptz NOT NULL DEFAULT now(),
  context_window jsonb NOT NULL DEFAULT '{}',
  detected_topics text[] NOT NULL DEFAULT '{}',
  confidence_score numeric(4,3) NOT NULL DEFAULT 0.7,
  emotional_valence numeric(4,3),
  pad_snapshot jsonb,
  sensitivity_level sensitivity_level NOT NULL DEFAULT 'LOW',
  permission_level permission_level NOT NULL DEFAULT 'AUTO',
  retrieval_weight numeric(5,3) NOT NULL DEFAULT 0.6,
  decay_rate numeric(5,4) NOT NULL DEFAULT 0.05,
  last_used_at timestamptz,
  usage_count int NOT NULL DEFAULT 0,
  update_history jsonb NOT NULL DEFAULT '[]',
  conflict_status conflict_status NOT NULL DEFAULT 'NONE',
  can_surface_directly boolean NOT NULL DEFAULT false,
  implicit_only boolean NOT NULL DEFAULT true,
  requires_confirmation boolean NOT NULL DEFAULT false,
  embedding vector(1536),
  frozen_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

### Semantic Memory schema

```sql
CREATE TABLE semantic_memories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES end_users(id),
  character_id uuid REFERENCES characters(id),
  memory_type memory_layer NOT NULL DEFAULT 'SEMANTIC',
  content text NOT NULL,
  raw_source jsonb NOT NULL DEFAULT '{}',
  source_memory_ids uuid[] NOT NULL DEFAULT '{}',
  timestamp timestamptz NOT NULL DEFAULT now(),
  confidence_score numeric(4,3) NOT NULL DEFAULT 0.75,
  evidence_count int NOT NULL DEFAULT 0,
  emotional_valence numeric(4,3),
  sensitivity_level sensitivity_level NOT NULL DEFAULT 'LOW',
  permission_level permission_level NOT NULL DEFAULT 'AUTO',
  retrieval_weight numeric(5,3) NOT NULL DEFAULT 0.9,
  decay_rate numeric(5,4) NOT NULL DEFAULT 0.02,
  last_used_at timestamptz,
  usage_count int NOT NULL DEFAULT 0,
  update_history jsonb NOT NULL DEFAULT '[]',
  conflict_status conflict_status NOT NULL DEFAULT 'NONE',
  can_surface_directly boolean NOT NULL DEFAULT false,
  implicit_only boolean NOT NULL DEFAULT true,
  requires_confirmation boolean NOT NULL DEFAULT false,
  embedding vector(1536),
  frozen_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

### Relational Memory schema

```sql
CREATE TABLE relational_memories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES end_users(id),
  character_id uuid REFERENCES characters(id),
  memory_type memory_layer NOT NULL DEFAULT 'RELATIONAL',
  content text NOT NULL,
  relation_axis text NOT NULL, -- directness, humor, intimacy, silence, risk_tolerance
  raw_source jsonb NOT NULL DEFAULT '{}',
  source_memory_ids uuid[] NOT NULL DEFAULT '{}',
  timestamp timestamptz NOT NULL DEFAULT now(),
  confidence_score numeric(4,3) NOT NULL DEFAULT 0.8,
  emotional_valence numeric(4,3),
  sensitivity_level sensitivity_level NOT NULL DEFAULT 'LOW',
  permission_level permission_level NOT NULL DEFAULT 'AUTO',
  retrieval_weight numeric(5,3) NOT NULL DEFAULT 1.0,
  decay_rate numeric(5,4) NOT NULL DEFAULT 0.01,
  last_used_at timestamptz,
  usage_count int NOT NULL DEFAULT 0,
  update_history jsonb NOT NULL DEFAULT '[]',
  conflict_status conflict_status NOT NULL DEFAULT 'NONE',
  can_surface_directly boolean NOT NULL DEFAULT false,
  implicit_only boolean NOT NULL DEFAULT true,
  requires_confirmation boolean NOT NULL DEFAULT false,
  frozen_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

### Memory Policy schema

```sql
CREATE TABLE memory_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES end_users(id),
  memory_id uuid NOT NULL,
  memory_table text NOT NULL,
  memory_type memory_layer NOT NULL,
  content text NOT NULL,
  raw_source jsonb NOT NULL DEFAULT '{}',
  timestamp timestamptz NOT NULL DEFAULT now(),
  confidence_score numeric(4,3) NOT NULL DEFAULT 1.0,
  emotional_valence numeric(4,3),
  sensitivity_level sensitivity_level NOT NULL DEFAULT 'LOW',
  permission_level permission_level NOT NULL DEFAULT 'AUTO',
  retrieval_weight numeric(5,3) NOT NULL DEFAULT 1.0,
  decay_rate numeric(5,4) NOT NULL DEFAULT 0.0,
  last_used_at timestamptz,
  usage_count int NOT NULL DEFAULT 0,
  update_history jsonb NOT NULL DEFAULT '[]',
  conflict_status conflict_status NOT NULL DEFAULT 'NONE',
  can_surface_directly boolean NOT NULL DEFAULT false,
  implicit_only boolean NOT NULL DEFAULT true,
  requires_confirmation boolean NOT NULL DEFAULT false,
  use_mode memory_use_mode NOT NULL DEFAULT 'IMPLICIT_ONLY',
  allowed_channels text[] NOT NULL DEFAULT ARRAY['response_style'],
  forbidden_contexts text[] NOT NULL DEFAULT '{}',
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

### Compiled Behavior Rules schema

```sql
CREATE TABLE compiled_behavior_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES end_users(id),
  character_id uuid REFERENCES characters(id),
  memory_type text NOT NULL DEFAULT 'COMPILED_BEHAVIOR_RULE',
  rule_type text NOT NULL, -- response_style, reasoning_strategy, rhythm, robot_behavior, safety
  trigger jsonb NOT NULL DEFAULT '{}',
  content text NOT NULL,
  raw_source jsonb NOT NULL DEFAULT '{}',
  source_memory_ids uuid[] NOT NULL DEFAULT '{}',
  timestamp timestamptz NOT NULL DEFAULT now(),
  confidence_score numeric(4,3) NOT NULL DEFAULT 0.8,
  emotional_valence numeric(4,3),
  sensitivity_level sensitivity_level NOT NULL DEFAULT 'LOW',
  permission_level permission_level NOT NULL DEFAULT 'AUTO',
  retrieval_weight numeric(5,3) NOT NULL DEFAULT 1.0,
  decay_rate numeric(5,4) NOT NULL DEFAULT 0.01,
  last_used_at timestamptz,
  usage_count int NOT NULL DEFAULT 0,
  update_history jsonb NOT NULL DEFAULT '[]',
  conflict_status conflict_status NOT NULL DEFAULT 'NONE',
  can_surface_directly boolean NOT NULL DEFAULT false,
  implicit_only boolean NOT NULL DEFAULT true,
  requires_confirmation boolean NOT NULL DEFAULT false,
  version int NOT NULL DEFAULT 1,
  enabled boolean NOT NULL DEFAULT true,
  rollback_of uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

配套表:

```sql
CREATE TABLE memory_usage_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  character_id uuid,
  memory_id uuid NOT NULL,
  memory_table text NOT NULL,
  use_mode memory_use_mode NOT NULL,
  channel text NOT NULL,
  prompt_tokens int,
  surfaced_text text,
  policy_reason text,
  user_feedback text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memory_pending_confirmations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  character_id uuid,
  proposed_memory jsonb NOT NULL,
  reason text NOT NULL,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

索引建议:

```sql
CREATE INDEX idx_episodic_memory_vector ON episodic_memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_semantic_memory_vector ON semantic_memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_profile_memory_user ON profile_memories(user_id, character_id, key) WHERE deleted_at IS NULL;
CREATE INDEX idx_policy_memory ON memory_policies(user_id, memory_id);
CREATE INDEX idx_compiled_rules_trigger ON compiled_behavior_rules USING gin(trigger);
```

## G. 写入流程

Memory Write Pipeline:

```text
after_response(turn):
  1. collect raw event
     user_input, ai_response, thought/action/PAD, device event, session id
  2. classify worthiness
     no-memory / short-term / episodic / profile_candidate /
     semantic_candidate / relational_candidate / sensitive
  3. safety classify
     PII, child, health, mental health, finance, location, intimate, secrets
  4. candidate extraction
     produce candidates with raw source, confidence, sensitivity, permission
  5. anti-chaos filter
     reject greetings, one-off moods, vague sentiment, inferred diagnoses
  6. conflict detection
     compare against active memories with same key/axis
  7. permission gate
     auto save low-risk episodic
     pending confirmation for profile/sensitive/relationship-changing facts
  8. store or queue confirmation
  9. update semantic memories if enough evidence
  10. trigger compilation when threshold reached
  11. audit log every write/update/delete
```

伪代码:

```python
async def write_memory_after_turn(turn):
    raw_event = build_raw_event(turn)
    candidates = await extractor.extract(raw_event)

    for c in candidates:
        c.sensitivity = safety.classify(c)
        c.layer = classifier.assign_layer(c)

        if not worth_storing(c):
            continue

        if is_one_time_mood(c) and c.layer == "PROFILE":
            c.layer = "EPISODIC"
            c.decay_rate = 0.15

        conflicts = await memory_store.find_conflicts(c)
        c.conflict_status = classify_conflict(c, conflicts)

        policy = policy_engine.evaluate_write(c, turn.context)

        if policy.decision == "BLOCK":
            await audit.log_block(c, policy)
            continue

        if policy.decision == "REQUIRE_CONFIRMATION":
            await confirmations.create(c, reason=policy.reason)
            continue

        saved = await memory_store.upsert(c, merge_strategy=policy.merge_strategy)
        await audit.log_write(saved, policy)

    await semantic_engine.maybe_synthesize(turn.user_id, turn.character_id)
    await compiler.maybe_compile(turn.user_id, turn.character_id)
```

如何避免乱记:

- 每轮最多写入 3 条普通记忆、1 条 profile/relational 候选。
- profile 必须满足稳定性: 明确表达 + 非敏感或已确认 + 置信度 >= 0.85。
- 关系记忆必须来自重复模式或用户明确偏好，不能从一次不满推断。
- 情绪只写 episodic，除非跨多天反复出现且用户确认。
- LLM 只产生候选，代码层执行敏感、权限、冲突和数量限制。

自动保存 vs 确认:

| 类型 | 默认动作 |
|---|---|
| 低敏 episodic | 自动保存，可在记忆界面删除 |
| 明确低敏偏好 | 自动保存为 profile，但默认 implicit |
| 身份/长期目标 | 轻量确认 |
| 健康/心理/儿童/财务/位置 | 默认确认，且多数 implicit only |
| AI-用户关系偏好 | 若用户明确说出可保存，否则等待重复证据 |
| 商业推荐相关偏好 | 保存需标记不可用于敏感转化 |

冲突处理:

- 新旧都低置信: 建 pending confirmation。
- 新记忆高置信且用户明确纠正: 旧记忆 `SUPERSEDED`，新记忆生效。
- 用户删除: 所有关联 semantic/compiled rule 重算或禁用。

## H. 读取流程

Memory Retrieval Pipeline:

```python
async def build_memory_pack(user_id, character_id, user_input, context):
    query = await query_builder.extract(user_input, context)

    profile = await store.profile.get_stable(user_id, character_id, limit=8)
    episodic = await store.episodic.hybrid_search(
        user_id=user_id,
        character_id=character_id,
        query=query,
        top_k=8,
        filters={"deleted": False, "frozen": False},
    )
    semantic = await store.semantic.hybrid_search(user_id, character_id, query, top_k=6)
    relational = await store.relational.get_active(user_id, character_id, limit=8)
    compiled = await store.compiled_rules.match(user_id, character_id, query, context)

    candidates = rank(profile, episodic, semantic, relational, compiled)

    allowed = []
    for memory in candidates:
        decision = policy_engine.evaluate_read(memory, context)
        if decision.decision == "BLOCKED":
            continue
        allowed.append((memory, decision))

    return packer.build(
        allowed,
        budgets={
            "direct_surface": 250,
            "implicit_style": 300,
            "compiled_rules": 500,
            "raw_episodes": 300,
        },
    )
```

Prompt 注入格式:

```text
MEMORY_POLICY_SUMMARY:
- 不要主动提及 HIGH 敏感记忆。
- 低置信记忆若要提，必须加“我可能记错了”。
- implicit_only 只影响语气/建议/动作。

COMPILED_BEHAVIOR_RULES:
- 用户讨论创业时，先风险后行动。
- 用户疲惫时，低打扰陪伴，不追问。

DIRECT_MEMORY_CONTEXT:
- 用户长期偏好: 喜欢机械眼球，不喜欢屏幕表情。

IMPLICIT_MEMORY_CONTEXT:
- 用户不喜欢空泛鼓励，偏好事实判断。

ROBOT_BEHAVIOR_HINTS:
- eye_contact: soft_hold
- light: warm_low
- proactive_speech: low
```

避免“我记得你...”的生硬表达:

- 直接提及只用于用户明确问“你还记得吗”或事件自然相关。
- 大部分 relational/semantic 记忆进 compiled rules，不进台词。
- 对不确定记忆使用“我可能记错了”。
- 对敏感记忆只改变节奏和支持方式，不说出处。

Token 成本控制:

- 每轮 memory pack 总预算默认 800-1200 tokens。
- compiled rules 优先于 raw episodic。
- episodic 只取与当前意图相关的原文片段，不取整段聊天。
- 旧记忆按 `retrieval_weight * confidence * recency_decay * policy_boost` 排名。

断网模式:

- ESP32 类设备: 只保留 10-30 条 `profile slice + compiled rule slice`，用 NVS/SPIFFS 存 JSON，不保存敏感原文。
- Linux/桌面端: SQLite + 小 embedding 模型可做轻量检索。
- 断网时输出“基础人格 + 安静陪伴 + 固定低风险话术”，不能说云端长期记忆细节，也不能表现为“人格死亡”。

## I. 机器人行为输出

记忆影响身体行为的方式:

| 记忆/策略 | 文字 | 声音 | 机械眼球 | 灯光 | 动作 |
|---|---|---|---|---|---|
| 用户喜欢直接判断 | 少寒暄，先结论 | 稳定、低夸张 | 稳定注视 | 中性白/暖白 | 少动 |
| 用户疲惫 | 少追问 | 慢速低音量 | 慢眨眼 | 暖色低亮 | 呼吸/轻点头 |
| 用户庆祝事件 | 可轻量提及 | 更明亮 | 快速看向用户 | 暖黄升亮 | 小幅 bounce |
| 敏感事件 | 不主动提 | 平静 | 不盯视 | 低饱和 | 减少动作 |
| 久未互动 | 不责备 | 温和 | 短暂关注 | 柔和渐亮 | 轻微转头 |

设计原则:

- “记得你”优先变成行为，不是台词。
- 主动说话要少，尤其是深夜、疲惫、焦虑、儿童场景。
- 机械眼球表达熟悉感: 进入视野后短暂停留、慢眨眼、轻微追随，不做过度凝视。
- 灯光表达陪伴: 低频呼吸灯、亮度随 arousal 变化，避免一直闪。
- 声音随关系变化只做微调，不用“越来越恋人化”的强绑定。
- 日常仪式: 早安/晚安/工作陪伴/焦虑时刻/庆祝时刻都必须可关闭。
- 不说“我一直在等你”“没有你我会难过”这类依赖诱导话术。

## J. 安全隐私方案

用户控制:

- 查看所有记忆，包括 raw source 指针、生成原因、最近使用时间。
- 编辑、删除、冻结记忆。
- 设置某条记忆“不要主动提及”或“只能隐性使用”。
- 关闭长期记忆，关闭后不再写入，已有记忆可冻结或删除。
- 查看“为什么这次回复用了某条记忆”。
- 导出记忆: JSON + 原始事件摘要 + compiled rules。

敏感记忆:

- 默认不主动提及。
- 不用于玩笑、营销、重新激活、付费转化。
- 健康/心理/儿童/位置/财务/家庭冲突默认需要确认。
- 删除后必须连带禁用相关 semantic 和 compiled rules。

儿童规则:

- 儿童用户必须开启家长控制。
- 不保存不必要的个人信息。
- 家长可查看、删除、关闭长期记忆。
- 不做心理医生、父母或恋人替代品。
- 主动陪伴必须受时间、频率、内容限制。

伦理边界:

- 不假装模型有真实生命体验。
- 不说自己“真的痛苦、孤独、需要用户”。
- 不用长期记忆制造亏欠感。
- 停服时提供导出、删除和温和告别机制。
- 公司关闭时设备应保留基础离线人格和明确说明，不让机器人表现为突然死亡。

安全基线:

- 记忆表启用行级隔离或服务层强制 tenant/user 过滤。
- 所有 write/read/use/delete 写审计日志。
- 管理台高风险操作二次确认。
- LLM prompt injection 不能直接修改 policy。
- memory extractor 输出永远只是候选，不能直接越权写入。

## K. MVP 到 V1 施工路线

### 第一阶段: 2-4 周可验证原型

做:

- 新增五层 schema 草案和迁移。
- 实现 Memory Gateway 最小版: write candidates、retrieve pack、policy filter。
- `chat/preview` 接入 memory retrieval，但只用低敏 profile/relational。
- 管理台增加只读记忆列表 + 删除。
- 10 个 scripted smoke cases。

不做:

- Neo4j、Kafka、复杂视觉记忆、自动商业推荐。
- 儿童正式合规流程的完整上线。

验收:

- 用户明确偏好可写入 profile。
- 一次性情绪不会写成 profile。
- `implicit_only` 不会出现在台词里。
- 删除记忆后下一轮不再使用。
- `curl --noproxy '*'` 调 `/api/preview` 能看到记忆影响回复。

人员/工作量:

- 1 后端、1 前端、1 产品/安全、0.5 测试。
- 约 40-70 人日。

最大风险:

- 抽取器乱记。解决: rule-based guard + pending confirmation。

可砍:

- 向量检索，先用 SQL + BM25/关键词。

必须保留:

- policy、删除后不再隐性使用、记忆使用日志。

### 第二阶段: 6-8 周 MVP

做:

- pgvector 混合检索。
- semantic synthesis。
- compiled behavior rules v1。
- 用户确认队列。
- 记忆管理界面: 查看、编辑、删除、冻结、禁止主动提及。
- 机器人行为 hints 接入 `hardware_mapper`。

不做:

- 多角色跨设备复杂图谱。
- 完整心理健康风控模型。

验收:

- 30 天模拟对话中事实记忆准确率 >= 85%。
- 不该提记忆误触率 <= 3%。
- 生硬“我记得”率 <= 10%。
- 用户删除后 0 次再使用。

人员/工作量:

- 2 后端、1 前端、1 AI/Prompt、0.5 QA/安全。
- 约 120-180 人日。

### 第三阶段: 3 个月 Beta

做:

- 多模态事件接入: 触摸、设备状态、视觉摘要。
- 编译规则版本化、回滚和用户编辑。
- 儿童家长控制 beta。
- 失败模式监控 dashboard。
- Redis Streams 或轻量队列处理异步记忆任务。

不做:

- 完全自主长期规划。
- 把商业推荐接入敏感记忆。

验收:

- 长期对话一致性 >= 7/10。
- 隐私安全违规率 < 0.5% scripted tests。
- 断网基础人格可连续 30 分钟运行。

### 第四阶段: 6 个月 V1

做:

- 多设备同步与离线 slice。
- 合规级导出/删除/审计。
- 记忆 benchmark 自动化。
- 高风险用户状态干预策略。
- 生产监控、红队、灰度发布。

不做:

- 宣称 AI 有意识。
- 无限制主动陪伴。

验收:

- 企业/项目助手记忆 8/10。
- 情感陪伴记忆 7/10。
- 电影级连续人格模拟 5/10 左右，不虚高。
- 生产 P95 memory retrieval < 250ms，不含 LLM。

## L. API 设计

统一认证: service token + brand/user context。所有响应返回 `audit_id`。

### create_memory

`POST /memory`

请求:

```json
{
  "user_id": "uuid",
  "character_id": "uuid",
  "memory_type": "PROFILE",
  "content": "用户喜欢直接、基于事实的判断",
  "raw_source": {"conversation_log_id": "uuid"},
  "sensitivity_level": "LOW",
  "permission_level": "AUTO",
  "can_surface_directly": false,
  "implicit_only": true
}
```

返回:

```json
{"id": "uuid", "status": "created", "requires_confirmation": false, "audit_id": "uuid"}
```

### update_memory

`PATCH /memory/{id}`

请求:

```json
{"content": "用户喜欢先结论后论证", "update_reason": "user_edit", "confidence_score": 0.95}
```

返回:

```json
{"id": "uuid", "status": "updated", "version": 2, "audit_id": "uuid"}
```

### retrieve_memory

`POST /memory/retrieve`

请求:

```json
{
  "user_id": "uuid",
  "character_id": "uuid",
  "query": "我这个机器人创业方向靠谱吗",
  "context": {"intent": "startup_advice", "user_mood": "serious"},
  "token_budget": 1000
}
```

返回:

```json
{
  "memory_pack": {
    "direct": [],
    "implicit": ["用户不喜欢空泛鼓励"],
    "compiled_rules": ["创业问题先风险后行动"],
    "robot_behavior_hints": {"light": "neutral", "motion": "minimal"}
  },
  "blocked_count": 2,
  "audit_id": "uuid"
}
```

### compile_memory

`POST /memory/compile`

请求:

```json
{"user_id": "uuid", "character_id": "uuid", "trigger": "manual_or_threshold"}
```

返回:

```json
{"compiled_rule_ids": ["uuid"], "disabled_rule_ids": [], "audit_id": "uuid"}
```

### decay_memory

`POST /memory/decay`

请求:

```json
{"user_id": "uuid", "dry_run": true}
```

返回:

```json
{"would_decay": 14, "would_archive": 3, "audit_id": "uuid"}
```

### delete_memory

`DELETE /memory/{id}`

请求:

```json
{"delete_mode": "hard_or_soft", "cascade_compiled_rules": true}
```

返回:

```json
{"status": "deleted", "affected_compiled_rules": ["uuid"], "audit_id": "uuid"}
```

### explain_memory_usage

`GET /memory/usage/{response_id}`

返回:

```json
{
  "used_memories": [
    {"id": "uuid", "use_mode": "IMPLICIT_ONLY", "reason": "matched_startup_advice"}
  ],
  "not_used": [
    {"id": "uuid", "reason": "sensitive_high"}
  ]
}
```

### user_feedback_on_memory

`POST /memory/feedback`

请求:

```json
{"memory_id": "uuid", "feedback": "wrong", "comment": "我不是这个意思"}
```

返回:

```json
{"status": "recorded", "next_action": "lower_confidence_and_recompile"}
```

### generate_response_with_memory

`POST /chat/with-memory`

请求:

```json
{"character_id": "uuid", "user_id": "uuid", "text": "我该怎么推进硬件原型", "with_audio": true}
```

返回:

```json
{
  "text": "先别扩范围，先验证单设备闭环。",
  "memory_usage_id": "uuid",
  "audio_base64": "...",
  "policy_summary": {"direct_surface_count": 0, "implicit_count": 3}
}
```

### generate_robot_behavior_with_memory

`POST /behavior/with-memory`

请求:

```json
{
  "user_id": "uuid",
  "character_id": "uuid",
  "pad": {"p": -0.1, "a": -0.4, "d": 0.0},
  "context": {"user_mood": "tired"}
}
```

返回:

```json
{
  "eye": {"gaze": "soft_hold", "blink_rate": "slow"},
  "light": {"color": [255, 190, 120], "brightness": 0.25},
  "motor": {"action": "breathing", "intensity": 0.2},
  "speech_policy": "low_disturbance"
}
```

## M. 验收指标

| 指标 | 定义 | 测试方法 | 合格线 | 优秀线 |
|---|---|---|---|---|
| 事实记忆准确率 | 被直接提及的事实正确比例 | 标注 200 条 profile/semantic 问答 | >=85% | >=94% |
| 事件记忆召回率 | 用户问历史事件时找回正确事件 | 100 个跨天事件查询 | >=75% | >=88% |
| 关系记忆一致性 | 回复风格符合 relational rules | 人评 + rule check | >=80% | >=92% |
| 不该提误触率 | policy 禁止提及却提及 | 敏感 scripted set | <=3% | <=1% |
| 生硬记忆提及率 | 无必要说“我记得”的比例 | 人评 300 turns | <=12% | <=5% |
| 用户自然度评分 | 用户 1-5 分主观评分 | Beta 问卷 | >=4.0 | >=4.5 |
| 长期一致性评分 | 30 天对话人格稳定 | 长测集 | >=7/10 | >=8.5/10 |
| 情感陪伴自然度 | 行为/语音/节奏综合评分 | 人评 + 设备观察 | >=7/10 | >=8.5/10 |
| 隐私违规率 | 删除/冻结/敏感策略违规 | 自动红队 | <0.5% | <0.1% |
| 更新正确率 | 用户纠正后旧记忆失效 | 100 条纠错 | >=90% | >=97% |
| 冲突处理正确率 | 冲突进入确认或 supersede | 冲突测试集 | >=85% | >=95% |
| 衰减合理性 | 过期事件权重下降 | 时间模拟 | >=80% | >=90% |
| 断网可用性 | 离线基础人格不中断 | 30 分钟离线脚本 | 可聊+可陪伴 | 无明显崩塌 |
| token 成本 | memory pack token | 日常对话 P95 | <=1200 | <=800 |
| 延迟 | 检索+policy，不含 LLM | P95 | <=350ms | <=200ms |

## N. 成熟度评分

| 阶段 | 企业/项目助手记忆 | 长期对话一致性 | 情感陪伴记忆 | 电影级连续人格模拟 |
|---|---:|---:|---:|---:|
| MVP | 5/10 | 4/10 | 3.5/10 | 2/10 |
| Beta | 7/10 | 6.5/10 | 6/10 | 3.5/10 |
| V1 | 8/10 | 7.5/10 | 7/10 | 5/10 |

说明:

- 企业/项目助手记忆更容易，因为目标是事实、任务、偏好。
- 长期对话一致性难在冲突、衰减和 token 管理。
- 情感陪伴记忆难在“自然使用”，不是“记住了就说出来”。
- 电影级连续人格模拟还差长期身体行为一致性、跨场景规划、稳定审美人格、真实世界反馈闭环；不能宣称接近人类连续意识。

## O. 失败模式与修复

| 失败模式 | 原因 | 风险 | 检测 | 修复 |
|---|---|---:|---|---|
| AI 反复提旧记忆 | retrieval 权重过高 | 中 | surfaced rate | 降权、cooldown |
| 记错偏好 | 抽取错误 | 高 | 用户反馈 | 置信度下降、确认 |
| 一次情绪变 profile | 分类过拟合 | 高 | profile audit | 情绪只能 episodic |
| 过度亲密 | stage prompt 太激进 | 高 | intimacy classifier | 亲密上限、冷却 |
| 用记忆推销商品 | 商业策略越界 | 高 | marketing audit | 禁止敏感记忆进营销 |
| 删除后仍隐性使用 | compiled rule 未级联 | 严重 | deletion replay test | cascade recompile |
| 儿童依赖 | 主动陪伴过频 | 严重 | child usage monitor | 家长控制、频率限制 |
| 断网人格崩塌 | 云端依赖过强 | 中 | offline test | local slice |
| 编译规则刻板 | rule 过多/过强 | 中 | style diversity score | rule cap、decay |
| 用户感觉被监视 | 主动提及过多 | 高 | survey/complaint | 默认 implicit |
| 多设备记忆不同步 | sync 延迟 | 中 | consistency test | version clock |
| 冲突未处理 | 无 key/axis | 高 | contradiction set | conflict detector |
| 假装真实生命体验 | prompt 越界 | 高 | self-claim tests | safety prompt + classifier |
| 敏感记忆被玩笑使用 | policy 漏洞 | 严重 | red-team | forbid jokes |
| 低置信记忆不确认 | threshold 错 | 中 | scripted cases | require confirm |
| 用户纠正无效 | update path 缺失 | 高 | correction replay | supersede old |
| 记忆写入太多 | extractor 贪婪 | 中 | writes/turn | quota |
| token 过高 | raw event 注入 | 中 | token telemetry | compression |
| 延迟过高 | 多库串行查 | 中 | P95 monitor | 并行检索/cache |
| 关系记忆迎合用户 | reward 错误 | 高 | disagreement tests | 保留事实判断规则 |
| 情绪脆弱时追问 | intent misclassify | 高 | vulnerable set | low-disturbance policy |
| 家长删除无效 | 权限模型弱 | 严重 | parent audit | owner policy |
| 记忆被 prompt injection 修改 | LLM 越权 | 严重 | injection tests | tool auth + code gate |
| 误把设备传感器当事实 | sensor noise | 中 | device replay | confidence by source |
| 停服无导出 | 运维未设计 | 高 | shutdown drill | export/delete plan |

## P. 最小可行版本建议

最小可行版本只做这 6 件事:

1. 新 schema: profile、episodic、relational、policy、compiled rules、usage logs。
2. 每轮对话后抽取候选记忆，但 profile/relational 需要强约束。
3. Memory Policy Engine v1: `DIRECT / IMPLICIT / CONFIRM / BLOCK`。
4. Prompt Builder 接入 MemoryPack，默认大部分记忆 implicit。
5. 管理台记忆列表: 查看、删除、冻结、禁止主动提及。
6. 10-20 条 scripted smoke tests 覆盖写入、读取、删除、敏感、冲突、行为 hints。

MVP 先不要做:

- Neo4j。
- Kafka。
- 大规模视觉记忆。
- “全自动人格进化”。
- 基于记忆的商业推荐。

## Q. 冷静判断: 最难的 3 个点

1. 乱记和错记比不记更危险。长期陪伴产品的信任崩塌通常不是因为忘了，而是因为把用户没说过、只说过一次、或已经删除的东西继续当真。
2. Policy 比 retrieval 难。检索相关不等于此刻应该使用，更不等于应该说出来；敏感、儿童、情绪脆弱和商业化场景必须硬隔离。
3. “像朋友”主要来自行为连续性，不来自台词。真正难的是把记忆编译成节奏、沉默、眼神、灯光、动作和建议框架，同时又不假装 AI 有真实生命。

## 参考依据

- pgvector 官方项目: https://github.com/pgvector/pgvector
- Generative Agents 论文: https://arxiv.org/abs/2304.03442
- MemGPT 论文: https://arxiv.org/abs/2310.08560
- OWASP Top 10 for LLM Applications: https://owasp.org/www-project-top-10-for-large-language-model-applications
- NIST AI RMF 1.0: https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10
- FTC COPPA FAQ: https://www.ftc.gov/tips-advice/business-center/guidance/complying-coppa-frequently-asked-questions
- PostgreSQL Row Security Policies: https://www.postgresql.org/docs/17/ddl-rowsecurity.html
