# SoulForge 真实 VRM 生活 Demo 调试手册

这个 demo 现在分成两条线：

1. `demo/vtuber_life_web/`：真实 VRM 本体渲染。使用 Three.js + `@pixiv/three-vrm` 加载 `.vrm`，画面质感和角色差异以这条线为准。
2. `demo/sim_life_vtuber_demo.py`：MuJoCo 物理代理。用于验证房间、调度、动作模板和物理路径，不再作为最终 VTuber 视觉验收画面。

当前展示策略：MuJoCo 只做物理和状态验证；给用户看的样片走 WebGL/Three.js 游戏式表现层。这样可以保留真实 VTuber 模型、字幕、音色、镜头和生活互动，不再把 MuJoCo 原生画面当成最终产品质感。

2026-07-04 更新：参考“夜间公寓生活模拟游戏”视觉方向后，WebGL 表现层加入了更接近游戏 HUD 的界面、后期 Bloom、城市夜景窗、厨房岛台、桌面、沙发区、灯具、书架、植物、底部对话条和音色标签。它仍然是可运行 WebGL 原型，不是 Unity 资产级最终画面。

当前选用的三个机器人架构角色是：

- Astra-F：女性人形陪伴机器人，底层模型使用 Lydia，外叠胸腔控制板、背包、肩/肘/膝执行器和线束。
- Mason-M：男性双足服务机器人，底层模型使用 Robert，外叠人形执行器和安全控制模块。
- Hex-01：非人形侦察机器人，底层模型使用 Polybot，保留更多外露模块和非人形扫描/维修特征。

本地模型路径：

```bash
assets/vtubers/open_source_avatars/lydia.vrm
assets/vtubers/open_source_avatars/robert.vrm
assets/vtubers/open_source_avatars/polybot.vrm
```

## 为什么之前手臂会展开

VRM 模型的默认绑定姿势通常接近 A-pose/T-pose。如果加载模型后直接叠加动作，但没有先把上臂、肩膀、前臂校准到自然垂臂，角色就会像手臂横向展开。

当前修复点：

- 开场动作从 `stretch` / `scan` 改为自然 `idle`。
- 每个角色在 `AGENTS` 里增加 `pose` 校准参数。
- `wave` 和 `dance` 模板收敛为小幅动作，上臂默认贴近身体。
- 三个角色使用左 / 中 / 右三条运动车道，减少镜头里互相穿插。
- 场景升级为 stylized studio：窗、海报、地面纹理、吊灯、家具、角色脚下光环。
- 活动层从泛化的 `idle/talk/think` 扩展为可见事件：咖啡、厨房、读书、画板、桌面工作、电话、扫描、维修、充电。
- 每个活动绑定道具或特效：杯子、平板、书、手机、锅、扳手、扫描束、充电环、维修火花。
- 录制时可用 `--clean` 隐藏大块 HUD，避免卡片遮挡身体导致误判。
- 游戏式导演层：预设对话节拍、说话人/倾听者朝向、底部字幕条、互动光环、角色之间的回应连线、分镜机位。
- 机器人硬件层：在人形/非人模型上外叠胸腔控制板、背包、电池包、传感器条、肩/肘/膝执行器和线束。

相关文件：

```bash
demo/vtuber_life_web/src/main.js
demo/vtuber_life_web/src/style.css
demo/vtuber_life_web/vite.record.config.mjs
demo/record_vtuber_life_web.mjs
demo/synthesize_vtuber_voice_track.mjs
```

## 安装

```bash
npx pnpm@10.11.0 install
npx playwright install chromium
```

## 浏览器预览

```bash
npx vite --host 127.0.0.1 --port 5178
```

然后打开：

```text
http://127.0.0.1:5178/demo/vtuber_life_web/index.html
```

干净画面预览：

```text
http://127.0.0.1:5178/demo/vtuber_life_web/index.html?clean=1
```

## 录制 Demo 动画

快速烟测，检查第 0 秒自然站姿：

```bash
node demo/record_vtuber_life_web.mjs \
  --duration-minutes 0.01 \
  --fps 2 \
  --width 1280 \
  --height 720 \
  --out outputs/webgl/vtuber_life_pose_smoke.mp4 \
  --frames-dir outputs/webgl/vtuber_life_pose_smoke_frames \
  --port 5180 \
  --clean
```

短样片，用 12 秒覆盖 30 分钟模拟周期，适合快速检查换动作后的姿态：

```bash
node demo/record_vtuber_life_web.mjs \
  --duration-minutes 0.2 \
  --sim-duration-minutes 30 \
  --fps 6 \
  --width 1280 \
  --height 720 \
  --out outputs/webgl/vtuber_life_true_vrm_activity_sample.mp4 \
  --frames-dir outputs/webgl/vtuber_life_true_vrm_activity_sample_frames \
  --port 5185 \
  --clean
```

游戏式互动样片，保留字幕条和分镜机位：

```bash
node demo/record_vtuber_life_web.mjs \
  --duration-minutes 0.2 \
  --sim-duration-minutes 30 \
  --fps 6 \
  --width 1280 \
  --height 720 \
  --out outputs/webgl/vtuber_life_gameplay_sample.mp4 \
  --frames-dir outputs/webgl/vtuber_life_gameplay_sample_frames \
  --port 5191 \
  --clean
```

机器人架构角色样片，使用 Astra-F / Mason-M / Hex-01：

```bash
node demo/record_vtuber_life_web.mjs \
  --duration-minutes 0.2 \
  --sim-duration-minutes 30 \
  --fps 6 \
  --width 1280 \
  --height 720 \
  --out outputs/webgl/vtuber_robot_arch_gameplay_sample.mp4 \
  --frames-dir outputs/webgl/vtuber_robot_arch_gameplay_sample_frames \
  --port 5196 \
  --clean
```

参考图方向的游戏化 HUD 样片，保留时间线、关系面板、角色卡、字幕条和语音波形：

```bash
node demo/record_vtuber_life_web.mjs \
  --duration-minutes 0.2 \
  --sim-duration-minutes 30 \
  --fps 6 \
  --width 1280 \
  --height 720 \
  --out outputs/webgl/vtuber_cinematic_life_gameplay_sample.mp4 \
  --frames-dir outputs/webgl/vtuber_cinematic_life_gameplay_sample_frames \
  --port 5205
```

给这版样片加语音、字幕和音色 manifest：

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/webgl/vtuber_cinematic_life_gameplay_sample.mp4 \
  --out outputs/webgl/vtuber_cinematic_life_gameplay_voiceover_warm.mp4 \
  --work-dir outputs/webgl/cinematic_voice_demo_warm \
  --mode auto \
  --duration 12
```

如果声音听起来尖细，先看 `voice_manifest.json`。当前免 key 样片大概率会走 `edge-tts`，不是 Fish Audio 克隆音色。尖细感通常来自三类参数：

- `edgeVoice` 选了偏年轻或偏亮的神经音色。
- `rate` 过快。
- `pitch` 和后处理同时抬高音高或高频。

当前已把 Astra-F 调整为 `zh-CN-XiaoxiaoNeural`、`rate: 164`、`pitch: 0.98`、`post: soft`，并把 Mason-M 调整为更低更稳的 `zh-CN-YunyangNeural`。

实际 8 小时录制：

```bash
node demo/record_vtuber_life_web.mjs \
  --duration-minutes 480 \
  --sim-duration-minutes 480 \
  --fps 6 \
  --width 1280 \
  --height 720 \
  --out outputs/webgl/vtuber_life_true_vrm_8h.mp4 \
  --frames-dir outputs/webgl/vtuber_life_true_vrm_8h_frames \
  --port 5190 \
  --clean
```

注意：8 小时、6 fps 会产生 172800 张中间帧，磁盘和时间成本很高。正式长录前先用 `--fps 2` 或 `--duration-minutes 1 --sim-duration-minutes 480` 做快速验收。

## 添加语音合成和音色模拟

视觉样片录完后，用下面的脚本把角色台词、音色和字幕混进视频：

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/webgl/vtuber_life_true_vrm_activity_sample.mp4 \
  --out outputs/webgl/vtuber_life_true_vrm_activity_voiceover.mp4 \
  --work-dir outputs/webgl/voice_demo \
  --mode auto \
  --duration 12
```

给新版游戏式样片加语音：

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/webgl/vtuber_life_gameplay_sample.mp4 \
  --out outputs/webgl/vtuber_life_gameplay_voiceover.mp4 \
  --work-dir outputs/webgl/gameplay_voice_demo \
  --mode auto \
  --duration 12
```

给机器人架构样片加语音：

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/webgl/vtuber_robot_arch_gameplay_sample.mp4 \
  --out outputs/webgl/vtuber_robot_arch_gameplay_voiceover.mp4 \
  --work-dir outputs/webgl/robot_arch_voice_demo \
  --mode auto \
  --duration 12
```

`--mode auto` 的降级顺序是：

1. `ai-core`：调用 `AI_CORE_URL` 的 `/tts/synthesize`，按角色写入 Fish Audio 音色 ID。
2. `edge-tts`：使用项目依赖里的 Edge TTS，给 Lydia / Robert / Polybot 分配不同中文神经音色。
3. `say-fallback`：最后才使用 macOS 系统朗读，保证 demo 不会因为外部 TTS 临时不可用而完全无声。

强制走真实 AI Core / Fish Audio：

```bash
AI_CORE_URL=http://127.0.0.1:8100 \
TTS_PROVIDER=fish \
FISH_AUDIO_API_KEY=... \
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/webgl/vtuber_life_true_vrm_activity_sample.mp4 \
  --out outputs/webgl/vtuber_life_true_vrm_activity_voiceover.mp4 \
  --work-dir outputs/webgl/voice_demo \
  --mode ai-core \
  --duration 12
```

只用 Edge TTS 生成免 key 样片：

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/webgl/vtuber_life_true_vrm_activity_sample.mp4 \
  --out outputs/webgl/vtuber_life_true_vrm_activity_voiceover.mp4 \
  --work-dir outputs/webgl/voice_demo \
  --mode edge \
  --duration 12
```

语音输出文件：

```text
outputs/webgl/vtuber_life_true_vrm_activity_voiceover.mp4
outputs/webgl/voice_demo/voice_mix.m4a
outputs/webgl/voice_demo/vtuber_life_voiceover.srt
outputs/webgl/voice_demo/voice_manifest.json
outputs/webgl/voice_demo/voice_waveform.png
```

验收时先看 `voice_manifest.json`。每一句台词都有 `provider`、`fishVoice`、`edgeVoice` 和 `fallbackVoice`。如果要证明真的走了 Fish Audio，不能只看视频是否有声音，还要确认 `provider` 是 `ai-core`，并检查 AI Core 日志中的 `tts.fish_audio_synthesize` / `tts.fish_voice_matched` / `voice_resolved`。

## 换 VTuber 模型

1. 把新的 `.vrm` 放到本地，例如：

```bash
assets/vtubers/custom/my_character.vrm
```

2. 修改 `demo/vtuber_life_web/src/main.js` 里的 `AGENTS`：

```js
{
  id: 'my_character',
  name: 'My Character',
  type: 'custom companion',
  model: '/assets/vtubers/custom/my_character.vrm',
  portrait: '/assets/vtubers/custom/my_character.png',
  color: '#f06bdc',
  accent: '#ffd36d',
  scale: 1.0,
  targetHeight: 1.55,
  pose: { upperZ: 1.58, upperX: -0.14, lowerX: -0.30, shoulderZ: 0.02 },
  schedule: [...]
}
```

3. 如果新模型站姿异常，优先调这几个字段：

- `targetHeight`：目标身高。
- `scale`：整体缩放微调。
- `pose.upperZ`：上臂向身体两侧收拢的程度。
- `pose.upperX`：手臂前后摆动的默认角度。
- `pose.lowerX`：前臂弯曲程度。

## 换人格和日程

人格主要由这些字段控制：

- `name`
- `type`
- `color` / `accent`
- `schedule`
- 每个日程项的动作模板和台词

日程项格式：

```js
['Breakfast chat', [-0.52, -0.25], 'talk', 'Morning check-in?']
```

含义：

- 第 1 项：显示给用户看的活动名。
- 第 2 项：房间里的目标位置 `[x, z]`。
- 第 3 项：动作模板，例如 `idle`、`talk`、`think`、`scan`、`wave`、`dance`。
- 第 4 项：气泡台词。

## MuJoCo 连接状态

MuJoCo 路径当前是物理代理，不是最终 VRM 皮肤渲染：

```bash
python demo/sim_life_vtuber_demo.py \
  --duration-minutes 0.05 \
  --record-fps 4 \
  --width 960 \
  --height 540 \
  --out outputs/mujoco/sim_life_960_smoke.mp4
```

要做到“任意 VTuber 模型直接在 MuJoCo 内以原始外观渲染”，还需要新增 VRM/GLB 到 MJCF mesh 的转换链路，或使用 MuJoCo 负责物理、WebGL/Unity/Blender 负责最终角色渲染的桥接式录制。当前可运行方案采用后者的方向：MuJoCo 保留为物理验证后端，真实 VTuber 画面由 WebGL VRM renderer 输出。

## Unity 视觉前端路径

本机已经检测并验证 Unity 6：

```text
/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app
```

我已用 batchmode 编译并生成 Unity 场景：

```text
unity/SoulForgeUnityClient/Assets/SoulForge/Scenes/SoulForgeApartment.unity
outputs/unity/soulforge_unity_apartment_preview.png
outputs/unity/soulforge_unity_apartment_demo.mp4
outputs/unity/soulforge_unity_apartment_demo_voiceover.mp4
outputs/unity/soulforge_unity_apartment_demo_voiceover_hardsub.mp4
outputs/unity/soulforge_unity_apartment_demo_contact_sheet.jpg
outputs/unity/unity_create_scene_richer_v4.log
outputs/unity/unity_capture_preview_richer_v3.log
outputs/unity/unity_capture_demo_frames_v3.log
```

Unity 视觉客户端项目结构：

```text
unity/SoulForgeUnityClient/
```

这个目录包含：

- `Packages/manifest.json`：Unity 6 已验证的离线最小包声明，包含 URP、TextMeshPro、UGUI 和核心模块。
- `ProjectSettings/`：Unity 项目识别所需的基础设置。
- `README.md`：Unity URP/UniVRM/Animation Rigging/Cinemachine/Recorder 接入步骤。
- `ASSET_REQUIREMENTS.md`：接近参考图所需的授权资产、动画、IK、镜头和 Recorder 标准。
- `UNITY_OPEN_CHECKLIST.md`：打开项目、重建场景、接入角色和 Recorder 的检查清单。
- `Assets/SoulForge/Scripts/SoulForgeBehaviorEvent.cs`：SoulForge 行为事件数据结构。
- `Assets/SoulForge/Scripts/SoulForgeBridge.cs`：离线 replay 驱动器，后续可替换为 WebSocket。
- `Assets/SoulForge/Scripts/SoulForgeWebSocketClient.cs`：Unity Editor/桌面端 WebSocket 输入。
- `Assets/SoulForge/Scripts/SoulForgeDialogueHud.cs`：对话 UI 绑定。
- `Assets/SoulForge/Scripts/SoulForgeVoiceClipPlayer.cs`：按事件播放语音 clip。
- `Assets/SoulForge/Scripts/SoulForgeAgentRegistry.cs`：角色 id 到 Transform 的注册表，用于动态 look-at。
- `Assets/SoulForge/Scripts/SoulForgeAgentController.cs`：按事件驱动角色移动、Animator trigger 和 emotion 参数。
- `Assets/SoulForge/Scripts/SoulForgeTimelineDirector.cs`：按 `cameraShot` 切换镜头 anchor。
- `Assets/SoulForge/Scripts/SoulForgeProceduralAgentAnimator.cs`：没有外部动画包时的临时动作层，能表现 cook、sketch、scan、repair、talk、call、dance 等模板。
- `Assets/SoulForge/Editor/SoulForgeSceneBuilder.cs`：一键生成公寓 graybox、三类机器人角色、HUD、预览截图和 Recorder-free 帧序列。
- `Assets/SoulForge/Samples/replay_events.json`：Unity 离线测试事件样例，当前 11 条事件。
- `demo/burn_subtitles_to_frames.py`：当 ffmpeg 没有 subtitles/drawtext filter 时，用 Pillow 把 SRT 逐帧烧进 Unity 帧序列。

导出 Unity replay 事件：

```bash
node demo/export_unity_behavior_events.mjs \
  --out outputs/unity/soulforge_unity_replay_events.json \
  --duration 12
```

刷新 Unity 项目内置样例：

```bash
node demo/export_unity_behavior_events.mjs \
  --out unity/SoulForgeUnityClient/Assets/SoulForge/Samples/replay_events.json \
  --duration 12
```

推荐架构：

```text
SoulForge planner / LLM / voice / MuJoCo
        -> behavior event JSON or WebSocket
        -> Unity visual client
        -> UniVRM + IK + licensed scene assets + Recorder
```

要达到参考图质感，Unity 侧需要真实授权室内资产、PBR 材质、动画片段、手部 IK、Cinemachine 分镜、URP/HDRP 后期和 Unity Recorder；WebGL 原型只用于验证行为、角色差异、HUD 和录制链路。

当前 Unity 包管理器访问线上 registry 时出现过 `ECONNRESET`，所以我先把工程改成可离线启动的 Unity 6 最小 manifest。Cinemachine、Animation Rigging、UniVRM 和 Unity Recorder 仍然是目标能力，等 Package Manager 网络稳定后再安装。

Unity 免 Recorder 短样片：

```bash
"/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit \
  -projectPath "/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient" \
  -executeMethod SoulForge.UnityClient.Editor.SoulForgeSceneBuilder.CaptureApartmentDemoFrames \
  -logFile "/Users/lovelyjoy/Desktop/soulForge/outputs/unity/unity_capture_demo_frames_v3.log"

ffmpeg -y -framerate 12 \
  -i outputs/unity/apartment_demo_frames/frame_%04d.png \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart \
  outputs/unity/soulforge_unity_apartment_demo.mp4
```

给 Unity 样片加和 replay JSON 对齐的语音、字幕和 voice manifest：

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/unity/soulforge_unity_apartment_demo.mp4 \
  --out outputs/unity/soulforge_unity_apartment_demo_voiceover.mp4 \
  --work-dir outputs/unity/unity_voice_demo \
  --mode auto \
  --duration 12 \
  --events-json unity/SoulForgeUnityClient/Assets/SoulForge/Samples/replay_events.json
```

如果播放器不显示内嵌字幕，生成硬字幕版：

```bash
python3 demo/burn_subtitles_to_frames.py \
  --frames-dir outputs/unity/apartment_demo_frames \
  --srt outputs/unity/unity_voice_demo/vtuber_life_voiceover.srt \
  --out-dir outputs/unity/apartment_demo_hardsub_frames \
  --fps 12

ffmpeg -y -framerate 12 \
  -i outputs/unity/apartment_demo_hardsub_frames/frame_%04d.png \
  -i outputs/unity/unity_voice_demo/voice_mix.m4a \
  -c:v libx264 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart \
  outputs/unity/soulforge_unity_apartment_demo_voiceover_hardsub.mp4
```

## 当前已验证输出

```text
outputs/webgl/vtuber_life_pose_smoke.mp4
outputs/webgl/vtuber_life_wave_pose_smoke.mp4
outputs/webgl/vtuber_life_true_vrm_quality_sample.mp4
outputs/webgl/vtuber_life_true_vrm_quality_contact_sheet.jpg
outputs/webgl/vtuber_life_true_vrm_activity_sample.mp4
outputs/webgl/vtuber_life_true_vrm_activity_contact_sheet.jpg
outputs/webgl/vtuber_life_true_vrm_activity_voiceover.mp4
outputs/webgl/vtuber_life_gameplay_sample.mp4
outputs/webgl/vtuber_life_gameplay_voiceover.mp4
outputs/webgl/vtuber_life_gameplay_contact_sheet.jpg
outputs/webgl/vtuber_robot_arch_gameplay_sample.mp4
outputs/webgl/vtuber_robot_arch_gameplay_voiceover.mp4
outputs/webgl/vtuber_robot_arch_gameplay_contact_sheet.jpg
outputs/webgl/vtuber_cinematic_life_gameplay_sample.mp4
outputs/webgl/vtuber_cinematic_life_gameplay_voiceover.mp4
outputs/webgl/vtuber_cinematic_life_gameplay_voiceover_warm.mp4
outputs/webgl/vtuber_cinematic_life_gameplay_contact_sheet.jpg
outputs/webgl/voice_demo/voice_manifest.json
outputs/webgl/gameplay_voice_demo/voice_manifest.json
outputs/webgl/robot_arch_voice_demo/voice_manifest.json
outputs/webgl/cinematic_voice_demo/voice_manifest.json
outputs/webgl/cinematic_voice_demo_warm/voice_manifest.json
```

最近一次本地验证：

```text
1280x720
6 fps
72 frames
12 秒视频覆盖 30 分钟模拟周期
真实 VRM 模型：Lydia / Robert / Polybot
当前角色包装：Astra-F 女性人形 / Mason-M 男性双足 / Hex-01 非人机器人
Three.js + @pixiv/three-vrm 真实 VRM 渲染
stylized studio 场景 + 三角色运动车道
可见活动道具：杯子 / 书 / 平板 / 手机 / 锅 / 扳手 / 扫描束 / 充电环
干净录制模式：--clean
游戏式表现层：底部字幕条 / 说话人高亮 / 倾听者转头 / 互动光环 / 分镜机位
机器人硬件层：胸腔控制板 / 背包 / 传感器条 / 关节执行器 / 线束
语音合成样片：11 句角色台词，全部走 edge-tts provider
输出流：h264 视频 + aac 音频 + mov_text 内嵌字幕
游戏化参考样片：1280x720 / 72 frames / 12 秒覆盖 30 分钟模拟 / h264 + aac + mov_text
```

## 当前真实度边界

这版已经不是“站着抖动”的演示，但仍然是程序化动作系统：

- 手部道具是按角色位置近似绑定，不是精确手掌 IK。
- 没有使用 BVH/FBX/mocap 动画片段，所以走路、坐下、拿取、放下还不是自然动画。
- 没有完整物体状态机，例如锅不会真的放到桌上再拿起，书不会逐页翻动。
- 角色之间没有碰撞避让，只是用三条运动车道降低穿插。
- 当前 WebGL 房间仍是程序化几何体，不是 Unity/Godot/Unreal 级别的真实室内资产。
- 机器人硬件层目前是外叠式可视化结构，还不是和 VRM 骨骼严密绑定的 CAD/URDF 机构。

要继续提升到更真实的 VTuber/游戏级 demo，下一步应该接入：

- VRM humanoid IK，用手部目标点绑定杯子、书、平板、手机、扳手。
- 一组动作片段库：walk、idle、sit、read、type、repair、wave、dance、sleep。
- 活动状态机：走到目标点 -> 拿道具 -> 执行动作 -> 放回道具 -> 转场。
- 更真实的场景资产或导入 GLB 房间模型。
- 如果目标是商业级观感，推荐新增 Unity 或 Godot 前端：SoulForge 负责日程/LLM/行为状态，游戏引擎负责 VRM 动画、IK、摄像机、光照、后期和录制。
