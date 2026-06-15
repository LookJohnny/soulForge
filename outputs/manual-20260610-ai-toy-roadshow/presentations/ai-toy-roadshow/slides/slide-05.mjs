import { C, slideBase, kicker, title, subtitle, footer, body, label, line, node } from "./shared.mjs";

export async function slide05(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "dark");
  kicker(slide, ctx, "FIRST PRODUCT", "dark");
  title(slide, ctx, "第一台样机先做“可信陪伴体”，不硬冲高自由度仿生脸。", "dark", 56, 82, 980, 36);
  subtitle(slide, ctx, "先把角色声音、记忆和低风险身体反馈做扎实，再逐步升级到眼睑、嘴型和多轴表情。", "dark", 58, 174, 850, 15);
  const tiers = [
    ["Basic", "$5-10\n电子 BOM", "声音 + LED + 震动\n低成本验证陪伴感", C.red],
    ["Mid", "$15-25\n电子 BOM", "ESP32-S3 + RGB 眼睛\n1 个头部舵机 + 触摸", C.cyan],
    ["Full", "$40-60\n电子 BOM", "2 轴头部 + 手臂\nLED matrix + 多触点", C.yellow],
  ];
  tiers.forEach((t, i) => {
    const x = 116 + i * 350;
    node(slide, ctx, t[0], x, 300, 120, 46, t[3], t[3] === C.yellow ? C.ink : C.white, 17);
    ctx.addShape(slide, { x, y: 360, w: 270, h: 162, fill: "#24221F", line: ctx.line("#3A342F", 1) });
    body(slide, ctx, t[1], x + 20, 388, 96, 58, t[3], 21, true);
    body(slide, ctx, t[2], x + 128, 394, 118, 78, "#D9D1C7", 12.5);
  });
  line(slide, ctx, 132, 574, 1010, 2, "#4A433D");
  label(slide, ctx, "样机策略", 132, 598, 80, C.yellow, 14, true);
  body(slide, ctx, "路演演示优先选择 Mid Tier：足够体现“活着”，同时不把资金消耗在高风险仿生脸机构。", 222, 596, 840, 30, C.bone, 15, true);
  footer(slide, ctx, "Hardware tiering from SoulForge integration docs");
  return slide;
}
