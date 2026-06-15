import { C, slideBase, kicker, title, subtitle, footer, block, body, label, line } from "./shared.mjs";

export async function slide11(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "dark");
  kicker(slide, ctx, "TEAM", "dark");
  title(slide, ctx, "种子轮投人：AI 产品先跑通，硬件和 IP 进入合伙人网络。", "dark", 56, 82, 980, 36);
  subtitle(slide, ctx, "早期团队的可信度来自已经跑通的系统、清晰的能力边界，以及对机电、供应链、IP BD 的明确分工。", "dark", 58, 174, 860, 15);
  block(slide, ctx, {
    x: 82, y: 300, w: 330, h: 188, fill: "#24221F", line: "#3A342F", accent: C.red, mode: "dark",
    title: "AI 产品 / 全栈工程",
    text: "SoulForge 核心系统 owner：persona、memory、TTS、gateway、admin web 和端到端 smoke。"
  });
  block(slide, ctx, {
    x: 476, y: 300, w: 330, h: 188, fill: "#24221F", line: "#3A342F", accent: C.cyan, mode: "dark",
    title: "硬件 / 供应链网络",
    text: "资金投向机电、ID、打样、BOM、装配和可靠性验证，形成 EVT 样机交付能力。"
  });
  block(slide, ctx, {
    x: 870, y: 300, w: 330, h: 188, fill: "#24221F", line: "#3A342F", accent: C.yellow, mode: "dark",
    title: "IP / 内容 / 渠道网络",
    text: "BD 围绕授权风控、角色审核、限定预售和社群冷启动，不依赖先拿头部 IP。"
  });
  line(slide, ctx, 110, 574, 1060, 2, "#4A433D");
  label(slide, ctx, "下一轮前团队目标", 110, 598, 150, C.yellow, 12, true);
  body(slide, ctx, "补齐机电/供应链 owner、IP BD owner 和首批渠道资源，让团队从软件验证进入实体交付。", 276, 594, 820, 28, C.bone, 14, true);
  footer(slide, ctx, "Team and capability boundary");
  return slide;
}
