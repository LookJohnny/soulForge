import { C, slideBase, kicker, title, subtitle, footer, block, body, line } from "./shared.mjs";

export async function slide03(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "dark");
  kicker(slide, ctx, "VALIDATED SOFTWARE LOOP", "dark");
  title(slide, ctx, "已验证的是软件陪伴管线，不是仿生脸量产。", "dark", 56, 82, 920, 38);
  subtitle(slide, ctx, "这条边界讲清楚，反而更可信：SoulForge 现在证明的是角色大脑和设备协议，下一阶段才购买机电样机能力。", "dark", 58, 174, 870, 15);
  const cards = [
    ["VERBAL 角色", "角色创建成功；/api/preview 返回 dialogue、action、thought、emotion 和多段 MP3。", C.red],
    ["VOCALIZED 模式", "非语言角色输出被限制在拟声词 palette 内，同时保留 thought、action 和情绪。", C.cyan],
    ["Fish Audio 克隆", "公开 WAV URL 克隆成功，生成 voice profile 并绑定角色，日志可追踪 voice_resolved。", C.yellow],
    ["硬件动作字段", "PAD 到 LED / motor / vibration 映射可输出；企鹅高 P/A 返回 waddle，doro 返回 wiggle。", C.green],
  ];
  cards.forEach((c, i) => {
    const x = 72 + (i % 2) * 560;
    const y = 298 + Math.floor(i / 2) * 142;
    block(slide, ctx, { x, y, w: 500, h: 108, fill: "#23211E", line: "#3A342F", accent: c[2], mode: "dark", title: c[0], text: c[1] });
  });
  line(slide, ctx, 110, 598, 1060, 2, "#4A433D");
  body(slide, ctx, "融资叙事：用已跑通的软件链路去支撑第一台低风险实体样机，而不是现在就声称拥有完整表情机器人能力。", 132, 616, 1010, 34, C.bone, 15, true);
  footer(slide, ctx, "Internal smoke evidence, April 2026");
  return slide;
}
