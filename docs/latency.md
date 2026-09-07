# 延迟指标的采样边界

本地主线有两个独立的 `/metrics/latency`：

| 地址（默认端口） | 采集内容 |
| --- | --- |
| Gateway `:8081/metrics/latency` | 设备语音轮次、统一 Runtime 决策与首音频、首帧发送 |
| AI Core `:8100/metrics/latency` | 原有 `/pipeline/chat`、`/pipeline/chat/stream` 的内部阶段 |

两个接口不互相汇总。统一认知调用 `/cognition/decide`，不会因此产生旧 pipeline 的阶段样本。Gateway 的外部 OpenAI 兼容接口只向视频平台交付文本，也不会产生本地设备语音轮次；平台何时合成或播放音频不在 Gateway 可观测范围内。

Gateway 只有在设备响应路径调用 `_record_voice_turn()` 后才增加样本。尚未记录语音轮次时返回 `{}`，表示没有样本。不能由此推断延迟为零，或推断模型调用没有成功。

## 字段与起点

设备语音轮次通常位于响应的 `voice_turn.stages_ms`。每阶段提供 `avg`、`p50`、`p95`、`p99`、`max`、`count` 和 `missing_count`；`last_turn` 只包含最后一次实际测到的阶段。

| 阶段 | 起点 → 终点 |
| --- | --- |
| `decision_ms` | Gateway 开始处理识别后的文本 → 收到完整、已验证的 Runtime 决策；包括身份解析、传输与调度等待 |
| `first_audio_ms` | 同上 → 首句 TTS 返回编码音频；包括决策与首句合成时间 |
| `first_chunk` | VAD 判定用户停止说话（无此时间则使用处理起点）→ 第一个流事件；该事件可能是情绪或文本 |
| `first_word` | 同一 VAD/处理起点 → Gateway 开始向设备发送回复的首个音频帧 |
| `respond` | 同一 VAD/处理起点 → 响应发送阶段结束；不含随后等待设备缓冲播放完毕的时间 |

`decision_ms`、`first_audio_ms` 同时保留原先的 `core_decision_ms`、`core_first_audio_ms` 字段，兼容设备 recorder 统一添加 `core_` 的行为。这两项来自统一 Runtime 路径的 `done.stages`，不是 AI Core 单独记录的纯模型推理时间。

`first_audio_ms` 表示音频可用，`first_word` 表示设备发送边界。两者起点不同，也都不是用户实际听到声音或视频嘴型同步的测量。思考填充音不计入回复首帧。

## 缺失、失败与统计

- `0` 是合法的已测值，例如低于时钟精度的测试操作；它保留在统计中。
- `None`、非数值、布尔值、非有限值和负值不作为延迟样本。
- 一个阶段从未测得时，该阶段不存在；有部分样本时，`count` 统计有效测量，`missing_count` 是同一路由窗口内未测到该阶段的轮次数。
- TTS 返回失败结果而语音路径继续结束时，决策延迟仍可计数，首音频和首帧缺失。提前抛异常或中断、未走到 recorder 的请求可能没有轮次样本，不能用 `missing_count` 代替完整错误率。
- 窗口按路由保留最近 500 个已记录轮次，只在当前进程内；重启清空。不同阶段的分位数可能基于不同数量的有效样本。

## 离线证据

`packages/gateway/tests/test_unified_latency_pipeline.py` 使用真实 `process_text_stream`、设备响应函数、`PlaybackChannel` 和 HTTP 指标路由，替换 Runtime/TTS、时钟及设备传输。受控时钟分别产生 120 ms 决策、200 ms 首音频、280 ms 首帧发送，验证这些值通过 `done.stages` 到达 Gateway 指标接口；第二轮 TTS 失败不生成音频或零延迟样本。

```bash
.venv/bin/python -m pytest packages/gateway/tests/test_latency.py packages/gateway/tests/test_unified_latency_pipeline.py -q
```

这些数值用于证明计时与聚合机制，不能作为 live 性能基准。真实语音延迟、外部视频首音频及嘴型同步仍需各自在相应边界测量。
