import { C, slideBase, kicker, title, subtitle, footer, metric, productHead, pill, body } from "./shared.mjs";

export async function slide01(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "dark");
  kicker(slide, ctx, "ANGEL+ FINANCING DECK", "dark");
  title(slide, ctx, "SoulForge：把 AI 角色装进真实玩具身体", "dark", 56, 90, 760, 42);
  subtitle(slide, ctx, "已跑通软件陪伴管线，下一阶段用天使+融资交付可录屏样机、硬件 BOM 和首批种子用户数据。", "dark", 58, 212, 730, 18);
  productHead(slide, ctx, 886, 128, 1.03);
  ctx.addShape(slide, { x: 826, y: 452, w: 340, h: 3, fill: C.red });
  pill(slide, ctx, "AI companion for IP characters", 852, 474, 288, C.yellow);
  body(slide, ctx, "不是“会说话的毛绒”，而是角色人格、声音、记忆、情绪和硬件表达的一体化系统。", 820, 540, 360, 54, "#DDD4C7", 14, true);
  metric(slide, ctx, "500-800万", "本轮融资额", 58, 514, 210, C.red);
  metric(slide, ctx, "9-12个月", "资金覆盖周期", 292, 514, 210, C.cyan);
  metric(slide, ctx, "Demo+BOM", "下一轮前核心交付", 526, 514, 210, C.yellow);
  footer(slide, ctx, "SoulForge / AI 潮玩天使轮路演修正版");
  return slide;
}
