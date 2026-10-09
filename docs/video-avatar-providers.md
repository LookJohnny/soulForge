# MiniMax H3 与 Vidu S2 接口实测

2026-09-18。两个候选视频供应商的实测记录。全部结论来自真实请求，
不是文档转述；每条都给出可复跑方式（`scripts/probe_video_providers.sh`）。

起因是型号容易认错：MiniMax 的 `M3` 是文本模型，`H3` 是视频模型，两者不同接口；
Vidu 的 `S2` 不在 `/ent/v2` 那套异步生成接口里，`viduq2` 不是 `S2`。

## MiniMax

账号 key 只在**国际站**有效。`api.minimax.io`、`api.minimaxi.chat` 通；
`api.minimax.com`、`api.minimax.chat` 返回 `invalid api key (2049)`。

### MiniMax-M3（文本）

`POST /v1/chat/completions`，OpenAI 兼容。实测单轮 1.9s。
`/v1/models` 列出 8 个文本模型：M3、M2.7、M2.7-highspeed、M2.5、
M2.5-highspeed、M2.1、M2.1-highspeed、M2。

注意：M3 把推理过程写在正文里，形如 `<think>...</think>\n\n正文`。
接 TTS 前必须剥掉，否则会念出推理过程。

### MiniMax-H3（视频，带原生音轨）

必须走 `/v2/video_generation`；用 `/v1/video_generation` 调它会被明确拒绝：
`this model must use the /v2/video_generation endpoint`。
`/v1/models` 不列视频模型，所以 H3 在模型列表里查不到。

```http
POST https://api.minimax.io/v2/video_generation
Authorization: Bearer $MINIMAX_API_KEY
Content-Type: application/json

{
  "model": "MiniMax-H3",
  "content": [{"type": "text", "text": "..."}],
  "duration": 4,
  "resolution": "480P",
  "ratio": "16:9"
}
```

接口自报的合法取值：

| 字段 | 取值 |
| --- | --- |
| `content[].type` | `text` / `image_url` / `video_url` / `audio_url` |
| `duration` | 4–15，逐秒 |
| `resolution` | `480P` / `768P` / `2K` |
| `ratio` | `16:9` `4:3` `1:1` `3:4` `9:16` `21:9`；纯文本输入时必填，且不能是 `adaptive` |

`content`、`duration`、`resolution` 三者都必填，缺一报 `missing required parameter`。

查询用 `GET /v2/query/video_generation?task_id=`，状态走
`running` → `succeeded`，成品在 `items[0].content.url`。
`/v1/query/video_generation` 也能查到同一任务，但返回的是旧字段格式。

**H3 直接出带声音的视频。** 实测 480P/4s 产物经 ffprobe 确认含两条流：
h264 1038×576 与 aac 32kHz。错误信息里把纯文本输入称作 `t2va`
（text-to-video-audio），与实测一致。
480P/4s 从提交到出片约 121s。

这点影响架构选型：H3 自带配音，和现有 TTS 链路是竞争关系而非补充关系，
用它就意味着这一段的音色不再由 `TTS_PROVIDER` 决定。

## Vidu

key 同样只在 `api.vidu.com`（Global）有效，`api.vidu.cn` 在本机连不通。
鉴权头是 `Authorization: Token vda_...`，不是 Bearer。

Vidu 有两套互不相通的接口，型号认错基本都出在这里：

### `/ent/v2/*` —— 异步生成，没有 S2

`text2video`、`img2video`、`reference2video`、`start-end2video`。
逐个枚举后，这套接口接受的模型是
`viduq1`、`viduq1-classic`、`vidu2.0`、`viduq2`、`viduq3`。
`s2`、`vidus2`、`vidu-s2`、`vidus2.0` 全部 `model is not supported`。

实测 `viduq2` 文生视频 4s/720p 成功，计费 30 credits。

### `/live/s_avatar/*` 与 `/ent/s_avatar/offline` —— S2 在这里

模型 id 是 `vidu-s2`（不是 `s2`，也不是 `vidu-s2.0`）。
`vidu-s1` 是默认值，稳定性更高但不支持 `prompt_operation`；
`vidu-s2` 文档标注为 beta。

四个版本：

| 版本 | 端点 | 支持的模型 | 说明 |
| --- | --- | --- | --- |
| Avatar 实时版 | `POST /live/s_avatar/realtime` | s1 / **s2** | Vidu 提供 ASR/LLM/TTS 全链路 |
| Avatar 组件版 | `POST /live/s_avatar/component` | s1 / **s2** | 自带 ASR/LLM/TTS，Vidu 只出数字人画面 |
| Avatar 离线版 | `POST /ent/s_avatar/offline` | **仅 s1** | 图 + 音频 → 视频，异步 |
| Editing | `/live/...` | — | 实时视频流编辑 |

离线版拒绝 S2 已单独验证过：同一请求体只换 model，
`vidu-s1` 返回 `task_id`，`vidu-s2` 返回 `model is not supported`。
（注意该端点先校验 text/audio 再校验 model，只传 image 时三种 model 都报
`text 与 audio 须至少传一个`，不能据此判断 model 是否受支持。）

实测 `vidu-s1` 离线版成功出片，计费 18 credits。

### 实时版实测

创建会话耗时 57s（含 avatar 预处理），返回 HTTP 200。响应顶层四个键：
`live`、`rtc`、`client_secret`、`recording`。

关键点：**RTC 频道由 Vidu 自己开**，实时版响应里直接给
`rtc.app_id` 和入会凭据，不需要自备 RTC。组件版相反，
必须在请求里传 `rtc_info`（`provider` / `app_id` / `channel_id` / `user_id` / `token`），
Vidu 加入你的频道。

`client_secret` 是 WebSocket 的短期签名令牌，有效期 24h。
控制信令与上行 PCM 音频、转写文本都走这条 WebSocket：
`GET /live/v1/external-lives/{live_id}/stream?conn_id=&client_secret=`。
会话查询 `GET /live/v1/lives/{live_id}`，单场上限 `live_duration` 7200s。

实时版内置的语音模型是 `qwen_omni`。

未连接 WebSocket 的会话会自行超时结束，`close_reason: timeout`，
`billed_seconds: 0`、`credits_cost: 0`——空跑不计费。

### 与现有记忆层重叠

实时版还带 `/live/v1/memories`、`/live/v1/knowledge-bases`、
`/live/v1/action-libraries`、`/live/v1/voices/clone`。
memories 与知识库和统一认知的记忆层职责重叠，
若走实时版需要明确哪一边是事实来源，否则会出现两套互相不知道的记忆。
组件版不涉及这个问题。

## 已验证与未验证

已验证：两个 key 的有效域名与鉴权头；M3 对话；H3 完整请求 schema、
合法取值、异步查询、产物含音轨；Vidu 两套接口各自接受的模型集合；
`viduq2` 与 `vidu-s1` 离线版真实出片与计费；`vidu-s2` 实时会话创建成功、
返回 RTC 凭据与 client_secret、空跑不计费。

未验证：H3 的 `image_url` / `video_url` / `audio_url` 输入；768P 与 2K 的耗时与计费；
S2 实时版的 WebSocket 全程（未接 PCM 上行，未看到实际画面）；
组件版接自有 RTC；Editing 版全部；两家的并发上限与实际单价。
