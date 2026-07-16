# SoulForge · 30 秒晚间陪伴 Demo（引擎驱动版）

> **融资版（v3）**：`outputs/webgl/dinner_pitch_final.mp4` — 1920×1080@24、品牌开场/收尾卡、
> 中英双语字幕、每镜头缓动推移、电影调色+颗粒+暗角、Kevin MacLeod《Wholesome》(CC BY 4.0) 音乐垫底。
> 重新生成：先跑下方步骤 1-2（`--width 1920 --height 1080`，帧目录 `dinner_pitch_frames`），
> 然后 `bash demo/finalize_pitch_video.sh` 一键完成调色/配音/音乐/交付物。

一段 30 秒、1280×720、24fps、带三音色配音与字幕的产品样片：
晚上 20:47，三个角色在公寓里收尾一天——**Kai**（男性，做饭）、**Luna**（女性 VTuber，画画）、**Pipo**（非人形照护机器人，植物巡检）。
中段用户说"我今天有点累……"，规划引擎判定 HIGH impact，现场把本小时计划重写为陪伴模式（画面右上角计划面板可见 REWRITTEN），植物传感器事件则走 LOW impact 微插入。

## 最终产物

- `outputs/webgl/dinner_final.mp4` — 最终带音频+字幕视频
- `outputs/webgl/dinner_final_contact_sheet.jpg` — 关键帧 contact sheet
- `assets/vtubers/vroid_samples/asset_manifest.json` — 模型/音频素材来源与 license

## 管线（重新生成步骤）

```bash
# 1. 规划引擎生成 30s 事件时间线（台词/beat/镜头/重规划决策）
uv run python demo/generate_dinner_timeline.py
#    -> demo/vtuber_life_web/dinner_timeline.json (渲染层消费)
#    -> demo/vtuber_life_web/dinner_voice_events.json (TTS 消费)

# 2. 无头渲染 30s @ 24fps 720p
node demo/record_vtuber_life_web.mjs --page dinner.html \
  --duration-minutes 0.5 --fps 24 \
  --out outputs/webgl/dinner_final_video.mp4 \
  --frames-dir outputs/webgl/dinner_final_frames

# 3. 三音色 TTS + 混音 + 字幕 + 混流
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/webgl/dinner_final_video.mp4 \
  --out outputs/webgl/dinner_final.mp4 \
  --events-json demo/vtuber_life_web/dinner_voice_events.json \
  --mode edge --duration 30

# 4. contact sheet
ffmpeg -y -i outputs/webgl/dinner_final.mp4 -vf "select='not(mod(n,72))',scale=426:240,tile=5x2" \
  -frames:v 1 outputs/webgl/dinner_final_contact_sheet.jpg
```

## 本次改动的文件

新增：
- `engine/planner/` — 三层规划引擎（day/hour/minute + 模板 + event_queue 重规划 + LLM 接口 + runtime loop）
- `tests/test_planner.py`、`tests/conftest.py` — 验收测试（8 项）
- `demo/generate_dinner_timeline.py` — 引擎 → demo 时间线导出
- `demo/vtuber_life_web/dinner.html` + `src/dinner.js` — 新渲染场景（VRoid 模型、注视/轮流说话、事件 HUD）
- `assets/vtubers/vroid_samples/` — 高质量模型（AvatarSample_B/C、RobotExpressive、Shibu 备用）

修改：
- `demo/record_vtuber_life_web.mjs` — 增加 `--page` 参数
- `demo/synthesize_vtuber_voice_track.mjs` — 角色改为 Luna/Kai/Pipo 三音色，机器人后期从重电子改为轻电子

## 角色 / 声音

| 角色 | 模型 | 定位 | 声音 |
| --- | --- | --- | --- |
| Luna | VRoid AvatarSample_B | 创作陪伴（画画/情绪关怀） | zh-CN-Xiaoxiao，自然温柔 |
| Kai | VRoid AvatarSample_C | 生活照料（做饭/计划） | zh-CN-Yunxi，自然对话感，降 4% 音高 |
| Pipo | three.js RobotExpressive | 环境照护（植物/传感器） | zh-CN-Yunxia 少年音 + 轻电子（flanger+bitcrush） |

## 互动结构（30s）

1. 0-8s：三人各自活动（做饭/画画/扫描），Kai 主动问 Luna 口味，Luna 抬头回应
2. 8.2s：🎤 用户事件"我今天有点累……" → 引擎 HIGH → 重写 20:47-21:30 为陪伴模式（HUD 面板闪烁 REWRITTEN）
3. 9-16s：Luna 转向用户回应，Kai 附和并调整计划
4. 16.4s：🌱 植物湿度事件 → 引擎 LOW → 不打断，插入提醒 + 更新明日计划
5. 17-24s：Pipo 转身汇报，Kai 接话分工，Kai/Pipo 走向客厅中心
6. 24-30s：Luna 感谢收尾（"像这个家在自己运转"），Pipo 挥手，镜头拉远

## 动作系统（v2 精细化）

- 眼球注视：`vrm.lookAt.target` 跟踪平滑后的注视点，眼睛先于头部转向
- 身体/注视时间平滑：转向 ~0.3s 缓动，beat 切换不再瞬跳
- 手指：四指三节自然弯曲（左手 +Z / 右手 -Z），做饭/画画时握持加深
- 做饭分相位：翻炒 ~3s → 提铲查看 ~1.4s 循环，锅铲道具同步
- 倾听反应：对方开口 0.6s 内的认同点头（指数衰减）
- 机器人：Idle/Walking/Yes（说话点头）/ThumbsUp（接受分工）/Wave（收尾）+ 头部注视

## 已知质量缺口（后续可再提升）

- 道具（锅铲/画板）是"跟随"而非真正 IK 抓握，手与道具偶有间隙
- 场景家具是程序化 RoundedBox 风格化资产，接近休闲游戏质感，但不是商业级建模场景
- 口型是振荡近似（'aa' blendshape），未做音素对齐
- 机器人行走用 RobotExpressive 自带 Walking clip，转身时脚底有轻微滑步
