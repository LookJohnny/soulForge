import { C, slideBase, kicker, title, subtitle, footer, body, label, line, sourceNote } from "./shared.mjs";

export async function slide09(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "dark");
  kicker(slide, ctx, "BUSINESS MODEL", "dark");
  title(slide, ctx, "硬件负责入口，订阅和内容负责复购。", "dark", 56, 82, 820, 38);
  subtitle(slide, ctx, "早期融资看的是毛利可行性和留存，不是总市场故事。", "dark", 58, 174, 720, 16);
  const items = [
    ["硬件", "首台 Mid Tier 样机\n目标证明可量产结构", C.red],
    ["订阅", "长期记忆、云端模型\n角色成长线与多设备同步", C.cyan],
    ["IP 分成", "授权角色、声音\n官方内容包与活动", C.yellow],
    ["内容包", "节日剧情、动作\n音色与限定互动", C.violet],
  ];
  items.forEach((it, i) => {
    const x = 82 + i * 292;
    ctx.addShape(slide, { x, y: 310, w: 230, h: 148, fill: i === 2 ? C.yellow : "#24221F", line: ctx.line(i === 2 ? C.yellow : "#3A342F", 1) });
    body(slide, ctx, it[0], x + 18, 332, 190, 24, i === 2 ? C.ink : it[2], 18, true);
    body(slide, ctx, it[1], x + 18, 374, 190, 60, i === 2 ? "#3D382F" : "#D9D1C7", 12);
  });
  line(slide, ctx, 106, 532, 1056, 2, "#4A433D");
  label(slide, ctx, "早期核心指标", 106, 558, 130, C.yellow, 13, true);
  body(slide, ctx, "预售转化、激活率、7/30 日留存、订阅转化、退货率、单台售后成本。", 250, 556, 820, 26, C.bone, 15, true);
  sourceNote(slide, ctx, "硬件 BOM 口径仅指电子部分；最终 COGS 还包括外观件、毛绒/塑胶、装配、包装、物流和售后。", "dark");
  footer(slide, ctx, "Revenue model and unit economics focus");
  return slide;
}
