import { C, slideBase, kicker, title, footer, line, body, label, node } from "./shared.mjs";

export async function slide04(presentation, ctx) {
  const slide = slideBase(presentation, ctx, "light");
  kicker(slide, ctx, "DEMO SCRIPT", "light");
  title(slide, ctx, "路演开场 20 秒：角色记得你，并用身体回应。", "light", 56, 82, 900, 38);
  const y = 306;
  line(slide, ctx, 112, y + 42, 1014, 4, "#D6CEC2");
  const steps = [
    ["01", "用户进入", "摄像/触摸/语音触发，设备进入陪伴状态。", C.red],
    ["02", "读取关系", "角色知道上次互动、称呼、偏好和当前关系阶段。", C.cyan],
    ["03", "生成情绪", "PAD 决定语速、语气、LED 颜色和动作强度。", C.yellow],
    ["04", "实体回应", "先抬头/眨眼/轻振，再用角色声音说一句短话。", C.violet],
  ];
  steps.forEach((s, i) => {
    const x = 94 + i * 284;
    ctx.addShape(slide, { x, y, w: 84, h: 84, fill: s[3], geometry: "ellipse" });
    ctx.addText(slide, { text: s[0], x: x + 18, y: y + 25, w: 48, h: 28, fontSize: 23, color: i === 2 ? C.ink : C.white, bold: true, align: "center", typeface: "Aptos Display" });
    label(slide, ctx, s[1], x - 18, y + 112, 120, C.ink, 17, true);
    body(slide, ctx, s[2], x - 44, y + 146, 176, 72, "#4A4640", 12);
  });
  node(slide, ctx, "示例台词：\n“你今天回来比昨天晚一点。先别急着说话，我陪你坐一会儿。”", 220, 565, 840, 72, C.ink, C.bone, 16);
  footer(slide, ctx, "Demo-first pitch");
  return slide;
}
