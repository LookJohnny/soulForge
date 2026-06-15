import { C, slideBase, kicker, title, subtitle, footer, block, sourceNote } from "./shared.mjs";

export async function slide02(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "light");
  kicker(slide, ctx, "WHY NOW", "light");
  title(slide, ctx, "IP 的情绪价值还停在屏幕和静态周边里。", "light", 56, 82, 860, 38);
  subtitle(slide, ctx, "用户愿意为角色买单，但现有消费载体大多只能收藏、观看或短时互动，缺少长期陪伴关系。", "light", 58, 174, 820, 16);
  block(slide, ctx, {
    x: 70, y: 284, w: 330, h: 226, fill: C.bone, line: C.line, accent: C.red, mode: "light",
    title: "静态潮玩",
    text: "有收藏价值和身份表达，但角色不会认识用户，也不会在日常生活里回应。"
  });
  block(slide, ctx, {
    x: 474, y: 284, w: 330, h: 226, fill: C.bone, line: C.line, accent: C.cyan, mode: "light",
    title: "普通 AI 玩具",
    text: "能聊天，但体验常退回泛问答；角色语气、声音、记忆和身体反应不稳定。"
  });
  block(slide, ctx, {
    x: 878, y: 284, w: 330, h: 226, fill: C.ink, line: C.ink, accent: C.yellow, mode: "dark",
    title: "SoulForge",
    text: "先把角色一致性跑通，再接入实体硬件，让用户感觉面对的是“同一个角色”。"
  });
  sourceNote(slide, ctx, "行业信号：AI 玩具与潮玩融合热度上升，但公开讨论同时集中在延迟、互动浅、售后和产品生命周期风险。", "light");
  footer(slide, ctx, "Problem");
  return slide;
}
