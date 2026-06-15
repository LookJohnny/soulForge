# AI + Robotics 工程论文与复现资料清单

更新日期: 2026-06-12

这份清单按 SoulForge 的实际产品形态整理: 有人格、长期记忆、语音、情绪、动作、硬件协议、仿真、安全和可置信度评估的 AI 角色/玩具/机器人平台。筛选标准不是“论文名气最大”，而是:

- 顶会/顶刊优先: RSS、CoRL、ICRA、NeurIPS、Science Robotics、ACM THRI、PMLR 等。
- 工程产物优先: 有代码、模型、数据集、硬件 BOM、装配教程、仿真环境或真实机器人实验。
- 对 SoulForge 可迁移: 能直接启发 `memory`、`persona_context`、`hardware_mapper`、Gateway 协议、RL 训练、数字孪生、语音情绪或陪伴体验。

## 先读/先复现清单

| 优先级 | 方向 | 论文 / 项目 |  venue / 状态 | 工程产物 | 对 SoulForge 的作用 |
|---|---|---|---|---|---|
| P0 | 长期记忆与可信陪伴 | [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442) / [GitHub](https://github.com/joonspk-research/generative_agents) | UIST 2023 | 核心仿真代码、Smallville 环境、复现说明 | 直接对应五层记忆、反思、计划、关系状态。适合改造成 SoulForge 的 `memory compilation` 和主动陪伴调度参考。 |
| P0 | 记忆系统架构 | [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) / [Letta](https://github.com/letta-ai/letta) / [Research site](https://research.memgpt.ai/) | arXiv / Letta 工程化 | 开源 Agent memory 框架、持久化 memory blocks | 对 `memory_policy.py`、长期上下文调度、隐式记忆注入很有参考价值。重点看 memory tier、interrupt、上下文分页思想。 |
| P0 | 低成本机器人学习 | [Learning Fine-Grained Bimanual Manipulation with Low-Cost Hardware](https://tonyzhaozh.github.io/aloha/) / [RSS page](https://roboticsconference.org/2023/program/papers/016/) | RSS 2023 | ALOHA 代码、硬件教程、ACT 策略、低成本双臂系统 | 最适合做 SoulForge 的第一个“可复现实机学习”参考。ACT 的 action chunk 思想也适合表达动作序列。 |
| P0 | 可复现机器人学习栈 | [LeRobot](https://github.com/huggingface/lerobot) / [docs](https://huggingface.co/docs/lerobot/en/index) / [SO-101 build](https://huggingface.co/docs/lerobot/so101) | arXiv 2026 / OSS | PyTorch 机器人学习库、SO-101 教程、数据采集/训练/评估流程 | 如果要把 SoulForge 接到便宜实物机械臂或桌面机器人，优先从 LeRobot + SO-101 跑通。 |
| P0 | 模仿学习动作策略 | [Diffusion Policy: Visuomotor Policy Learning via Action Diffusion](https://diffusion-policy.cs.columbia.edu/) / [GitHub](https://github.com/real-stanford/diffusion_policy) | RSS 2023 | 代码、Colab、真实/仿真 benchmark | 可用于把“情绪/人格 -> 连续动作”从规则映射升级为可学习策略，尤其适合平滑 expressive motion。 |
| P0 | 开源通用机器人策略 | [Octo: An Open-Source Generalist Robot Policy](https://octo-models.github.io/) / [GitHub](https://github.com/octo-models/octo) | RSS 2024 | 模型权重、JAX 训练/微调脚本、Open X 数据加载器 | 可作为 SoulForge 后续 generalist robot policy 的接口参考。短期不建议重训，建议只学数据格式和 fine-tune API。 |
| P0 | 开源 VLA | [OpenVLA](https://proceedings.mlr.press/v270/kim25c.html) / [GitHub](https://github.com/openvla/openvla) | CoRL 2024 / PMLR 2025 | 7B VLA、训练/微调代码 | 适合做“语言指令 + 视觉 + 动作”的长线能力。短期可借鉴 action tokenizer 和 VLA fine-tuning 接口。 |
| P1 | 大规模跨机器人数据 | [Open X-Embodiment / RT-X](https://robotics-transformer-x.github.io/) / [GitHub](https://github.com/google-deepmind/open_x_embodiment) | ICRA 2024 / Google DeepMind | 1M+ 真实机器人轨迹、22 类机器人、统一 RLDS 格式 | 适合设计 SoulForge 自己的 hardware/action log schema，避免未来数据不可训练。 |
| P1 | VLA / flow policy | [pi0: A Vision-Language-Action Flow Model](https://arxiv.org/html/2410.24164v1) / [openpi](https://github.com/Physical-Intelligence/openpi) / [blog](https://www.pi.website/blog/openpi) | arXiv / 强工程项目 | 开源模型、权重、ALOHA/DROID 示例、微调代码 | 适合研究“预训练机器人模型如何落到具体硬件”。短期更适合作为 benchmark，而不是主路线。 |
| P1 | LLM 到机器人动作 | [Code as Policies](https://code-as-policies.github.io/) | ICRA 2023 | 项目页、真实机器人 demos、可执行 policy program 思路 | 对 SoulForge 的 `hardware_mapper` 很关键: LLM 不直接发低层电机命令，而是生成受限的可审计动作程序。 |
| P1 | 可执行性约束 | [SayCan: Do As I Can, Not As I Say](https://say-can.github.io/) / [Google Research](https://research.google/pubs/do-as-i-can-not-as-i-say-grounding-language-in-robotic-affordances/) | CoRL 2022 / PMLR 2023 | 项目页、真实机器人演示 | 对 SoulForge 很重要: 角色想做什么不等于硬件能做什么。要用 affordance / capability gate 约束动作。 |
| P1 | 闭环语言推理 | [Inner Monologue](https://innermonologue.github.io/) / [PMLR](https://proceedings.mlr.press/v205/huang23c.html) | CoRL 2022 / PMLR 2023 | 项目页、真实/仿真任务 | 可以改造成 SoulForge 的“感知反馈 -> 语言状态 -> 动作修正”闭环，用于触摸、打断、设备状态、失败恢复。 |
| P1 | 角色机器人设计 | [Olaf: Bringing an Animated Character to Life in the Physical World](https://arxiv.org/abs/2512.16705) | arXiv 2025 / Disney Research | 真实硬件验证、RL 控制、机构设计说明 | 对 SoulForge 的“角色动作可置信度”非常重要。重点学: animation reference、隐藏机构、温度/噪音 reward、believability 优先于工业效率。 |
| P1 | 角色机器人控制 | [Design and Control of a Bipedal Robotic Character](https://arxiv.org/html/2501.05204v1) / [Disney PDF](https://la.disneyresearch.com/wp-content/uploads/BD_X_paper.pdf) | Disney Research / robotics paper | 真实 biped character、RL pipeline | 适合指导 SoulForge 的 `believability`、`motion`、`safety` 模块: 角色型机器人不是普通 locomotion，动作要符合角色身份。 |
| P1 | 社交机器人硬件 | [Blossom: A Handcrafted Open-Source Robot](https://dl.acm.org/doi/10.1145/3310356) / [GitHub](https://github.com/hrc2/blossom-public) | ACM THRI 2019 | 开源硬件、开源软件、柔性社交机器人 | 很适合 SoulForge 的“毛绒/桌面陪伴实体”第一阶段。比机械臂更贴近陪伴产品。 |
| P1 | 仿真 benchmark | [RoboCasa](https://robocasa.ai/) / [GitHub](https://github.com/robocasa/robocasa) / [arXiv](https://arxiv.org/abs/2406.02523) | RSS 2024 | 大规模家庭环境仿真、任务、数据集 | 对 SoulForge 的数字孪生和自动评测有用。不是直接复制场景，而是学习任务生成、资产管理和 evaluation protocol。 |
| P2 | 机器人学习仿真 | [Isaac Lab](https://isaac-sim.github.io/IsaacLab/) / [GitHub](https://github.com/isaac-sim/IsaacLab) / [arXiv](https://arxiv.org/html/2511.04831v1) | arXiv / NVIDIA OSS | GPU 仿真、RL/IL/motion planning workflow | 若后续要做真实 sim-to-real，Isaac Lab 是主流路线。当前 SoulForge 可先用轻量 simulator，等硬件成型再接入。 |
| P2 | 腿式机器人 sim-to-real | [legged_gym](https://github.com/leggedrobotics/legged_gym) / [PMLR paper](https://proceedings.mlr.press/v164/rudin22a.html) | CoRL 2021 / PMLR 2022 | ANYmal 训练环境、domain randomization、actuator network | 对低成本玩具移动底盘/四足宠物有参考价值，尤其是 domain randomization 和 actuator modeling。 |
| P2 | 机器人示教学习框架 | [robomimic](https://robomimic.github.io/) / [GitHub](https://github.com/ARISE-Initiative/robomimic) | CoRL 2021 / ARISE | 数据集、offline imitation learning 算法、benchmark | 适合作为 SoulForge 动作学习的 baseline 框架，尤其是先在离线数据上验证策略。 |
| P2 | 情绪/风格 TTS | [StyleTTS 2](https://proceedings.neurips.cc/paper_files/paper/2023/hash/3eaad2a0b62b5ed7a2e66c2188bb1449-Abstract-Conference.html) / [project](https://styletts2.github.io/) / [GitHub](https://github.com/yl4579/StyleTTS2) | NeurIPS 2023 | 代码、demo、训练脚本 | 对 SoulForge 的本地/自部署 TTS 备选很有价值，尤其是情绪风格控制和参考音色。 |
| P2 | 低延迟多语种 TTS | [CosyVoice 2](https://arxiv.org/html/2412.10117v1) / [GitHub](https://github.com/FunAudioLLM/CosyVoice) | arXiv / Alibaba OSS | 多语种 TTS、zero-shot voice、streaming/non-streaming | 对中文陪伴玩具更实用。可作为 Fish Audio 外的本地或私有部署备选。 |

## SoulForge 模块映射

### 1. 五层记忆、关系和主动陪伴

最值得对照:

- Generative Agents: 记忆流、反思、计划三件套。SoulForge 可以把事件记忆编译成 `relationship`、`private_state`、`robot_behavior_hints`，而不是每次都把历史事实直接塞进 prompt。
- MemGPT / Letta: 把 LLM 上下文当 cache，把外部长期记忆当存储层。SoulForge 已有五层记忆和 policy，下一步可以加 memory compaction job、睡眠期总结、冲突检测和可回滚的 memory block。
- Reflexion: 失败后的语言反思进入 episodic memory。SoulForge 可用于“角色说错话/动作失败/用户纠正”后的自我修正，而不是只写普通聊天记录。
- Voyager: 技能库与自我验证。SoulForge 可把硬件动作、互动套路、安静陪伴策略做成可复用 skill library。

建议落地:

1. 新增 `memory_reflection_jobs`: 异步把原始事件归纳成稳定偏好、关系状态和禁忌。
2. 给每条 compiled memory 加 `allowed_channels`: `dialogue`、`voice`、`motion`、`lighting`、`proactive`.
3. 在后台显示“这条记忆影响了哪些回答/动作”，避免黑箱陪伴。

### 2. LLM 到硬件动作: 从会说话到会做事

最值得对照:

- Code as Policies: 让 LLM 生成受限 Python / DSL 程序，而不是裸 JSON 电机命令。
- SayCan: 先判断动作是否有用，再判断硬件是否能做。SoulForge 的 `hardware_manifest` 可以变成 affordance scorer。
- Inner Monologue: 把传感器反馈、失败检测、人类纠正变成语言状态，供下一步规划使用。
- ProgPrompt: 用程序化 prompt 描述可用动作、对象和环境约束，降低 LLM 编造动作的概率。

建议落地:

1. 在 `protocol/primitives.proto` 上层加一个 `ActionPlan DSL`，只允许调用白名单 primitives。
2. `hardware_manifest.json` 不只描述 actuator，还要描述 capability score，例如 `can_nod=0.8`、`can_walk=0.0`、`can_blink=1.0`。
3. `hardware_mapper.py` 从规则表升级为 `intent -> affordance gate -> primitive plan -> degradation matrix`。
4. 所有 LLM 生成动作都必须过 safety/capability validator，不能直接进入 Gateway。

### 3. 表达动作学习: 从规则动作到可置信动作

最值得对照:

- Diffusion Policy: 适合连续动作、平滑轨迹、多模态观测。
- ACT / ALOHA: action chunk 能减少高频控制的误差积累，适合“头部/眼睛/耳朵/身体摆动”的短动作片段。
- Disney Olaf / BD-X: 角色机器人核心不是效率，而是角色身份一致、冲击噪音低、热安全、动作看起来“活”。
- robomimic: 先用离线示教数据跑 baseline，不要一上来直接大模型。

建议落地:

1. 用现有 `motion/`、`engine/`、`believability/` 先做一个 keyframe/teleop 数据格式: `emotion + persona + primitive + servo trace + rating`.
2. 第一版不学复杂 manipulation，只学 5-10 个 expressive clips: 打招呼、害羞、点头、摇头、兴奋、困倦、安静陪伴、被摸头。
3. 训练 baseline 顺序: rule-based smoother -> ACT -> Diffusion Policy。
4. 指标不要只看轨迹误差，要加 SoulForge 已有的 believability、impact、thermal、battery、安全约束。

### 4. 可复现硬件路线

| 路线 | 适合阶段 | 资料 | 为什么适合 SoulForge |
|---|---|---|---|
| Blossom 社交机器人 | 最贴近“陪伴玩具/MVP 实体” | [paper](https://dl.acm.org/doi/10.1145/3310356), [GitHub](https://github.com/hrc2/blossom-public) | 软外观、低自由度、HRI 友好，适合先验证角色生命感。 |
| LeRobot SO-101 | 第一个可学习机械臂 | [SO-101 docs](https://huggingface.co/docs/lerobot/so101), [LeRobot](https://github.com/huggingface/lerobot) | 装配、数据采集、训练、评估都有教程，适合学习 robot learning 全流程。 |
| ALOHA / Mobile ALOHA | 高阶双臂/移动操作 | [ALOHA](https://tonyzhaozh.github.io/aloha/), [Mobile ALOHA](https://mobile-aloha.github.io/), [GitHub](https://github.com/MarkFzp/mobile-aloha) | 工程完整，但成本和复杂度较高。适合参考，不适合第一台 SoulForge 原型。 |
| Reachy Mini / Reachy 2 | 桌面开源 HRI / AI builder | [Reachy Mini GitHub](https://github.com/pollen-robotics/reachy_mini), [Pollen Robotics](https://www.pollen-robotics.com/) | 表情和上身互动更接近陪伴角色，SDK 友好。 |
| Stanford Pupper | 四足宠物/教育机器人 | [GitHub](https://github.com/stanfordroboticsclub/StanfordQuadruped), [build docs](https://pupper.readthedocs.io/en/latest/) | 如果 SoulForge 做“宠物型移动底盘”，Pupper 比工业四足更适合低成本验证。 |
| OpenCat / Bittle | 更便宜的四足宠物路线 | [OpenCat GitHub](https://github.com/PetoiCamp/OpenCat-Quadruped-Robot) | 成本低、教育生态强，适合测试语音+动作+触摸反馈。 |

优先建议: Blossom 或 Reachy Mini 做“陪伴生命感”，SO-101 做“AI 机器人学习能力展示”。不要一开始就做 Mobile ALOHA 级别复杂系统。

### 5. 语音、情绪和多模态体验

SoulForge 当前已有 Fish Audio / Cosy 等接入方向。研究层面建议重点看:

- StyleTTS 2: 情绪/风格扩散，适合研究“文本情绪 -> 语音风格”的模型化方式。
- CosyVoice 2/3: 中文、多语种、低延迟、zero-shot，工程价值更接近产品。
- VALL-E: neural codec language model 思路，适合理解为什么短音频 prompt 能做 speaker adaptation。

落地建议:

1. 保持商业 TTS 作为默认产品路径。
2. 自建评测集: 角色一致性、情绪强度、延迟、中文自然度、儿童安全、失败率。
3. 对本地 TTS 做离线备选，不要在 MVP 阶段把训练 TTS 当主线。

## 30 天复现路线

### 第 1 周: 文档和接口定型

- 读 Generative Agents、MemGPT、Code as Policies、SayCan。
- 输出 SoulForge `ActionPlan DSL` 草案。
- 给 `hardware_manifest.schema.json` 增加 capability / affordance 设计草案。
- 把五层记忆的输出通道从 prompt 扩展到 `voice`、`motion`、`proactive`。

### 第 2 周: 低成本硬件选择并跑通

- 如果目标是陪伴玩具: 复现 Blossom 或 Reachy Mini SDK。
- 如果目标是 robot learning demo: 复现 LeRobot SO-101 的 record/train/evaluate。
- 把 SoulForge Gateway 接入一个真实设备或模拟设备，至少能跑: greeting、nod、idle breathing、touch response。

### 第 3 周: 动作学习 baseline

- 先用规则生成 8 类 expressive clips。
- 录制或合成每类 20-50 条轨迹。
- 用 robomimic / LeRobot / 简化 ACT 训练第一版动作 chunk 策略。
- 与现有 `motion/smoother.py`、`engine/blender.py`、`believability/metrics.py` 对比。

### 第 4 周: 产品级闭环

- 接入 Inner Monologue 风格反馈: 用户打断、触摸、硬件失败、温度/电量反馈进入状态机。
- 接入 SayCan 风格 capability gate: 不能做的动作自动降级。
- 生成一份 demo: 同一个角色在不同硬件 tier 上表现不同，但人格一致。
- 做一次真实 smoke test: 语音、记忆、动作、失败降级、后台审计全链路。

## 不建议现在投入过深的方向

- 从零训练 OpenVLA / pi0 / Octo: 数据和算力要求高，短期回报低。先学接口、数据格式和微调方式。
- Mobile ALOHA 全量复现: 工程价值大，但成本、空间、调试复杂度都高。适合作为融资演示后期目标。
- 复杂双足/四足 RL: 先用桌面 expressive body 或低成本机械臂证明 SoulForge 的角色/语音/记忆/动作闭环。
- 自研完整 TTS 基座: 可以评测和微调，不建议作为当前主线。

## 推荐阅读顺序

1. Generative Agents
2. MemGPT / Letta
3. Code as Policies
4. SayCan
5. ALOHA / ACT
6. LeRobot SO-101
7. Diffusion Policy
8. Disney Olaf / BD-X
9. Octo / Open X-Embodiment
10. OpenVLA / pi0

这个顺序的原因是: SoulForge 的壁垒先来自“人格记忆 + 可审计动作 + 可复现实物体验”，不是一开始就追最重的通用机器人大模型。
