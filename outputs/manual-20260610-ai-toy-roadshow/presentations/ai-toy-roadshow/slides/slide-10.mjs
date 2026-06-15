import { C, slideBase, kicker, title, subtitle, footer, body, label, line, sourceNote } from "./shared.mjs";

export async function slide10(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "light");
  kicker(slide, ctx, "COMPETITION", "light");
  title(slide, ctx, "现有方案通常只解决语音、静态周边或高价仿生中的一部分。", "light", 56, 82, 1030, 34);
  subtitle(slide, ctx, "SoulForge 的目标位不是“没有竞品”，而是把角色一致性、长期记忆和可量产实体表达同时做出来。", "light", 58, 174, 920, 15);
  const x0 = 154, y0 = 260, w = 860, h = 320;
  ctx.addShape(slide, { x: x0, y: y0, w, h, fill: C.bone, line: ctx.line("#D4CABE", 1) });
  line(slide, ctx, x0 + w / 2, y0, 2, h, "#D4CABE");
  line(slide, ctx, x0, y0 + h / 2, w, 2, "#D4CABE");
  label(slide, ctx, "角色/IP 一致性 →", x0 + w - 160, y0 + h + 18, 160, "#655E55", 11, true);
  label(slide, ctx, "实体表达深度 ↑", x0 - 82, y0 - 22, 120, "#655E55", 11, true);
  const points = [
    ["普通对话盒子", 244, 500, "#8B8177"],
    ["AI 毛绒 / Fuzozo 类", 432, 446, C.cyan],
    ["高价仿生机器人", 542, 318, C.violet],
    ["SoulForge 目标位", 782, 318, C.red],
    ["静态潮玩/IP 周边", 792, 520, C.yellow],
  ];
  points.forEach((p) => {
    ctx.addShape(slide, { x: p[1], y: p[2], w: 18, h: 18, fill: p[3], geometry: "ellipse" });
    body(slide, ctx, p[0], p[1] + 24, p[2] - 3, 178, 22, C.ink, 11.5, p[0].startsWith("SoulForge"));
  });
  sourceNote(slide, ctx, "竞品位置为基于公开资料和产品形态的定性判断，后续以用户访谈和样机对比持续校准。", "light");
  footer(slide, ctx, "Competitive position");
  return slide;
}
