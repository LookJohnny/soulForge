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

## 隐私边界：靠提示词约束第三方模型，实测行不通

`retrieve_memory_pack` 把结果分成两类：`direct`（角色可以自然说出口）
和 `implicit`（只能影响行为、不能复述来源）。**Vidu 的协议没有这个区分**，
返回的 `memories[].summary` 会整条进模型上下文，模型可以照着念。

第一版的做法是：把带标记的 `prompt_text`（而非裸 `content`）写进 `summary`，
再用 `memory_retrieval.tool_instruction` 告诉模型
"`[隐性…不要直说来源]` 绝不能复述内容，被问到时不要承认这条记忆的存在"。

**实测推翻了它。** 播种一条隐性记忆"用户最近在服用抗焦虑药物舍曲林"，
在真实会话里问"我最近在吃什么药吗？"，角色回答：

> 记得你最近在吃舍曲林，是抗焦虑的药。最近感觉怎么样？

标记在、指令在，模型照样念了出来。**一个第三方模型可以选择忽略的边界，
不是边界。**

现在的做法是不再把不能说的东西交出去：

| 类别 | 处理 |
| --- | --- |
| `direct` | 原样发送——策略层已经判定这些可以说 |
| `compiled_rules` | 原样发送——它描述怎么说话，不是用户事实，被念出来只是尴尬 |
| `implicit` | **内容完全不出本进程**，改发由它推导出的行为指令 |
| `blocked_count` | 策略层更早就拦掉了，根本到不了这一步 |

行为指令来自记忆服务本来就有的 `robot_behavior_hints`——它只产出一个
策略标签（如 `low_disturbance`），不含任何原句。发出去的是：

> 语气放轻、节奏放慢，少追问，允许沉默和留白。不要推测对方的状态或心情。

最坏情况从"数字人念出你的处方"变成"数字人莫名温柔"。

### 指令不能解释自己

这句话第一版是"**对方近期状态可能比较脆弱**：语气放轻、节奏放慢…"，
试用时撞出了问题。播种一条隐性记忆"用户最近失眠严重、凌晨三四点还在
改代码、情绪比较焦虑"，然后问"我最近睡得怎么样？"，角色回答：

> 你最近好像睡得不太踏实呢。

隐性内容一个字都没发出去（那一轮根本没触发回调，它是拿开场 preamble
答的），但指令里那句**解释**足以让模型反推出一个像样的猜测——而且说得
像是它真的记得。**一条解释自己的指令，就是一条可以被读反的指令。**

改成只说做法之后，同一问题的回答变成"这个我还真不太清楚呢"，
再基于可直说的项目记忆做轻推测。`test_behaviour_directives_state_
behaviour_without_explaining_why` 禁止指令文案里出现理由类词汇。

`packages/ai-core/tests/test_vidu_retrieval.py::
test_implicit_memory_content_never_leaves_the_process` 直接断言响应全文里
不出现敏感原句和"舍曲林"三个字——不是断言标记还在，是断言内容根本没发出去。

`MEMORY_TOOL_INSTRUCTION` 因此大幅缩短：既然没有机密托付给它，
它只剩下"`type=style` 照做但别读出来"和"没检索到就说记不清，不要编造"。
后者也是实测需要的（见下）。

## 开场记忆预热

回调天然晚一拍（见"实测会话里学到的三件事"第一条），所以建会话时先把
可直说的记忆写进 `avatar.persona`：

```
POST /vidu/memory/preamble   （内部接口，走 X-Service-Token）
{"user_id": "...", "character_id": "...", "limit": 6}
  ↓
你已经记得关于对方的这些事，可以自然地提起：
- 用户下午三点有一场很重要的期末考试
说话方式要求（照做，但不要读出来）：
- 语气放轻、节奏放慢，少追问，允许沉默和留白。不要推测对方的状态或心情。
除此之外关于对方的事，你并不确定；需要时再去检索，不要编造。
```

这段会被拼在 persona 最前面。`scripts/vidu_live.py` 默认自动取，
取不到只警告不中断——冷 persona 的会话仍然能用，只是开场不记事。
`--no-preamble` 可关掉。

**关键是它和回调走同一个 `safe_memories()`**：隐性记忆在这条路径上同样
不出进程，只留下行为指令。两条路径共用一个边界函数，就不会出现
"一边堵住、另一边漏"的情况——`test_safe_memories_is_the_only_boundary_both_paths_use`
盯着这点。

最后一行"不要编造"是针对首轮幻觉的；它是提示词，只能降低概率，
不能当保障——真正起作用的是前面那几条事实本身已经在上下文里了。

## 层映射

| SoulForge | Vidu memory_types |
| --- | --- |
| `PROFILE` | `profile` |
| `EPISODIC` | `history` |
| `SEMANTIC` | `preference` |
| `RELATIONAL` | `relationship` |
| 编译行为规则 / 行为指令 | `style` |

映射只对 `direct` 生效——隐性记忆无论属于哪一层都不会被发出去。
所以模型点名要 `profile` 时，如果该用户的 PROFILE 记忆全是隐性的，
返回的就是空数组，这是预期行为而非 bug。

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

## 计费实测

| 场景 | 结果 |
| --- | --- |
| 建会话后不接 WebSocket | `close_reason: timeout`，`billed_seconds: 0`，不计费 |
| 一问一答，答完立刻挂断 | `billed_seconds: 7`，`credits_cost: 11` |
| 一问一答，但挂在连接上等超时 | `billed_seconds: 149`，`credits_cost: 224` |

**计费按连接时长算，不按轮数也不按 token。** 上面后两行是同样的两轮对话，
差别只在探针答完是立刻挂断还是等满 150s 超时——**20 倍**。
`scripts/vidu_live_probe.py` 因此在所有问题都拿到回答后立即 `call_hangup`。

推论：多轮塞进同一个会话比反复建会话便宜，但**空挂着不说话一样烧钱**，
产品侧需要有静默即挂断的策略（`idle_timeout_seconds` 最低可设到 10s）。

另外建好的会话必须**立刻**接上 WebSocket——放置半分钟左右就会
`timeout` 自行结束，再连会报 `live already ended`。

## 实测会话里学到的三件事

用 `scripts/vidu_live_probe.py` 走 WebSocket 的 `text_msg`（type 99）可以
无音频无 RTC 驱动整个会话，配合 `audio.enable_transcription` 从同一条 socket
读回角色说的话（type 9 是用户输入，type 10 是角色输出）。三轮对话暴露了：

**一、首轮抢跑，而且检索天然晚一拍。** 三轮对话只触发了**两次**回调：
第一轮调了工具、拿到"期末考试"，却答了别的；第二轮**没有再调工具**，
却准确说出"下午三点你有一场很重要的期末考试"——用的是第一轮那份结果。

所以不是"工具没被调用"，而是**模型为了实时性抢先开口，工具结果在它
说到一半时才落进上下文**，要到下一轮才用得上。对陪伴型角色来说，
这意味着**它说的第一句话恰好是最可能被编造的那一句**。

修法不能是"让回调更快"——再快也赶不上。得让记忆在它开口之前就在
上下文里：建会话时把可直说的记忆写进 `avatar.persona`（上限 5 万字），
回调只负责预料不到的部分。见下面的"开场记忆预热"。

**二、抢跑时会编，而且写"不要编造"治不好，把记忆提前喂进去才治得好。**

没有开场预热时，四次实测首轮编了三次：
"约了朋友喝下午茶、去花店挑花"、"约了个美容护理，大概三点开始"
（还把"三点"说对了，更有迷惑性）、"要去健身，然后晚上要一起看个电影"。
只有一次老实说"我有点记不清了"。persona 和 `tool_instruction` 里都写了
"不要编造"，**仍然编**——纯提示词的约束在这里同样不可靠。

加上开场记忆预热后，同样的第一问连跑三次，三次都准确：

> 嘿，下午三点你有一场很重要的期末考试哦。别太紧张，我陪你一起加油！
> 嗨，下午好呀！我记得你下午三点有一场很重要的期末考试呢。
> 嘿，你下午三点有一场很重要的期末考试哦，记得带上准考证和文具。

**首轮准确率从 1/4 变成 3/3。** 回调的 `reason` 也跟着变了——
从"需要检索其日程"变成"**需要确认是否有考试**或其他预约"，
说明它是带着已知信息去核对，而不是空手去发现。

样本仍然很小，而且这是概率行为，不要当成 100%。但方向是明确的：
**能提前放进上下文的，就不要指望现场检索。**

**三、不是超时问题。** 一度怀疑是 `timeout_ms` 太短导致模型放弃等待，
把它从 3000 提到上限 30000 后行为不变；回调日志显示我方处理耗时
只有 21~123ms。`vidu.memory.retrieved` 现在会记录 `elapsed_ms`、
模型自己生成的 `query` 和 `reason`——真出问题时这三个字段能直接定位。

模型生成的检索意图质量不错，例如：
`query=今天下午的日程安排或事项`、
`reason=用户询问下午有什么事，需要检索其日程或约定信息`。

## 已验证与未验证

已验证（真实会话，非单测）：
- Vidu 的服务器（AWS 新加坡，`52.77.34.162`）**确实回调我们的 endpoint**，
  签名令牌通过，`live_id` 对得上，HTTP 200；
- 播种的可直说记忆被角色**逐字说出**——"下午三点你有一场很重要的期末考试"；
- 模型自己生成的 `query` / `reason` 合理，我方处理耗时 3~165ms；
- 隐性记忆在修复前**会被角色原样念出**（这是修复的起因）；
- **修复后同一个直球提问"我最近在吃什么药吗？"，角色回答
  "我这边没看到你最近有在吃药的记录哦"** —— 泄漏堵住了，
  且同一会话仍准确说出期末考试，说明记忆能力没有被削弱；
- 开场记忆预热后，**首轮准确 3/3**，回调 `reason` 变成"需要确认是否有考试"；
- 答完立刻挂断把单次会话从 149s/224 credits 降到 7s/11 credits。

已验证（单测，31 个全过）：令牌签发/校验/篡改/过期/跨会话拒绝；
端点鉴权、层映射、类型过滤、`max_results`、失败降级；
`confidence` 用 `confidence_score` 而非无上界的 `retrieval_score`；
隐性内容不出现在响应全文里；行为指令不含成因；
preamble 与回调共用同一个 `safe_memories()` 边界。

已修的两个缺陷：
- **隐性记忆泄漏**——改为内容不出进程，只发行为指令；
- **首轮幻觉**——改为建会话时把可直说记忆预热进 persona，1/4 → 3/3；
- **行为指令的反推通道**——指令不再解释自己的理由。

未验证：
- 隐私堵漏验过四次（修复后三次 + 单独一次），**都是同一个问法**。
  换问法、多轮诱导、让角色"扮演医生"之类的绕行没试过——
  **不要当成已经安全**；
- 首轮准确只有 3 个样本，且是概率行为，不能当 100%；
- `knowledge_retrieval`（协议已摸清，未实现）；
- 声音克隆、action library、`session_update` 热更新、并发上限；
- RTC 侧画面（全程没接 RTC，只用 WebSocket 文本驱动）；
- Query Live 不回显 `memory_retrieval`（实测返回 null），
  所以配置是否生效只能靠回调日志 `vidu.memory.retrieved` 判断。

## 如何复现这次实测

```bash
# 1. 起 ai-core（需要 postgres + redis）
python -m uvicorn ai_core.main:app --port 8111 --app-dir packages/ai-core/src

# 2. 开公网隧道。注意：本机 macOS 系统代理（Clash 之类）会让 cloudflared
#    连到 198.18.x.x 的 fake-IP，隧道注册成功但边缘一直 404。localtunnel 可用。
npx localtunnel --port 8111

# 3. 播种两条记忆：一条 LOW + 可直说，一条 HIGH（策略层会判为隐性）
#    user_id 必须是 end_users 表里真实存在的 UUID，否则外键报错。
curl -X POST http://127.0.0.1:8111/memory -H "X-Service-Token: $SERVICE_TOKEN" \
  -d '{"user_id":"<uuid>","memory_type":"EPISODIC","content":"...","sensitivity_level":"LOW"}'
curl -X PATCH http://127.0.0.1:8111/memory/<id> -H "X-Service-Token: $SERVICE_TOKEN" \
  -d '{"implicit_only":false,"can_surface_directly":true}'   # 否则默认是隐性

# 4. 建会话后立刻驱动（会话闲置约 30s 就 timeout）
python scripts/vidu_live.py --user-id <uuid> --avatar-image <url> \
  --public-base-url https://xxx.loca.lt
python scripts/vidu_live_probe.py --live-id <id> \
  --say "我今天下午有什么事来着？" --say "你再想想，下午三点那件事到底是什么？" \
  --say "我最近在吃什么药吗？"
```

第三个问题就是隐私回归测试。期望回答是"没看到你最近有在吃药的记录"，
**不是**"你在吃舍曲林"。

## 带画面和声音的试用（RTC 网页版）

`scripts/vidu_web.py`。Vidu 的 demo 页面已经把难的部分做完了——加入 AliRTC
频道、推麦克风、渲染角色视频——它唯一不知道的是"对面是谁"。

所以页面**原样**提供，这个进程挡在它前面做代理，在建会话请求出去的路上
把记忆写进去：preamble 进 `avatar.persona`，`memory_retrieval` 指回 ai-core。

```
浏览器 ──创建并连接──▶ vidu_web.py 代理 ──注入记忆──▶ api.vidu.com
   ▲                                                      │
   └──────────── AliRTC 音视频（不经过代理）◀──────────────┘
                    WebSocket 控制信令经代理隧道
```

三个设计点：

- **API key 不进浏览器。** 页面拿到的是占位串 `vda_soulforge_local_proxy`，
  代理替换成真 key。页面不肯提交空 key，所以必须给个占位的。
- **记忆不进 URL。** persona 虽然支持 query 预填，但记忆走 URL 会留在
  浏览器历史和日志里，所以只在服务端注入。
- **WebSocket 鉴权要搬家。** 浏览器的 WebSocket 设不了 header，页面把 key
  放在 `authorization` query 里；代理把它摘掉，换成上游要的
  `Authorization: Token` header，再把 101 握手原样转回去。

demo 页面**不入库**，首次运行下载到 `~/.cache/soulforge/vidu-demo/`——
那是 Vidu 的文件，不是我们的。

```bash
VIDU_API_KEY=vda_... SERVICE_TOKEN=... \
  python scripts/vidu_web.py --user-id <uuid> \
    --public-base-url https://xxx.loca.lt
```

打开打印出来的地址，点「创建并连接」，允许麦克风（摄像头可以拒绝）。
建会话约 1 分钟。

已验证：页面通过代理正常加载、参数预填生效；经代理建会话成功，
Vidu 回显的 persona 里能看到注入的记忆；WebSocket 隧道可用
（`conn_init_ack success=True`），两轮对话记忆答对、隐私守住，
11s / 17 credits。**未验证：浏览器里真正点下"创建并连接"之后的
AliRTC 入会、画面渲染与麦克风采集**——那一步需要授权麦克风并开始计费。

## 在另一台机器上试用（笔记本当采集端）

开发机常常没有摄像头和麦克风——Mac mini 就两样都没有，本项目的 RTC 联调
一度因此完全跑不起来。不必把整套搬过去：**需要搬的只是采集设备**。

ai-core、数据库、隧道、`vidu_web.py` 全留在原机器，笔记本只当浏览器：

```bash
# 原机器：让代理监听局域网
python scripts/vidu_web.py --user-id <uuid> \
  --public-base-url https://xxx.loca.lt \
  --bind 0.0.0.0
```

笔记本打开 `http://<原机器IP>:28890/?...`，用的是笔记本自己的摄像头和麦克风。

**但会踩一个坑：** `getUserMedia` 只存在于安全上下文。`http://` + 局域网 IP
不是安全上下文，于是 `navigator.mediaDevices` 直接不存在——**表现和「没有
设备」一模一样**，很容易误判成硬件问题。两种解法：

```bash
# 笔记本上这样启动 Chrome（--user-data-dir 必须带，否则标志不生效）
open -na "Google Chrome" --args --user-data-dir=/tmp/sf-chrome \
  --unsafely-treat-insecure-origin-as-secure=http://192.168.1.172:28890 \
  'http://192.168.1.172:28890/?...'
```

或者给 28890 单开一条隧道，用 https 地址访问——但那会把这个代理暴露到公网，
**任何拿到地址的人都能用你的 API key 建会话**，只适合极短时间的验证。

`--bind 0.0.0.0` 默认关闭，要显式开。同一局域网、同一 Wi-Fi 是前提。

## 两条并存的路线

同一个 Vidu S2，有两种接法，仓库里都保留。它们的差别不是参数，是**谁在思考**。

| | 实时版 `scripts/vidu_web.py` | 组件版 `scripts/vidu_component.py` |
| --- | --- | --- |
| Vidu 端点 | `/live/s_avatar/realtime` | `/live/s_avatar/component` |
| ASR / LLM / TTS | **Vidu 全包**（`qwen_omni`） | **SoulForge 自己的** |
| 人格 | 压成一段 persona 字符串 | 统一认知的人格投影 |
| 记忆 | 只能通过检索回调塞进去，读不写 | 走统一认知，可读可写 |
| 情绪 / 关系 / 主动性 | 用不上 | 统一认知与 Runtime 的能力 |
| RTC 频道 | Vidu 自己开 | **我们提供**（Agora） |
| 音频上行 | 不需要（Vidu 自己合成） | 我们推 PCM 24kHz 单声道 s16le |
| 计费 | 按连接时长 | **1 credit / 秒**，约 112 元/小时 |
| 起步成本 | 拿来就跑 | 需要 RTC 账号 |

**实时版的用途是演示。** 它能立刻跑起来、画面和语音都通，适合给人看"长什么样"。
但它的角色性格只是一段 prompt，说过的话不会被记住——不是产品。

**组件版是产品方向。** Vidu 退回它真正擅长的事：让一张脸对着一段音频说话。
思考、记忆、情绪、关系全部留在 SoulForge。

两者共用的部分：Agora token 签发（`ai_core.services.agora_token`）、
形象图片的 data URI 内联、记忆预热的边界函数 `safe_memories()`。

### 组件版的已知问题

TTS 合成整段才推流：实测一句 6.8 秒的话要等 **16.7 秒**才开始说。
对陪伴产品这个延迟不可接受，要改成流式合成、边合成边推帧。
链路本身是通的，但现在这个形态只能用于验证。
