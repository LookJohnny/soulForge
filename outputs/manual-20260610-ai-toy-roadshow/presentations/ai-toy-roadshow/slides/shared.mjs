export const C = {
  ink: "#121110",
  ink2: "#1C1B1A",
  paper: "#F7F1E6",
  bone: "#FFF9EE",
  muted: "#C8C0B5",
  smoke: "#6F6A63",
  line: "#DDD4C7",
  red: "#FF5A47",
  cyan: "#20C9B8",
  yellow: "#FFD166",
  blue: "#4E7CFF",
  violet: "#8D7CFF",
  green: "#65D46E",
  white: "#FFFFFF",
};

export function slideBase(presentation, ctx, mode = "dark") {
  const slide = presentation.slides.add();
  const bg = mode === "dark" ? C.ink : C.paper;
  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: ctx.H, fill: bg });
  return slide;
}

export function footer(slide, ctx, text = "") {
  const color = text ? (isDark(slide) ? "#AFA79D" : "#78716C") : "#78716C";
  ctx.addText(slide, {
    text,
    x: 56,
    y: 674,
    w: 980,
    h: 20,
    fontSize: 10,
    color,
    typeface: "PingFang SC",
  });
  ctx.addText(slide, {
    text: String(ctx.slideNumber).padStart(2, "0"),
    x: 1188,
    y: 668,
    w: 38,
    h: 24,
    fontSize: 12,
    color,
    align: "right",
    typeface: "Aptos",
  });
}

function isDark(_slide) {
  return true;
}

export function kicker(slide, ctx, text, mode = "dark", x = 56, y = 42) {
  const fill = mode === "dark" ? C.red : C.ink;
  const color = mode === "dark" ? C.paper : C.ink;
  ctx.addShape(slide, { x, y: y + 8, w: 26, h: 3, fill });
  ctx.addText(slide, {
    text,
    x: x + 40,
    y,
    w: 520,
    h: 22,
    fontSize: 11,
    color,
    bold: true,
    typeface: "Aptos",
  });
}

export function title(slide, ctx, text, mode = "dark", x = 56, y = 82, w = 760, size = 38) {
  ctx.addText(slide, {
    text,
    x,
    y,
    w,
    h: size * 2.3,
    fontSize: size,
    color: mode === "dark" ? C.bone : C.ink,
    bold: true,
    typeface: "PingFang SC",
  });
}

export function subtitle(slide, ctx, text, mode = "dark", x = 58, y = 178, w = 680, size = 17) {
  ctx.addText(slide, {
    text,
    x,
    y,
    w,
    h: 72,
    fontSize: size,
    color: mode === "dark" ? "#D9D1C7" : "#433F3A",
    typeface: "PingFang SC",
  });
}

export function label(slide, ctx, text, x, y, w, color = C.smoke, size = 11, bold = false) {
  ctx.addText(slide, {
    text,
    x,
    y,
    w,
    h: 18,
    fontSize: size,
    color,
    bold,
    typeface: "PingFang SC",
  });
}

export function body(slide, ctx, text, x, y, w, h, color = "#E7DED2", size = 16, bold = false) {
  ctx.addText(slide, {
    text,
    x,
    y,
    w,
    h,
    fontSize: size,
    color,
    bold,
    typeface: "PingFang SC",
  });
}

export function block(slide, ctx, { x, y, w, h, fill = "#211F1D", line = "#00000000", title: t, text, accent = C.red, mode = "dark" }) {
  ctx.addShape(slide, { x, y, w, h, fill, line: ctx.line(line, line === "#00000000" ? 0 : 1) });
  ctx.addShape(slide, { x, y, w: 4, h, fill: accent });
  if (t) {
    body(slide, ctx, t, x + 20, y + 18, w - 34, 24, mode === "dark" ? C.bone : C.ink, 17, true);
  }
  if (text) {
    body(slide, ctx, text, x + 20, y + 52, w - 36, h - 58, mode === "dark" ? "#D8D0C5" : "#4A4640", 13);
  }
}

export function pill(slide, ctx, text, x, y, w, fill, color = C.ink) {
  ctx.addShape(slide, { x, y, w, h: 28, fill, line: ctx.line("#00000000", 0) });
  ctx.addText(slide, {
    text,
    x: x + 12,
    y: y + 6,
    w: w - 24,
    h: 16,
    fontSize: 10,
    color,
    bold: true,
    align: "center",
    typeface: "PingFang SC",
  });
}

export function metric(slide, ctx, value, labelText, x, y, w, accent = C.red, mode = "dark") {
  ctx.addShape(slide, { x, y, w, h: 86, fill: mode === "dark" ? "#1F1E1C" : C.bone, line: ctx.line(mode === "dark" ? "#3A342F" : C.line, 1) });
  ctx.addText(slide, { text: value, x: x + 16, y: y + 14, w: w - 32, h: 30, fontSize: 26, color: accent, bold: true, typeface: "Aptos Display" });
  ctx.addText(slide, { text: labelText, x: x + 16, y: y + 50, w: w - 32, h: 22, fontSize: 12, color: mode === "dark" ? "#CFC6BB" : "#5B554E", typeface: "PingFang SC" });
}

export function line(slide, ctx, x, y, w, h = 1, fill = C.line) {
  ctx.addShape(slide, { x, y, w, h, fill });
}

export function node(slide, ctx, text, x, y, w, h, fill, color = C.ink, size = 14) {
  ctx.addShape(slide, { x, y, w, h, fill, line: ctx.line("#00000000", 0) });
  ctx.addText(slide, {
    text,
    x: x + 12,
    y: y + 12,
    w: w - 24,
    h: h - 20,
    fontSize: size,
    color,
    bold: true,
    valign: "mid",
    align: "center",
    typeface: "PingFang SC",
  });
}

export function sourceNote(slide, ctx, text, mode = "dark") {
  ctx.addText(slide, {
    text,
    x: 56,
    y: 646,
    w: 1080,
    h: 18,
    fontSize: 9,
    color: mode === "dark" ? "#8F877D" : "#8A8178",
    typeface: "PingFang SC",
  });
}

export function productHead(slide, ctx, x, y, scale = 1) {
  const w = 210 * scale;
  const h = 270 * scale;
  ctx.addShape(slide, { x, y, w, h, fill: "#EDE4D7", line: ctx.line("#5A524B", 2), geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 38 * scale, y: y + 92 * scale, w: 42 * scale, h: 48 * scale, fill: C.ink, geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 130 * scale, y: y + 92 * scale, w: 42 * scale, h: 48 * scale, fill: C.ink, geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 53 * scale, y: y + 108 * scale, w: 12 * scale, h: 12 * scale, fill: C.cyan, geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 145 * scale, y: y + 108 * scale, w: 12 * scale, h: 12 * scale, fill: C.cyan, geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 84 * scale, y: y + 172 * scale, w: 42 * scale, h: 12 * scale, fill: C.red, geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 21 * scale, y: y + 158 * scale, w: 36 * scale, h: 20 * scale, fill: "#F3A2A1", geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 154 * scale, y: y + 158 * scale, w: 36 * scale, h: 20 * scale, fill: "#F3A2A1", geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 22 * scale, y: y - 26 * scale, w: 48 * scale, h: 80 * scale, fill: "#EDE4D7", line: ctx.line("#5A524B", 2), geometry: "ellipse" });
  ctx.addShape(slide, { x: x + 140 * scale, y: y - 26 * scale, w: 48 * scale, h: 80 * scale, fill: "#EDE4D7", line: ctx.line("#5A524B", 2), geometry: "ellipse" });
}
