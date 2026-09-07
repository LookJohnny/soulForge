# SoulForge MediaBody

自建 WebRTC 视频身体，继续使用 Gateway → Runtime → ai-core 的统一认知与身份。
浏览器入口是 `http://127.0.0.1:8899/joi?body=selfhost`。

## 启动

```bash
scripts/selfhost-up.sh --install
# 根 .env: SELFHOST_MEDIA_TOKEN 随机密钥；AVATAR_WORKER_URL/TOKEN 指向真实 worker。
scripts/selfhost-up.sh
# 或根 .env 设置 SELFHOST_MEDIA_ENABLED=true 后让 scripts/live-up.sh 统一管理。
scripts/selfhost-up.sh --status
```

Python 3.12 / aiortc / PyAV 在本包 `.venv` 中运行，不改主服务依赖。
源码和依赖清单在本仓库；GPU 独立包见 `../avatar-worker/`。
根 `.env` 按数据读取，覆盖旧 shell 配置；浏览器只通过 Studio 同源白名单代理。
GPU 远程访问使用 HTTPS 或 SSH 的本地端口转发。

## 协议

所有控制与完整健康查询需要 `Authorization: Bearer SELFHOST_MEDIA_TOKEN`。
唯一不带认证的 `/livez` 只返回进程存活，不能据此断言模型或 GPU 可用。

- `GET /health`：GPU 加载状态、脑接口配置状态及其验证范围，始终保留 `end_to_end_verified:false`。
- `POST /sessions`：`{client_id:UUID,sdp,type:"offer"}`，返回本地 WebRTC answer 和 session_id。
  相同 owner 与 SDP 重试返回同一会话；首版最多一个会话。
- `POST /sessions/{id}/turn`：`{client_id,text}`，创建一次认知轮。
- `POST /sessions/{id}/interrupt`：`{client_id}`，返回确切 epoch；数据通道的同 epoch cancelled 才是对应确认。
- `POST /sessions/{id}/close` 与 `POST /sessions/close-owned`：显式回收，包括创建响应丢失的情况。
- 有序 `events` DataChannel：每条包含 session_id、epoch；传输状态、字幕和计时，不传服务器密钥。

麦克风经 WebRTC → 16k 单声道 PCM → 能量 VAD（含开口前缓存）→ Gateway ASR-only。
回复只调用一次统一认知；逐句 MP3 解码成同一份 PCM，视频推理与音频播放共用该 PCM。
模型返回的 JPEG 与音频必须严格 25fps / 每帧 640 个采样匹配，否则整轮失败。
声音只在对应视频帧到达后发送；队列有界；模型补齐的静音尾部不播放。

取消立刻使服务端旧 epoch 无效并清队列，远程清理独立执行，确认前新轮不能调用脑。
GPU 旧内核可以继续运行，返回结果会被丢弃；忙碌时先等待，不重复调用脑。
创建后 30 秒未接通、断开 10 秒或 15 分钟上限会回收会话。

## 验证与边界

```bash
PYTHONPATH=packages/media-body/src packages/media-body/.venv/bin/python -m pytest -c packages/media-body/pyproject.toml packages/media-body/tests
```

测试使用明确隔离的假脑/GPU输入，WebRTC 两端、编解码和音画传输是真实的。
正常服务没有假模型回退；GPU 不可用时禁止创建会话。

当前不是已验收的真人交互：

- 没有运行 NVIDIA 实际推理或测量电影观感；角色参考图尚未就绪。
- 逐句完整音频后再渲染；不是 LLM/TTS 输入端到端流式。
- FlashHead 是音频驱动近景脸，不支持语义眼神、手势或全身动作控制。
- 跨渲染请求重置视觉状态；闲置保持最后一帧，尚无自然倾听动画。
- 能量 VAD 是首轮基线，嘈杂环境/回声与中文句尾须实测。
- 清服务端队列不等于清浏览器 RTP 缓冲；真正停嘴、停声和恢复倾听仍须实测。
- 计时区分音频准备、视频准备、发送队列完成。没有浏览器实际播放回执，向 Runtime 保守提交 played=false。
- 当前浏览器与媒体服务按同机部署设计，没有公网 ICE/TURN 配置。

真实 GPU 启动、首轮录制与完整验收见 `../../docs/self-hosted-joi-implementation.md`。
