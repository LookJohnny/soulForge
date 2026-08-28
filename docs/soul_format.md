# `.soul` — 灵魂包格式 v2.0

一个 `.soul` 文件 = **一个角色本体的全部**：人格、音色、3D/毛绒外观、表情参数、知识、可选专属事件。
**不含任何用户数据**——关系进度、记忆、情绪历史属于"用户 × 角色"的存档，走 `GET/POST /relationship/{user}/{character}/export|import`。

把 `.soul` 丢给任何身体（`/live` 桌面形象、Studio、玩具固件、Unity 客户端），它就变成这个角色；换身体不换灵魂。

## 容器

```
SOUL2\n                      ← 魔数
{"enc":"none|pass","salt":…,"soul_id":…}\n   ← 一行 JSON 头（无需解密即可读）
<ZIP>                        ← 明文 ZIP，或用口令派生密钥（PBKDF2-SHA256×200k → AES）加密后的 ZIP
```

- `enc:"none"`：可直接分发（内部用、开源角色）。
- `enc:"pass"`：**口令就是发布 key**（形如 `SF-7K2M-9QXA`），文件 + 口令即可在任意品牌/任意身体加载；给玩具厂/IP 方的授权就是发口令。
- 旧版 `.soulpack`（v1.0，品牌密钥加密、不可跨品牌）仍可读，不再生成。

## ZIP 内容

| 路径 | 必需 | 内容 |
|---|---|---|
| `manifest.json` | ✓ | `version` `soul_id` `name` `author` `license` `created_at` `compat{protocol,vrm,soulforge}` `capabilities[]` `files{path:sha256}` `checksum` |
| `character.json` | ✓ | 可移植的人格字段：name/archetype/species/backstory/relationship/personality/catchphrases/suffix/topics/forbidden/response_length/voice_speed/language_mode/vocalization_palette/age_setting/emotion_config/audio_clips/llm_*/tts_provider（**不含** id/brand/时间戳） |
| `prompt_template.j2` | | 自定义系统提示模板 |
| `voice/profile.json` | | 音色配置（fish reference_id / edge voice / dashscope…） |
| `voice/reference.wav` | | 声音克隆参考音频 |
| `embodiment/embodiment.json` | | `kind`(vrm/glb/fbx/plush) `model`(包内文件名或 URL) `target_height` `pose{upperZ…}` `toon` `idle_clips[]` |
| `embodiment/model.<ext>` | | 模型文件本体（VRM/GLB/FBX；大文件可改为 URL + 哈希） |
| `expression.json` | | `intensity`（表情烈度 0–1）、`mouth_style`(mixed/lips/jaw/off)、`pad_baseline{p,a,d}` |
| `events.json` | | 角色专属事件/台词覆盖（缺省用内置 28 个） |
| `studio.json` | | 引擎侧人格（`configs/characters.json` 条目：traits/daily_goals/role_label/color/comfort_line/energy） |
| `rag/<name>` | | 知识库文档 |
| `avatar.png` | | 头像 |

完整性：`manifest.files` 记录每个文件的 SHA-256，`checksum` 是文件哈希清单的哈希；读取时逐一校验，篡改即拒绝。

## API

| 端点 | 作用 |
|---|---|
| `POST /soul-packs/export` | 从 ai-core 角色表导出（可附 `embodiment`/`expression`/`studio`/`model_b64`/`passphrase`），返回 base64 |
| `POST /soul-packs/export.bin` | 同上，直接下载 `<name>.soul` |
| `POST /soul-packs/peek` | 只读文件头：版本、soul_id、是否需要口令 |
| `POST /soul-packs/import` | 导入到当前品牌的角色表（v2 需口令时传 `passphrase`；v1 用品牌密钥） |
| Studio `POST /api/soul/export` | 把 `configs/characters.json` 的某个角色 + 模型文件打成 `.soul` |
| Studio `POST /api/soul/import` | 解包 → 写 `configs/characters.json` + 模型存入 `assets/vtubers/souls/<soul_id>/` + 调 ai-core 入库 |

## 版本策略

- `manifest.compat.soulforge` 是最低兼容版本；读取端遇到未知文件直接忽略（向前兼容）。
- 未来的"灵魂 Key 注册表"（输入短码即拉包）只是在这个格式之上加托管与签名，不改容器。
