import { C, slideBase, kicker, title, subtitle, footer, body, label, line } from "./shared.mjs";

export async function slide08(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "light");
  kicker(slide, ctx, "MARKET WEDGE", "light");
  title(slide, ctx, "先打愿意为角色生命感付费的人，而不是泛儿童市场。", "light", 56, 82, 960, 36);
  subtitle(slide, ctx, "儿童玩具会带来更重的安全、渠道和售后要求；早期更适合用 IP 粉丝和潮玩用户验证情绪价值。", "light", 58, 174, 900, 15);
  const headers = ["首批人群", "购买动机", "验证方式", "首款打法"];
  const xs = [72, 300, 590, 890];
  const ws = [190, 250, 250, 270];
  headers.forEach((h, i) => label(slide, ctx, h, xs[i], 276, ws[i], C.ink, 12, true));
  line(slide, ctx, 68, 304, 1110, 2, "#D4CABE");
  const rows = [
    ["二次元/游戏 IP 粉丝", "想把喜爱的角色带到现实", "社群预约、Demo 转发、预售转化", "限定角色样机"],
    ["潮玩收藏用户", "情绪价值、稀缺感、可展示", "盲盒/手办消费能力、线下渠道触达", "静态收藏升级"],
    ["情感陪伴用户", "低压力陪伴、日常在场感", "互动时长、7/30 日留存、订阅转化", "轻语言 companion"],
  ];
  rows.forEach((r, row) => {
    const y = 334 + row * 88;
    ctx.addShape(slide, { x: 64, y: y - 18, w: 1120, h: 70, fill: row === 1 ? C.bone : "#EFE7DA" });
    r.forEach((cell, i) => body(slide, ctx, cell, xs[i], y, ws[i], 44, i === 0 ? C.ink : "#4A4640", i === 0 ? 14 : 12.2, i === 0));
  });
  body(slide, ctx, "扩展路径：IP 粉丝验证情绪价值 → 礼品/潮玩渠道放量 → 儿童陪伴和教育场景分阶段进入。", 112, 598, 1040, 34, C.ink, 16, true);
  footer(slide, ctx, "Initial ICP");
  return slide;
}
