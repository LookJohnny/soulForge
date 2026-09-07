# Joi 真人视频测试入口

2026-09-07。用户选择“真人视频脸与自然对话，接近电影观感”。

打开 `http://127.0.0.1:8899/joi`。原三维页面保留在 `/joi?body=vrm`。
新页面接收真实 WebRTC 视频与音频；待机页没有静态人像、预制视频或替代语音。

## 连接方式

浏览器 Daily SDK → 已配置 Tavus PAL（现有 Luna 脸）→ 公网 relay →
Gateway `/v1/chat/completions` → Runtime → AI Core `/cognition/decide`。
原有人格、用户身份与持久记忆继续由统一认知负责。
真人页不启动 `GatewayClient`、`BodyClient` 或第二条麦克风采集。

按“接通”先申请麦克风，成功后才创建 Tavus 会话。摄像头始终关闭。
会话使用已有 PAL，不创建角色、不覆盖脸或声音、不自动录音。
本轮上限 300 秒；无人加入上限 120 秒；离开后 10 秒结束。
实际费用由现有 Tavus 账户规则决定。

Studio 的创建/结束接口仅接受本机同源浏览器；GET 状态不返回入会令牌。
入会使用私有房间的 meeting token，Tavus API key 与 Gateway token 留在服务端。
每个页面具有独立 client_id，别的页面不能复用令牌或挂断其会话。
挂断、连接失败、页面离开都会请求结束；失败显式显示等待回收。
服务端私有 journal 记录其自己创建的会话属主，重启后只回收这些会话。
未知创建结果依据随机名称与 PAL 核对，不盲目重发创建请求。

PAL 预检核对默认脸、模型、大脑 URL、关闭 speculative inference。
供应商将 API key 回读为固定 `********` 时，标记 `provider_redacted`；
这不是密钥读回校验通过。现有启动流程负责 PATCH 同步，Gateway 仍验证真实 bearer。

## 本次人格修正

- Joi 的数值人格与背景校准为克制、口语、允许留白，减少惯性反问和固定安慰词。
- 明确记忆有原话依据时直接回应；未知内容不拿角色背景补成用户事实。
- 三个 prompt 模板区分角色兴趣与用户兴趣，修复角色爱好被冒充为用户偏好的问题。
- Joi 坦诚自身 AI 身份，保持记忆使用权限与隐私边界。

## 已验证与未验证

已验证：本地会话生命周期、所有权、鉴权、供应商掩码兼容；浏览器页面实际加载，
视频 SDK 可加载且接通按钮可用。只读核对现有 PAL、默认脸和接线；旧会话已经结束。

未验证：本次修改后的实际真人视频通话、自然中文声音、嘴型同步、真实抢话、人格效果。
自动审批拒绝了创建 Tavus 测试会话，因此没有执行该 POST，也没有计入真实模型验收。
用户可以自行按接通，或明确授权一次有时限的代测。

“等一下”发送官方 `conversation.interrupt`，等待供应商停止事件；
发送成功不会被当作嘴和声音已停止。音频/视频轨到达也不是用户已听见的证明。
字幕优先使用累积 utterance streaming 快照，去除 PAL/replica 重复及过期轮次。
连接详情中的轮次间隔来自 provider speaking 时间戳，并非浏览器首音频延迟。

以下仍是下一阶段工作，不包含在这次前端接入的完成声明里：

- Gateway 等整次 Runtime 决策完成后才发送 SSE，仍不是 token 级端到端流式。
- Tavus 的面部表演由供应商生成，未将 Runtime 动作意图转换成可控全身表演。
- Tavus 打断尚未映射成 Runtime 推理取消或实际播放回执；外部文本交付继续标记 playback unverified。
- Tavus 的视觉/情绪系统上下文尚未接入中央认知；当前页面也没有开启用户摄像头。
- 现有 Luna 库存脸不等于电影演员或为 Joi 定制的授权形象。

## 人工验收

接通后，等简短问候结束再开始（Tavus 官方说明问候不能被打断）。

1. 说一句新近的普通事实，检查真人视频连续说话，中文自然，嘴型与声音一致。
2. 在一次较长回复中插话，再试“等一下”，确认声音和嘴都停止，没有旧句尾继续播放。
3. 紧接上一轮追问，检查依据真实上下文接续，而非另起话题或机械追问。
4. 挂断，确认麦克风关闭；再次接通继续上下文；状态接口最终回到 idle。

通过这四项后，再评估定制真人资产、语音选角和流式认知的收益。

接口依据：[Tavus 会话](https://docs.tavus.io/api-reference/conversations/create-conversation)、
[打断](https://docs.tavus.io/sections/event-schemas/conversation-interrupt)、
[说话事件](https://docs.tavus.io/sections/event-schemas/conversation-started-stopped-speaking)、
[Daily 自定义视频](https://docs.daily.co/reference/daily-js/factory-methods/create-call-object)。
