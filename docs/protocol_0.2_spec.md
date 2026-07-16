# SoulForge Character Runtime 协议规格（Protocol 0.2）

**版本**: `PROTOCOL_VERSION = "0.2"`
**状态**: 权威（Authoritative）——这是 Character Runtime 当前唯一有效的线协议
**格式**: JSON over WebSocket（文本帧）
**单一事实来源**: `engine/server/protocol.py` 中的数据类。本文档逐字段对照该文件编写；如有出入，以代码为准。

> 历史说明：`docs/protocol_spec.md` 描述的是早期 protobuf 玩具表演协议实验（`protocol/` 目录），未接入 Character Runtime，请勿据其接入。

**实现与参考客户端**:

| 角色 | 文件 |
|---|---|
| 服务端（大脑） | `engine/server/server.py`（`SoulForgeRuntimeServer`） |
| 消息定义 | `engine/server/protocol.py` |
| 能力协商 | `engine/server/capability.py`（`EmbodimentManifest`） |
| Python 身体示例 | `demo/runtime_server_demo.py` |
| Unity 身体客户端 | `unity/SoulForgeUnityClient/Assets/SoulForge/Scripts/SoulForgeProtocolClient.cs` |
| 语音身体（网关） | `packages/gateway/src/gateway/pipeline/character_bridge.py` |

---

## 1. 概述：一个大脑，多个身体

SoulForge Runtime Server 是唯一的决策者（"大脑"）。角色的身份、记忆、规划全部在服务端；**身体（body）不持有任何灵魂状态**。同一个角色（agent）可以同时活在多个身体里（Unity 场景、语音管道、机器人、浏览器），每个身体只声明并执行自己物理上能做的事。

服务端在单一端口上按 WebSocket 路径区分两类连接：

| 端点 | 谁连接 | 职责 |
|---|---|---|
| `/body` | 具身端（Unity、机器人桥、语音网关、Web） | 先发 `hello`（含 manifest）注册；之后接收 `action` / `plan_state` / `tick`，回发 `observation` 与 `event` |
| `/control` | HUD、调试 UI、测试工具（受信任） | 可发 `event`；接收**全部** agent 的 `plan_state` 广播；可发 `{"type":"query","what":"state"|"trace"}` 请求快照 |

路径不以 `/control` 开头的连接一律按 `/body` 处理。

### 1.1 帧格式

- 每帧是一个 JSON 对象，必须带 `type` 字段。
- 合法的 `type`: `hello`、`action`、`observation`、`event`、`plan_state`、`tick`、`welcome`。
- 解码时**容忍未知字段**（多余的 key 被丢弃），未知 `type` 视为错误。
- `/body` 连接上的畸形帧不会杀死连接：服务端记录 `wire_error` 日志后继续。

---

## 2. 连接握手

### 2.1 BodyHello（body → server，连接后第一帧）

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `body_id` | string | 必填 | 身体唯一 ID（如 `unity-apartment-1`、`rover-01`、`gateway-voice-xxxxxx`） |
| `backend` | string | 必填 | `"unity"` \| `"web"` \| `"robot"` \| `"mujoco"` \| `"voice"` \| ... |
| `agent_ids` | list[string] | 必填 | 该身体具身的规划器 agent 列表 |
| `manifest` | dict | `{}` | `EmbodimentManifest.to_dict()`（见第 3 节） |
| `protocol` | string | `"0.2"` | 协议版本 |
| `type` | string | `"hello"` | 固定 |

握手失败的关闭码：

- `4000 expected hello frame`——第一帧无法解码；
- `4001 first frame must be hello`——第一帧不是 `hello` 类型。

服务端会用 `hello.body_id` 与 `hello.backend` 覆盖 manifest 中的同名字段；`agent_ids` 中不在服务端角色表（personas）里的 agent 会被静默过滤。

### 2.2 Welcome（server → body，注册确认）

| 字段 | 类型 | 说明 |
|---|---|---|
| `body_id` | string | 回显 |
| `accepted_agents` | list[string] | 服务端实际接受的 agent 子集 |
| `supported_steps` | list[string] | 能力协商后该身体将收到的完整 micro-step 词汇表（已应用替换） |
| `protocol` | string | `"0.2"` |
| `type` | string | `"welcome"` |

Welcome 之后，服务端立即对每个 accepted agent 推送一帧当前 `plan_state`。

### 2.3 重连顶替

同一 `body_id` 的新连接**顶替**旧连接：服务端以 `4002 replaced by reconnect` 关闭旧 socket。旧连接的清理逻辑做身份检查，绝不会误删新连接的注册项。客户端断线后应带退避重连并重新发送 `hello`（参考 Unity 客户端的 backoff + re-hello + 按 `sequence` 去重）。

---

## 3. 能力协商（EmbodimentManifest）

来源：`engine/server/capability.py`。身体声明它物理上能做什么；服务端据此过滤或降级命令——规划器永远不会让轮式机器人"走路"、让无屏设备"画画"。

### 3.1 Manifest 字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `body_id` | string | `"anonymous"` | 身体 ID（握手时被 hello 覆盖） |
| `backend` | string | `"unknown"` | 后端类型（同上） |
| `supported_steps` | list[string] | `[]` | 支持的 micro-step 名 |
| `supported_templates` | list[string] | `[]` | 支持的活动模板 ID |
| `features` | dict[string, bool] | `{}` | 特性开关：`speech`、`gaze`、`nav`、`speech_only` 等 |
| `step_substitutions` | dict[string, string] | `{}` | 步骤替换表，如 `walk_to_kitchen -> nav.goto kitchen` |

### 3.2 协商规则（`accepts_step` / `accepts_template`）

1. **通用步骤**：所有身体免费获得 `idle_breathing`、`wait`、`look_around`、`resume_activity`、`pause_template`、`resume_template`、`stop_current_activity`、`abort_all_templates`、`report`（最小硬件上可实现为纯计时/no-op）。
2. **speech_only 身体**：若 `features.speech_only = true`，只接受显式列在 `supported_steps` 中的步骤（连通用步骤也不隐含）——网关语音身体只声明 `speak_line`。
3. **fail-closed（物理安全）**：`backend` 为 `"robot"` 或 `"hardware"` 的身体**永不获得隐式能力**——`supported_steps` 为空意味着"除通用步骤外什么都不能做"；`supported_templates` 为空时只接受 `idle` 模板。虚拟身体（unity/web 等）留空则视为"什么都能做"。
4. **接受模板 ⇒ 接受其恢复片段**：若某步骤是身体已声明模板（或未声明模板时任意注册模板）的 `recovery` 片段，该步骤自动被接受。这样失败恢复永远不会被能力门槛卡住。
5. **步骤替换**：`step_substitutions` 命中即接受；下发时服务端调用 `resolve_step` 用替换后的名字填充 `ActionCommand.name`。
6. **对话过滤**：`features.speech` 为 false 的身体（`wants_dialogue()` 返回 false）收到的命令 `dialogue` 字段会被置为 `null`。缺省视为 true。

不通过协商的命令**根本不会发给该身体**（"body never sees what it can't do"）。

---

## 4. 消息类型详解

方向标注：`S→B` = server→body，`B→S` = body→server，`C` = control 端可用。

### 4.1 ActionCommand（S→B，`type: "action"`）

协议 0.2 的**规范 Action IR**——新代码唯一可依赖的动作契约。具身适配器把它翻译为 Unity 动画、机器人 Intent/ActionUnit、Web 动画或 MuJoCo 控制；规划器从不下发电机角度。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `agent_id` | string | 必填 | 归属的角色 |
| `name` | string | 必填 | micro-step / 原语名：`stir_pan`、`look_at_user` ...（已按身体替换表 resolve） |
| `template_id` | string \| null | `null` | 所属活动模板 |
| `params` | dict | `{}` | 步骤参数 |
| `adapter_command` | dict | `{}` | 按 backend 的提示（如 `{"unity": ..., "robot": ...}`） |
| `dialogue` | string \| null | `null` | 台词（不支持 speech 的身体收到 null） |
| `gaze_target` | string \| null | `null` | 注视目标 |
| `duration_s` | float | `2.0` | 预期时长（秒） |
| `sim_minute` | float | `0.0` | 下发时的模拟分钟 |
| `command_id` | string | 自动生成（12 位 hex） | 回执关联键 |
| `protocol_version` | string | `"0.2"` | |
| `correlation_id` | string \| null | `null` | 把同一意图/规划节拍的多个步骤分组（网关用它把一次决策的台词归到一次用户发话） |
| `sequence` | int | `0` | **per-body 单调递增**，重连后去重用 |
| `target_body` | string \| null | `null` | 目标身体；null = 任何具身该 agent 的身体（服务端下发时填当前身体的 `body_id`） |
| `priority` | int | `50` | 10 = idle / 50 = plan / 90 = reactive |
| `issued_at` | float | `0.0` | 下发时的 sim_minute |
| `deadline` | float \| null | `null` | 超过此 sim_minute 后执行已无意义（服务端按 `duration_s` 与 time_scale 计算填入） |
| `ttl_s` | float | `30.0` | 墙钟有效窗口 |
| `interruptible` | bool | `true` | 可否打断——确定性字段，由执行器强制（服务端从模板取值） |
| `safety_class` | string | `"expressive"` | 见第 6 节 |
| `ack_policy` | string | `"on_complete"` | 取值见 `ACK_POLICIES`：`none` \| `on_start` \| `on_complete` \| `full` |
| `trace_context` | dict | `{}` | 链路追踪关联 |
| `type` | string | `"action"` | 固定 |

### 4.2 Observation（B→S，`type: "observation"`）

对某条已下发命令的执行回执。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `command_id` | string | 必填 | 对应 `ActionCommand.command_id` |
| `agent_id` | string | 必填 | 必须等于原命令的 `agent_id`（见回执语义） |
| `status` | string | 必填 | `accepted` \| `running` \| `done` \| `failed` \| `interrupted` \| `rejected`（`OBSERVATION_STATUSES`，构造时校验，非法值抛错） |
| `detail` | string | `""` | 人读细节，如 `"joint stall"` |
| `payload` | dict | `{}` | 附加数据 |
| `body_id` | string | `""` | 发送方身体 ID |
| `started_at` | float \| null | `null` | 开始的 sim_minute |
| `finished_at` | float \| null | `null` | 结束的 sim_minute |
| `error_code` | string \| null | `null` | 机器可读错误码：`E_STALL`、`E_TIMEOUT` ... |
| `sensor_snapshot` | dict | `{}` | 传感器快照 |
| `recoverable` | bool | `true` | 是否可恢复 |
| `type` | string | `"observation"` | 固定 |

**回执语义（防伪造）**：服务端按 `command_id` 在该连接自己的 `sent_commands` 中查找原命令；找不到则记 `observation_rejected`（unknown command_id）并丢弃。**命令的 agent 是权威**：若 `obs.agent_id != command.agent_id`，回执被拒绝（agent_id mismatch）且**不消耗**原命令——一个身体不能伪造跨 agent 回执去操纵另一个角色的恢复流程。

**生命周期**：`accepted` / `running` 是进度回执，**非终态**，命令保持 pending（语音身体可以先 `accepted` 收下台词、播放真正结束后再 `done`）。终态为 `done` / `failed` / `interrupted` / `rejected`，收到后命令从 pending 表移除。每个身体的 pending 表上限 256 条（超出时最旧的被丢弃——身体可能永不回执）。

**失败恢复**：`status = "failed"` 且原命令带 `template_id` 时，服务端查模板注册表，下发一条恢复命令：`name = template.recovery`，`params = {"recovering_from": <失败步骤名>}`，`duration_s = 2.0`，并在决策 trace 中记录 `plan_change`（level=recovery）。

### 4.3 Event / WireEvent（B→S，也可从 `/control` 发，`type: "event"`）

身体感知到的世界事件（镜像 `planner.models.Event`）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `kind` | string | 必填 | `user_utterance` \| `environment` \| `robot_state` \| ...（必须能转成规划器的 `EventKind`，未知 kind 记 `event_dropped` 后丢弃） |
| `source` | string | 必填 | 事件来源（如 `"user"`） |
| `text` | string | `""` | 文本内容（如用户发话） |
| `payload` | dict | `{}` | 附加数据（网关在此放 `event_id` 用作 correlation） |
| `target_agent` | string \| null | `null` | 定向到某个 agent；null = 广播 |
| `type` | string | `"event"` | 固定 |

事件进入一个有界队列（256），由独立 worker 在线程池中做 LLM 决策——慢 LLM 永远不会卡住 tick。队列满时事件被丢弃并记 `event_dropped`（backpressure）。

### 4.4 PlanState（S→B / S→C，`type: "plan_state"`）

规划快照，在决策/规划变化后推送，或响应 control 查询。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `agent_id` | string | 必填 | 所属 agent（`last_decision` 严格 per-agent） |
| `clock` | string | 必填 | 模拟时钟字符串 |
| `hour_goal` | string | 必填 | 当前小时目标 |
| `activities` | list[dict] | `[]` | 小时计划活动：`template_id` / `start_min` / `duration_min` / `params` / `interruptible` |
| `day_blocks` | list[dict] | `[]` | 日计划块：`start_min` / `end_min` / `activity_key` / `intent` |
| `last_decision` | dict | `{}` | 最近一次决策的详情 |
| `type` | string | `"plan_state"` | 固定 |

**按订阅定向广播**：身体只收到自己声明过的 agent 的 `plan_state`；`/control` 连接（受信任 UI）收到全部 agent 的。内容与上一帧完全相同时去重不发（对 HUD 是噪音）。

### 4.5 Tick（S→B / S→C，`type: "tick"`）

模拟时钟心跳，按 `tick_hz`（默认 1 Hz）广播给所有身体和 control 连接。

| 字段 | 类型 | 说明 |
|---|---|---|
| `sim_minute` | float | 当前模拟分钟 |
| `clock` | string | 时钟字符串（如 `"20:47"`） |
| `type` | string | `"tick"` |

### 4.6 control 查询（C→S，非 dataclass 帧）

`/control` 连接可发送：

```json
{"type": "query", "what": "state"}   // 回复：每个 agent 一帧 plan_state
{"type": "query", "what": "trace"}   // 回复：完整决策 trace 的 JSON dump
```

`what` 非 `"trace"` 的任何 query 都按 `"state"` 处理。

---

## 5. 时序语义汇总

1. **per-body sequence 单调**：服务端为每个身体维护 `next_sequence`（从 1 起），每下发一条命令递增。客户端按 agent 记录最近 sequence，`sequence != 0 && sequence <= last` 的帧丢弃——重连后服务端可能重发，靠这个去重（参考 Unity 客户端）。
2. **command_id 回执**：每条命令带唯一 `command_id`；回执必须回带。`accepted`/`running` 非终态，`done`/`failed`/`interrupted`/`rejected` 终态。
3. **重连顶替**：同 `body_id` 新连接踢掉旧连接（close 4002），旧连接的 teardown 有身份检查、不会误伤新注册。
4. **失败触发恢复**：`failed` + 有 `template_id` ⇒ 服务端下发模板声明的 recovery 片段（能力协商保证：接受模板即接受其 recovery）。
5. **tick 抗漂移**：tick 按绝对时钟调度，慢 tick 不会永久拖慢模拟日；单次 tick 异常被捕获记日志，不杀大脑。
6. **每身体最多 256 条 pending 命令**，防止从不回执的身体撑爆内存。

---

## 6. 安全类别（safety_class）

`SAFETY_CLASSES`（从最保守到最宽松）：`"safety_critical"`、`"physical"`、`"expressive"`、`"virtual"`。

当前服务端下发规则：目标身体 fail-closed（`backend` 为 `robot`/`hardware`）时 `safety_class = "physical"`，否则 `"expressive"`。语义约定：`physical` 命令会驱动真实执行机构，执行侧应施加硬件安全约束（限速、限力、可急停）；`expressive` 仅影响虚拟表现。`safety_critical` 与 `virtual` 为保留档位，0.2 服务端尚未主动下发。

---

## 7. 最小客户端示例

### 7.1 Python 身体（精简自 `demo/runtime_server_demo.py`）

```python
import asyncio
import websockets
from engine.server import (
    ActionCommand, BodyHello, EmbodimentManifest, Observation,
    WireEvent, decode, encode,
)

async def body():
    manifest = EmbodimentManifest(
        body_id="rover-01", backend="robot",
        supported_steps=["speak_line", "look_at_user", "water_plant"],
        supported_templates=["plant_care", "chatting", "rest", "idle"],
        features={"speech": True, "nav": True},
        step_substitutions={"walk_to_plants": "nav.goto plants"},
    )
    async with websockets.connect("ws://127.0.0.1:8765/body") as socket:
        # 1. 握手
        await socket.send(encode(BodyHello(
            body_id="rover-01", backend="robot",
            agent_ids=["kai"], manifest=manifest.to_dict())))
        welcome = decode(await socket.recv())
        print("negotiated steps:", welcome.supported_steps)

        # 2. 上报一个感知事件
        await socket.send(encode(WireEvent(
            kind="user_utterance", source="user",
            text="我今天有点累……", target_agent="kai")))

        # 3. 收命令、执行、回执
        async for raw in socket:
            frame = decode(raw)
            if isinstance(frame, ActionCommand):
                print("action:", frame.name, frame.dialogue)
                await socket.send(encode(Observation(
                    command_id=frame.command_id,
                    agent_id=frame.agent_id,
                    status="done", body_id="rover-01")))

asyncio.run(body())
```

非 Python 客户端直接收发同构 JSON 即可（参考 Unity 的 `JsonUtility` 用法和网关的裸 dict 帧）。

### 7.2 消息 JSON 示例

握手（body → server）：

```json
{
  "type": "hello",
  "protocol": "0.2",
  "body_id": "gateway-voice-a1b2c3",
  "backend": "voice",
  "agent_ids": ["luna"],
  "manifest": {
    "supported_steps": ["speak_line"],
    "supported_templates": [],
    "features": {"speech": true, "speech_only": true, "gaze": false, "nav": false}
  }
}
```

动作命令（server → body）：

```json
{
  "type": "action",
  "protocol_version": "0.2",
  "agent_id": "luna",
  "name": "speak_line",
  "template_id": "chatting",
  "params": {},
  "adapter_command": {},
  "dialogue": "今天辛苦啦，先坐下歇会儿吧。",
  "gaze_target": "user",
  "duration_s": 2.0,
  "sim_minute": 1247.0,
  "command_id": "9f2c01ab34de",
  "correlation_id": "6d1e22c0aa17",
  "sequence": 42,
  "target_body": "gateway-voice-a1b2c3",
  "priority": 90,
  "issued_at": 1247.0,
  "deadline": 1249.2,
  "ttl_s": 30.0,
  "interruptible": true,
  "safety_class": "expressive",
  "ack_policy": "on_complete",
  "trace_context": {}
}
```

回执（body → server）：

```json
{
  "type": "observation",
  "command_id": "9f2c01ab34de",
  "agent_id": "luna",
  "status": "done",
  "detail": "",
  "body_id": "gateway-voice-a1b2c3"
}
```

---

## 8. 版本与兼容性

- 当前版本 `PROTOCOL_VERSION = "0.2"`，随 `BodyHello.protocol` / `Welcome.protocol` / `ActionCommand.protocol_version` 传递。
- **向后兼容**：所有 0.2 新增字段（canonical IR envelope：`correlation_id`、`sequence`、`target_body`、`priority`、`issued_at`、`deadline`、`ttl_s`、`interruptible`、`safety_class`、`ack_policy`、`trace_context`，以及 Observation 的 `body_id`、`started_at`、`finished_at`、`error_code`、`sensor_snapshot`、`recoverable`）都有合理默认值，0.1 的对端可继续解码。
- **向前兼容**：解码器丢弃未知字段——新增字段不破坏旧客户端；未知 `type` 会被拒绝。
- v0 刻意选 JSON 而非 protobuf：浏览器、C# 客户端和 Python 机器人桥零代码生成即可互通。protobuf 可在 v1 镜像这些数据类。
