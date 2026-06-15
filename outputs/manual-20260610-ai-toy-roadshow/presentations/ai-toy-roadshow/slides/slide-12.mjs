import { C, slideBase, kicker, title, subtitle, footer, block, body, label, line } from "./shared.mjs";

export async function slide12(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "light");
  kicker(slide, ctx, "FINANCING ASK", "light");
  title(slide, ctx, "本轮融资 500-800 万人民币，交付可被投资人复核的样机证据。", "light", 56, 82, 1040, 34);
  subtitle(slide, ctx, "1500-2500 万机构种子轮放到下一阶段：样机、IP 意向和预售/留存数据出现后再谈。", "light", 58, 174, 900, 15);
  block(slide, ctx, {
    x: 80, y: 282, w: 520, h: 190, fill: C.ink, line: C.ink, accent: C.red, mode: "dark",
    title: "天使+：500-800 万",
    text: "9-12 个月资金周期。用于完成可录屏 Mid Tier 样机、BOM/COGS 口径、首批用户测试和可谈判 IP/渠道线索。"
  });
  block(slide, ctx, {
    x: 680, y: 282, w: 520, h: 190, fill: C.bone, line: C.line, accent: C.cyan, mode: "light",
    title: "下一轮触发条件",
    text: "样机视频可复现；100-300 名种子用户；7/30 日留存与订阅意愿；至少 1 条 IP 或渠道 LOI；退货/售后风险有数据口径。"
  });
  label(slide, ctx, "资金用途", 88, 530, 100, C.ink, 15, true);
  const uses = [
    ["硬件/供应链 35%", 0.35, C.red],
    ["AI/云/TTS 25%", 0.25, C.cyan],
    ["IP/内容 15%", 0.15, C.yellow],
    ["内测/GTM 15%", 0.15, C.violet],
    ["法务/缓冲 10%", 0.10, C.green],
  ];
  let x = 196;
  uses.forEach((u) => {
    const w = 760 * u[1];
    ctx.addShape(slide, { x, y: 532, w, h: 30, fill: u[2] });
    body(slide, ctx, u[0], x + 8, 568, w + 34, 18, C.ink, 9.5, true);
    x += w;
  });
  line(slide, ctx, 88, 622, 1040, 2, "#D4CABE");
  body(slide, ctx, "投资人看到的终局不是 PPT：是可以现场演示、可以拆 BOM、可以拿给 100 个用户测试的第一台角色实体。", 98, 642, 1000, 28, C.ink, 14.5, true);
  footer(slide, ctx, "Angel+ financing plan");
  return slide;
}
