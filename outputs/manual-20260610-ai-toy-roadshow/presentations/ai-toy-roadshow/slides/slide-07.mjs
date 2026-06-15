import { C, slideBase, kicker, title, subtitle, footer, body, label, line, block } from "./shared.mjs";

export async function slide07(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "dark");
  kicker(slide, ctx, "IP GOVERNANCE", "dark");
  title(slide, ctx, "IP 授权的关键不是“能说话”，而是“不会乱说话”。", "dark", 56, 82, 960, 36);
  subtitle(slide, ctx, "角色自由生成内容会放大版权方风险，因此 SoulForge 的 IP 接入把可控性做成产品能力。", "dark", 58, 174, 860, 15);
  const rows = [
    ["人设边界", "角色模板、禁用话题、不可破壁规则和官方语气样例。", C.red],
    ["输出约束", "非语言模式、短句模式、白名单音效、危险内容拦截。", C.cyan],
    ["记忆策略", "敏感记忆分层、确认机制、儿童场景屏蔽和审计日志。", C.yellow],
    ["商业接口", "授权分成、内容包审核、灰度发布和数据回传。", C.green],
  ];
  rows.forEach((r, i) => {
    const y = 300 + i * 78;
    block(slide, ctx, { x: 104, y, w: 1020, h: 58, fill: "#23211E", line: "#3A342F", accent: r[2], mode: "dark", title: r[0], text: r[1] });
  });
  line(slide, ctx, 108, 634, 1010, 2, "#4A433D");
  label(slide, ctx, "对 IP 方的卖点", 110, 646, 140, C.yellow, 12, true);
  body(slide, ctx, "不是把角色交给黑盒模型，而是把角色输出放进可审核、可降级、可追责的系统。", 260, 642, 800, 24, C.bone, 14, true);
  footer(slide, ctx, "IP risk control");
  return slide;
}
