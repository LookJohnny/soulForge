# SoulForge 架构 —— 一个大脑、多个身体（2026-07-10 Character Runtime 重构）

SoulForge 是跨载体 Character Runtime：同一个角色（人格/记忆/关系/情绪/计划）可以驱动
实体机器人、Unity 游戏角色、Web/VTuber、MuJoCo 等不同身体。SoulForge 只负责上层角色
智能与具身行为决策——不替代游戏引擎，LLM 永远不进电机实时控制链路。

## 三层架构

```
┌─ 1. Character Core（engine/planner/）────────────────────────────────────┐
│ Identity/Persona        configs/characters.json + characters.py（单一来源）│
│ Memory / Relationship   memory_store.py：MemoryStore 协议，agent_id 主键， │
│                         与 body 解耦；InMemory（测试）/ AICoreMemoryStore  │
│                         （五层 PROFILE/EPISODIC/SEMANTIC/RELATIONAL/       │
│                          COMPILED，HTTP 适配既有 ai-core 服务，非第三套实现）│
│ Clock / World / Event   clock.py（Wall/Simulation/Game 时钟；总分钟单调，   │
│                         日界取模）；models.py WorldState/Event              │
│ Planner / Replanner     day(按日重生成) → hour(按 DayBlock 边界切分，支持   │
│                         22:30 等非整点) → minute(模板 micro-step)；        │
│                         四级重规划 + 确定性中断执法（不可中断活动延后到     │
│                         安全断点；CRITICAL 走 hold→safe_stop→abort 序列）  │
│ LLM 接口                SafeDecisionLLM：线程池+硬超时+严格结构校验+mock    │
│                         fallback；事件永不丢失；tick 永不被 LLM 阻塞       │
│ Behavior Template       9 模板（clips/servo/unity/mujoco 绑定+可中断性+恢复）│
│ Trace / Replay          环形 trace + 单调 seq；决策全程可解释               │
└──────────────────────────────────────────────────────────────────────────┘
                                   │  canonical Action IR / Observation
┌─ 1.5 Multimodal Perception（engine/perception/，Phase 6）────────────────┐
│ models.py   PerceptionEvent/Visual/Auditory/Entity/SpatialRelation/       │
│             SceneState；privacy_class；hazard 标签表                       │
│ sources.py  CameraSource/MicrophoneSource 协议；File/Recorded fixtures；   │
│             MuJoCoStateSource（仿真态直读，不截图猜）；真机只有 HAL 契约   │
│ vision.py   图像校验/采样变化检测/VisionGate（默认至少 1s 节流）；Mock、  │
│             可注入本地 detector、RemoteVLM(HTTP+严格 JSON schema)；provider│
│             在可终止子进程内运行，超时不遗留线程                           │
│ audio.py    格式归一化/VAD/ASR/声音事件契约（真实链路复用 gateway 既有     │
│             Opus+Silero+DashScope，不重造）；SelfVoiceFilter 回声过滤；    │
│             BargeInController（停 TTS→安全暂停→重新决策，确定性）          │
│ fusion.py   时间窗融合/实体追踪/说话人归属/去抖/置信度阈值/deixis 落地      │
│             （“那个”→pointing_at 实体 entity_id）                          │
│ runtime.py  生命周期/有界 FIFO/drain/过期丢弃/指标；hazard 多帧确认证据； │
│ sink.py     有界异步 WS sink：PerceptionRuntime → Runtime /control       │
│ 安全边界：OCR/标签永不当指令；视觉 CRITICAL 必须多帧确认并经部署 HMAC     │
│ 签名，Runtime 再验签并改走固定 safe-stop；记忆递归消毒、限深和限总大小    │
└──────────────────────────────────────────────────────────────────────────┘
                                   │  PerceptionEvent → WireEvent
┌─ 2. Embodiment Protocol（engine/server/，protocol 0.2，JSON-WS）─────────┐
│ ActionCommand：command_id/correlation_id/sequence/agent_id/target_body/  │
│   template_id/step/params/priority/issued_at/deadline/ttl_s/             │
│   interruptible/safety_class/expected duration/ack_policy/trace_context  │
│ Observation：accepted/running/done/failed/interrupted/rejected +         │
│   body_id/started_at/finished_at/error_code/sensor_snapshot/recoverable  │
│ Hello+Manifest 能力协商（步骤替换；robot/hardware 后端 FAIL CLOSED）       │
│ 重连：同 body_id 顶替旧连接且互不误删；sequence 供去重                     │
│ 回执防伪：以服务器记录的 command.agent_id 为准                            │
│ plan_state 按订阅 agent 定向；last_decision 按 agent 隔离                 │
│ 畸形帧/未知类型/[]/null 不断连；tick 绝对时钟防漂移；参数校验拒绝 0/负/NaN │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
┌─ 3. Embodiment Runtimes ─────────────────────────────────────────────────┐
│ Robot（engine/embodiment/）  RobotEmbodimentAdapter: IR→submit_intent→    │
│   Dispatcher→PhysicalExecutor→SafetyManager→Backend；watchdog/故障锁存/   │
│   人工复位/安全姿态；传感器读数实接 SafetyManager；FaultInjectionBackend  │
│   （堵转/过温/低电量/通信丢失/非法关节）；hal.py 定义真机 HAL 契约        │
│   （CAN/串口/PWM 驱动只有接口，无伪造实现）                               │
│ Unity（unity/.../SoulForgeProtocolClient.cs + ProtocolMessages.cs）       │
│   /body 接入、hello/manifest、主线程执行、Observation 回报、断线重连+     │
│   sequence 去重；桥接既有 Bridge/AgentController/动画/对话 HUD            │
│ Web（demo/vtuber_life_web）  three.js+VRM 渲染；离线消费引擎时间线，       │
│   实时订阅待迁移                                                          │
│ MuJoCo  engine/mujoco_backend.py 作为 ExecutionBackend 可挂入 Robot 适配器 │
└──────────────────────────────────────────────────────────────────────────┘
```

## 关键数据流

行为：`Persona/店memory → day_plan → hour_plan → minute_action → ActionCommand(IR)
→ (能力过滤+sequence) → 身体 → Observation → 失败恢复/重规划`

事件：`身体/控制端 Event → server 事件队列（独立 worker，线程池跑 LLM，超时 fallback）
→ 确定性中断执法 → PlanDelta → plan_state 定向广播`

感知语音：`Camera/Mic → PerceptionRuntime → RuntimePerceptionSink → WireEvent
→ Character Runtime → ActionCommand(speak_line) → 持久在线 voice body → TTS
→ 设备播放等待 → done/interrupted Observation`。`accepted` 只是接单，绝不等于播放完成。

记忆：`agent_id → MemoryStore（关系/五层记忆）；换身体重建 runtime 时自动补水
（Unity 里聊出的关系，机器人身体里直接可读——tests/test_memory_store.py 验证）`

## 成熟度（诚实评估）

| 能力 | 状态 |
| --- | --- |
| Character Core（规划/重规划/中断执法/时钟/48h 连续模拟） | **demo-ready**（全仓 194 项测试含 48h/午夜/边界回归） |
| Protocol 0.2 + Runtime Server（协商/重连/防伪/隔离） | **demo-ready**（模拟身体端到端） |
| Robot 桥（RecordingBackend/故障注入/watchdog/锁存复位） | **prototype-ready**（仿真后端验证；未接真机） |
| 真机 HAL（CAN/串口/PWM） | **仅接口定义**，无驱动实现，未验证 |
| Unity Protocol/Perception 客户端 | C# 批处理编译通过；Reporter 有 `.meta` 且默认关闭；仍需目标项目场景挂载联调 |
| Web 感知上报 | **demo-ready**：显式 opt-in、失败全资源清理、只发 VAD/RMS；浏览器 ASR 未接 |
| Web 角色实时渲染订阅 | 未实现（现为离线时间线消费） |
| AICoreMemoryStore | **prototype**（需运行 ai-core 服务；未联测） |
| MuJoCo | Backend 可挂接，未做专项验证 |
| Audio capture（Opus/VAD/流式ASR，gateway 既有栈） | **ready**（xiaozhi 线上跑过）；与 Character Runtime 的单一决策桥 **demo-ready**（离线测试） |
| ASR | **ready**（DashScope 流式，gateway 既有）；Mock 供离线 |
| Vision fixture 链路（文件→事件→决策） | **ready**（离线测试+demo） |
| 真实摄像头 | **unverified**（仅 HAL 契约，无驱动） |
| VLM provider | Mock/Local callable **ready**；Remote HTTP/JSON adapter 已测试；真实服务凭据联调 **unverified** |
| 多模态融合（时间窗/追踪/deixis/说话人） | **ready**（离线测试） |
| 动作+TTS 闭环（correlation/两阶段 ACK） | **demo-ready**：真实 WS + TTS stub + 播放终态 ACK 已测；真实扬声器未联跑 |
| 真机机器人感知 | **unverified** |

任何"production-ready"结论都需要：真机台架验证、Unity 编译+场景联调、ai-core 联测。

## 可复现命令

```bash
uv run pytest -q                                   # 194 passed；Gateway 重依赖专项另有 1 skip
PYTHONPATH=.:packages/gateway/src uv run --isolated --package gateway \
  --with pytest --with pytest-asyncio python -m pytest -q \
  tests/test_gateway_playback_server.py            # 真实 Gateway 依赖环境：3 passed
uv run python demo/planner_acceptance_demo.py      # 规划/重规划验收（--interactive 可实时打断）
uv run python demo/runtime_server_demo.py          # 端到端：注册→动作流→打断→失败恢复
uv run python -m engine.server.server --port 8765  # 常驻服务（Unity/机器人接这里）
```

生产环境必须在感知 producer 与 Character Runtime 同时设置至少 24 字节的
`SOULFORGE_PERCEPTION_ATTESTATION_KEY`；未配置、签名被篡改或确认次数不足时，视觉危险
声明会 fail-closed，不能进入 CRITICAL。

Gateway 数据库中的 `character_id` 通常是 UUID，而 Runtime 使用 `kai` 这类 agent id。
生产环境应设置 `CHARACTER_RUNTIME_VOICE_DEVICE_ID`，把感知触发的主动台词明确绑定到一个
实际播放设备；未绑定时只在 session character_id 与 Runtime agent id 相同的开发配置下启用。

## 与 ai-core 的边界（有意的两套，不是待合并的债）

| 关注点 | engine 侧 | ai-core 侧 | 边界规则 |
|---|---|---|---|
| LLM 调用 | `planner/llm_interface.py`：同步单发行为决策，stdlib urllib，失败落 mock | `services/llm/`：异步流式对话栈（多 provider/重试/SSE） | 引擎保持零三方依赖可嵌入；要 provider/重试/流式，去 ai-core，经 HTTP 调用（照 `AICoreMemoryStore` 模式） |
| 记忆 | `planner/memory_store.py`：协议 + InMemory + HTTP 瘦适配 | `services/memory.py`：五层记忆真实现 | 已按适配器模式处理，engine 侧明示 "NOT a third implementation" |
| 人格 | `configs/characters.json`（agent 名如 kai/luna，运行时/Studio/demo 用） | Postgres characters 表（UUID，admin-web 管理，商用管线用） | 网关用 `CHARACTER_RUNTIME_AGENT` 把设备的 DB 角色映射到运行时 agent。**统一方向未定**：待第一个真实商用 body（Joy 迁移）落地时，决定 provisioning 流向（DB→json 还是 json→DB），在那之前不要盲目双写 |
