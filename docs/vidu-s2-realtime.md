# Vidu S2 实时版接入

2026-09-18。接口实测见 `docs/video-avatar-providers.md`，这里只讲接法。

选的是**实时版**（`POST /live/s_avatar/realtime`），不是组件版。
实时版里 Vidu 跑 ASR / LLM / TTS 并渲染角色，RTC 频道也由它自己开，
我们不需要自备 RTC。代价是这条链路上原有的 Fish TTS、DashScope ASR、
DeepSeek 都被绕过，内置语音模型是 `qwen_omni`（可切 `doubao`）。

## 记忆不交出去

实时版唯一没有交给 Vidu 的是记忆。`memory_retrieval.provider` 设为 `self`，
Vidu 的模型需要回忆时反过来调我们的 `/vidu/memory/retrieve`，
统一认知层仍然是"角色知道用户什么"的唯一事实来源。

不这么做的话会有两套互不知情的记忆：Vidu 内置的长期记忆
（`provider: vidu` + `enable_write`）会自己从对话里抽取并写回，
而它抽出来的东西统一认知看不见。

```
Vidu 模型需要回忆
      │  POST /vidu/memory/retrieve
      │  Authorization: Bearer <签名会话令牌>
      ▼
ai-core  api/vidu_retrieval.py
      │  retrieve_memory_pack(end_user_id, character_id, query)
      ▼
统一认知记忆层（五层记忆 + 读策略）
```

## 身份怎么传

Vidu 的外部记忆协议请求体里只有 `live_id`，**没有用户标识**。
但 `endpoint` 和 `authorization` 是建会话时逐会话配置的，
所以身份绑定放在 `authorization` 里：

`ai_core/services/vidu_session_token.py` 用 `MASTER_SECRET` 派生出一个
用途隔离的密钥，签出 `v1.<payload>.<hmac>` 形式的令牌，
payload 里带 `u`（end user）、`c`（character）、`l`（live id）、`exp`。
这样用户标识不必出现在回调 URL 里，令牌本身既是鉴权也是路由键——
只有拿到合法签名才能指定读谁的记忆。

`l` 在建会话时是空的（`live_id` 要等 CreateLive 返回才有），
此时令牌绑到用户而非单场会话；若日后拿到 `live_id` 再签一个带 `l` 的，
校验时会拒绝跨会话使用。令牌默认 8 小时有效，覆盖单场上限 7200s。

这条路径不能走 ai-core 现有的 `AuthMiddleware`：Vidu 只会原样转发一个字符串，
给不出 JWE，也给不出 `sk-` 开头的 API key。所以 `/vidu/memory/retrieve`
列在 `SELF_AUTHENTICATED_PATHS` 里跳过中间件，**在路由内部自己做常数时间 HMAC 校验**，
没签名的请求一律 401。跳过中间件不等于不鉴权。

## 隐私边界：这是最容易接错的地方

`retrieve_memory_pack` 把结果分成两类：`direct`（角色可以自然说出口）
和 `implicit`（只能影响行为、不能复述来源）。**Vidu 的协议没有这个区分**，
返回的 `memories[].summary` 会整条进模型上下文，模型可以照着念。

裸接的后果是具体的：一条"用户最近在服用抗焦虑药物"的隐性长期画像，
会被数字人直接念出来。这是隐私回归，不是风格问题。

所以上线的做法是：
- 写进 `summary` 的是 `prompt_text` 而不是 `content`——
  `prompt_text` 自带 `[可自然提及]` / `[隐性长期画像，不要直说来源]` 这类标记；
- 建会话时把 `MEMORY_TOOL_INSTRUCTION` 传给 `memory_retrieval.tool_instruction`
  （上限 2000 字），告诉模型每个标记该怎么执行；
- `blocked_count` 那部分策略层已经拦掉，根本不会进到这一步。

`packages/ai-core/tests/test_vidu_retrieval.py` 里
`test_implicit_memories_keep_their_do_not_disclose_marker` 锁的就是这条，
另有一条测试保证每个可能发出的标记在 tool_instruction 里都有对应规则——
标记发出去却没有配套规则，模型没有理由遵守。

## 层映射

| SoulForge | Vidu memory_types |
| --- | --- |
| `PROFILE` | `profile` |
| `EPISODIC` | `history` |
| `SEMANTIC` | `preference` |
| `RELATIONAL` | `relationship` |
| 编译行为规则 | `style` |

请求里带 `memory_types` 时按映射后的类型过滤；`max_results` 协议限定 1..10。

检索失败返回 **200 + 空数组 + `error` 字段**，不是 5xx：
非 2xx 会被 Vidu 规整成一个错误 tool 结果塞给模型，角色会当场卡壳。
宁可让它这一轮想不起来，也不要让它结巴。

## 怎么跑

ai-core 要能被 Vidu 的服务器访问到，`endpoint` 必须是公网可达的绝对 URL，
不能是 127.0.0.1。仓库里已有隧道机制（`LIVE_TUNNEL_PROVIDER`）。

```bash
# 只打印请求体，不建会话
python scripts/vidu_live.py --user-id u_123 \
  --avatar-image https://example.com/face.jpg \
  --public-base-url https://xxx.trycloudflare.com --dry-run

# 真建会话
VIDU_API_KEY=vda_... SOULFORGE_PUBLIC_BASE_URL=https://xxx.trycloudflare.com \
  python scripts/vidu_live.py --user-id u_123 --character-id c_joi \
  --avatar-image https://example.com/face.jpg --persona "克制、口语、允许留白"
```

建会话本身不计费，计费从客户端接上 WebSocket 开始；
建完不接的会话会 `close_reason: timeout` 自行结束，`billed_seconds` 为 0。
CreateLive 约 57s 才返回（含 avatar 预处理），别当成超时。

## 已验证与未验证

已验证：令牌签发/校验/篡改拒绝/过期/跨会话拒绝；回调端点的鉴权、
层映射、类型过滤、`max_results`、失败降级；隐性记忆标记不被剥掉；
`scripts/vidu_live.py --dry-run` 的请求体；**真实 CreateLive 接受了
完整的 `memory_retrieval`（`provider: self` + 我们的 endpoint 与 Bearer 令牌
+ tool_instruction），返回 `vidu-s2` 会话与 RTC 凭据**。
17 个单测全过。

未验证：**Vidu 实际回调我们的 endpoint**（需要公网隧道 + 起 ai-core + 接 WebSocket，
本轮没做）；因此层映射和标记在真实对话里的效果也未验证。
文档写明 Query Live 不回显 `memory_retrieval`（实测返回 null），
所以不能靠回显判断配置是否生效，只能靠回调日志 `vidu.memory.retrieved`。
另未验证：`knowledge_retrieval`（未实现）、声音克隆、action library、
`session_update` 热更新、实际单价与并发上限。
