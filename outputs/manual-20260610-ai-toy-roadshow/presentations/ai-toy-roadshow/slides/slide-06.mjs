import { C, slideBase, kicker, title, subtitle, footer, block, body, line } from "./shared.mjs";

export async function slide06(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "light");
  kicker(slide, ctx, "CHARACTER CONSISTENCY STACK", "light");
  title(slide, ctx, "产品壁垒来自角色一致性，而不是单个记忆或 TTS 功能。", "light", 56, 82, 940, 36);
  subtitle(slide, ctx, "五层记忆、PAD、音色和硬件映射单独看都是 feature；连成闭环后，才是用户感知到的“这是同一个角色”。", "light", 58, 174, 900, 15);
  const blocks = [
    ["Persona", "角色设定、称呼、语气和不破壁规则", C.red],
    ["Memory", "identity / preference / event / relationship / private_state", C.cyan],
    ["Policy", "敏感信息、儿童安全、确认、审计、软删除", C.yellow],
    ["Emotion", "PAD 连续情绪驱动声音和硬件输出", C.violet],
    ["Body", "LED / motor / vibration 按硬件等级降级表达", C.green],
  ];
  blocks.forEach((b, i) => {
    const x = 86 + i * 228;
    block(slide, ctx, { x, y: 318, w: 184, h: 168, fill: i === 0 ? C.ink : C.bone, line: C.line, accent: b[2], mode: i === 0 ? "dark" : "light", title: b[0], text: b[1] });
    if (i < blocks.length - 1) line(slide, ctx, x + 184, 402, 44, 3, "#BFB6AA");
  });
  body(slide, ctx, "投资逻辑：先用可验证体验拿到留存，再把 IP 授权、供应链成本和互动数据沉淀成真正的防御。", 150, 574, 980, 42, C.ink, 17, true);
  footer(slide, ctx, "Technology as experience, not feature list");
  return slide;
}
