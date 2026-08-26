# 把 FBX / PMX / 商业角色做成高质量 VRM（Blender 离线管线）

`/live` 能直接吃 FBX / GLB（`studio/web/lib/humanoid_adapter.js` 会把任意人形骨架合成 VRM），
但"拖进来就能用"路径只有文件自带的材质、没有 MToon 卡渲、没有弹簧骨、表情要靠 morph 命名碰运气。
想要接近叠纸那种观感，**离线转成 VRM 1.0** 才是上限路径。本文是这条路的检查清单。

## 工具（全部免费）

| 工具 | 用途 | 许可 |
|---|---|---|
| Blender 4.x | 主工具 | GPL（工具本身，不影响你的模型） |
| [VRM Add-on for Blender](https://vrm-addon-for-blender.info/) | 导入/导出 VRM 0.x/1.0，MToon，弹簧骨，表情 | MIT |
| [mmd_tools](https://github.com/MMD-Blender/blender_mmd_tools) | 导入 PMX/PMD/VMD | GPL |
| [VRoid Studio](https://vroid.com/studio) | 从零捏一个二次元角色直接出 VRM | 免费；样例模型可商用 |

## 流程

1. **导入**
   - FBX：`File → Import → FBX`，勾 *Automatic Bone Orientation*；Mixamo/Unity 导出的 cm 尺度勾 *Apply Transform* 或事后 `Scale 0.01 → Apply`。
   - PMX：`File → Import → MikuMikuDance Model`，勾 *Rename bones (to Blender/英文)* 便于后续指派；材质用 *Toon* 会自动转 MMD 卡渲近似。
2. **人形骨骼指派**（VRM 面板 → *Humanoid* → *Bone Assignment*）
   - 必需 15 根：Hips / Spine / Head / 左右 UpperArm、LowerArm、Hand / 左右 UpperLeg、LowerLeg、Foot；Neck / Chest / 眼睛 / 手指 尽量补齐（注视和握拳靠它们）。
   - Mixamo 名可直接 *Auto-assign*；MMD 名对照：下半身→Hips、上半身→Spine、上半身2→Chest、首→Neck、頭→Head、左肩→LeftShoulder、左腕→LeftUpperArm、左ひじ→LeftLowerArm、左手首→LeftHand、左足→LeftUpperLeg、左ひざ→LeftLowerLeg、左足首→LeftFoot、左つま先→LeftToes、左目→LeftEye。
3. **静息姿态必须是 T-pose**（VRM 1.0 规范；我们的 VRMA 动捕重定向也以此为前提）
   - A-pose 模型：Pose 模式把上臂绕 Z 抬到水平 → `Pose → Apply → Apply Pose as Rest Pose`。
   - 面向 **+Z**（Blender 里是 −Y 前方，插件导出会转换；导入 FBX 后若背对相机，Object 模式绕 Z 转 180° 再 Apply Rotation）。
4. **表情（Expressions）**
   - VRM 面板 → *Expressions*：给 `aa/ih/ou/ee/oh`（口型）、`blink/blinkLeft/blinkRight`、`happy/angry/sad/relaxed/surprised` 逐个绑定 shape key。
   - ARKit 52 blendshape 的模型：`jawOpen→aa`、`mouthFunnel→oh`、`mouthPucker→ou`、`eyeBlinkLeft/Right→blinkLeft/Right`、`mouthSmileLeft+Right→happy`、`mouthFrownLeft+Right→sad`、`browDownLeft+Right→angry`、`browInnerUp+eyeWide→surprised`。
   - MMD：あ→aa、い→ih、う→ou、え→ee、お→oh、まばたき→blink、笑い→happy、困る→sad、怒り→angry、びっくり→surprised。
   - 没有 shape key 的模型（Mixamo Y-Bot 这类）不会有口型/表情——只能重新雕刻或换模型。
5. **材质 → MToon**
   - 选中材质 → VRM 面板 *Material* → *MToon*：Lit/Shade 颜色、Shade Toony（二阶化程度）、Outline（Width Mode = World Coordinates，宽度 0.05–0.1 cm）、Rim、MatCap（头发高光可用 MatCap 假高光）。
   - 脸部阴影想要"叠纸感"：Shade 贴图画成 SDF 式渐变、`Shading Shift` 拉高、关掉 Receive Shadow。
6. **弹簧骨（头发/裙摆/尾巴）**
   - VRM 面板 *Spring Bone* → 新建 Spring → 添加 Joint 链（从根到梢）→ 设 stiffness 0.8–1.5、drag 0.4、gravity 0.02；碰撞体挂在头/胸/大腿。
   - MMD 模型的物理刚体不会自动转换，需要手动重建 Spring。
7. **导出**：`File → Export → VRM 1.0`，勾 *Export only selections* 与 *Enable MToon outline*；文件放进 `assets/vtubers/<你的目录>/`，旁边放 `LICENSE.txt`（`/api/models` 会读第一行显示在选择器里）。
8. **验证**：`uv run python studio/server.py` → `/live?model=<文件名>` → 看 idle 动捕、注视、口型（发一句话）、表情（聊到开心/难过）、弹簧骨是否晃。

## 常见坑

- **导入后四肢散架**：骨骼停在动画第一帧而不是绑定姿态 → Pose 模式 `Pose → Clear Transform → All`，再 *Apply as Rest Pose*。
- **Mixamo 名带前缀** `mixamorig:` 无所谓，插件能识别；但 Blender FBX 导出时 `:` 会被替换，别在别的引擎里再依赖冒号。
- **VRM 0.x vs 1.0**：0.x 面向 −Z、表情叫 `Joy/Angry/Sorrow/Fun`；`/live` 两者都认（three-vrm 自动升级），新做一律 1.0。
- **尺度**：VRM 单位是米；身高 1.5–1.8 m。`/live` 会按包围盒归一到 1.55 m，但弹簧骨参数依赖真实尺度。
- **许可**：VRoid Hub 模型看 *Conditions of use*；Booth 商品看"可商用/可改造"；MMD 模型看 readme 的二次配布/改造条款——**叠纸等游戏的官方模型不可用**。
