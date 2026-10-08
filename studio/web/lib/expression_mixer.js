/* 表情混合器（纯逻辑，无 three 依赖，node 可测）。

   三件事：
   1. 直接表情输入：Nous Tone 读数给出的连续表情权重（每句一条 cue），绕过 PAD 的
      13 配方量化；cue 与 PAD 配方表情按 blend 线性混合，之后仍走 VrmBody 的逐帧阻尼。
      PAD 继续驱动头姿 / 眨眼 / 目光。
   2. 说话时让位只针对嘴：旧逻辑说话时把整张脸 ×0.45；现在按"该表情有多少落在嘴上"
      逐通道让位（VRoid 可拆分时：眉/眼满值、只有嘴部分 ×0.45）。
   3. 按模型通道映射：模型缺的通道换成近似通道（warmth/relaxed → 浅一点的 happy），
      实在表达不了的通道交给头姿（一张错的脸比没有表情更糟）。 */

import { EXPR_CHANNELS, RECIPE_PRESETS } from './pad_expression.js';

export const MOUTH_SPEAKING_GAIN = 0.45; // 说话时嘴部情绪形变的保留比例（视素优先）
export const BLEND_IN = 5;               // cue 接管速率 (1/s)
export const BLEND_OUT = 1.2;            // cue 过期后交还 PAD 的速率 (1/s)，慢一点免得"啪"地收脸
export const SPLIT_RESIDUAL_MAX = 0.02;  // ‖ALL − (BRW+EYE+MTH)‖² / ‖ALL‖² 低于此才按部位拆分

const clamp01 = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0);
const damp = (cur, target, lambda, dt) => cur + (target - cur) * (1 - Math.exp(-lambda * dt));

/* 缺失通道的替身：按顺序取第一个模型有的通道。surprised/sad/angry 没有安全替身 → 交给头姿。 */
export const CHANNEL_FALLBACKS = {
  relaxed: [['happy', 0.5]],
  happy: [['relaxed', 1.0]],
  surprised: [],
  sad: [],
  angry: [],
};

/* 模型给这句台词声明的情绪（dialogue[].emotion，自由文本）→ 表情先验。
   读数分不出语气的那部分（neutral 份额）显示它；没有声明时才回落到 PAD 心情。 */
export const DECLARED_EMOTIONS = {
  happy: { happy: 0.6 }, joy: { happy: 0.6 }, excited: { happy: 0.7, surprised: 0.2 }, playful: { happy: 0.5 },
  cheerful: { happy: 0.6 }, proud: { happy: 0.5 }, delighted: { happy: 0.7 },
  warm: { relaxed: 0.5, happy: 0.2 }, caring: { relaxed: 0.5 }, gentle: { relaxed: 0.45 }, affectionate: { relaxed: 0.5, happy: 0.2 },
  friendly: { happy: 0.35, relaxed: 0.2 }, calm: { relaxed: 0.25 }, relaxed: { relaxed: 0.4 }, shy: { happy: 0.3, relaxed: 0.3 },
  sad: { sad: 0.6 }, sorrow: { sad: 0.6 }, worried: { sad: 0.4 }, sorry: { sad: 0.35 }, lonely: { sad: 0.5 }, hurt: { sad: 0.5 },
  angry: { angry: 0.6 }, annoyed: { angry: 0.4 }, frustrated: { angry: 0.35, sad: 0.15 },
  surprised: { surprised: 0.6 }, curious: { surprised: 0.25, happy: 0.1 },
};

const VALENCE = { happy: 1, relaxed: 1, sad: -1, angry: -1, surprised: 0 };
export const CONFLICT_KEEP = 0.3;        // 读数与声明情绪效价相反时，读数只保留 30%（其余并入 neutral）
export const CONFLICT_MAX_WEIGHT = 0.9;  // 但非常确定的读数（权重 ≥0.9，约 p≥0.7）照常采信

/** 声明情绪 → 先验权重（大小写/中文常见词兼容）；不认识返回 null。 */
export function declaredPrior(label) {
  if (typeof label !== 'string') return null;
  const k = label.trim().toLowerCase();
  const zh = { 开心: 'happy', 高兴: 'happy', 兴奋: 'excited', 温柔: 'gentle', 温暖: 'warm', 关心: 'caring', 平静: 'calm',
    难过: 'sad', 伤心: 'sad', 担心: 'worried', 生气: 'angry', 惊讶: 'surprised', 好奇: 'curious', 害羞: 'shy' };
  return DECLARED_EMOTIONS[k] ?? DECLARED_EMOTIONS[zh[label.trim()]] ?? null;
}

/* 表达不了的通道 → 头姿 / 目光（取自同情绪的 PAD 配方，保证与 PAD 路径同一套身体语言）。 */
const HEAD_RECIPE = { happy: 'warm_smile', relaxed: 'rest', surprised: 'surprised', sad: 'down', angry: 'stern' };

/** has(channel) → {map: {k: [[target, scale]]}, missing, fallbacks, support: 'full'|'partial'|'none'} */
export function planChannels(has) {
  const map = {}, missing = [], fallbacks = {};
  for (const k of EXPR_CHANNELS) {
    if (has(k)) { map[k] = [[k, 1]]; continue; }
    missing.push(k);
    const alt = (CHANNEL_FALLBACKS[k] ?? []).find(([t]) => has(t));
    map[k] = alt ? [alt] : [];
    if (alt) fallbacks[k] = `${alt[0]}×${alt[1]}`;
  }
  const native = EXPR_CHANNELS.length - missing.length;
  return { map, missing, fallbacks, support: missing.length === 0 ? 'full' : native ? 'partial' : 'none' };
}

/** 情绪权重 → 本模型可显示的通道权重（替身按 max 合并，不叠加超 1）。 */
export function mapWeights(weights, plan) {
  const out = Object.fromEntries(EXPR_CHANNELS.map((k) => [k, 0]));
  for (const k of EXPR_CHANNELS) {
    const v = clamp01(weights?.[k]);
    if (!v) continue;
    for (const [t, s] of plan.map[k]) out[t] = Math.max(out[t], v * s);
  }
  return out;
}

/** 本模型显示不了的那部分情绪 → 头姿/目光偏移（按权重加权 RECIPE 头姿）。 */
export function unshownHead(weights, plan) {
  let x = 0, y = 0, z = 0, gy = 0, sum = 0;
  for (const k of EXPR_CHANNELS) {
    if (plan.map[k].length) continue;
    const v = clamp01(weights?.[k]);
    if (!v) continue;
    const r = RECIPE_PRESETS[HEAD_RECIPE[k]];
    x += v * r.head.x; y += v * r.head.y; z += v * r.head.z; gy += v * (r.gaze?.y ?? 0); sum += v;
  }
  const n = Math.max(1, sum); // 权重和 <1 时按强度缩放，>1 时归一
  return { x: x / n, y: y / n, z: z / n, gazeY: gy / n, amount: Math.min(1, sum) };
}

/** 说话时整通道（不可拆分）的让位系数：只按嘴部占比让位。mouthShare 未知时按 1（旧行为）。 */
export function speakingGain(mouthShare, speakingAmt) {
  const m = mouthShare == null ? 1 : clamp01(mouthShare);
  return 1 - (1 - MOUTH_SPEAKING_GAIN) * m * clamp01(speakingAmt);
}

/** [‖all − Σparts‖², ‖all‖²]（Float32Array 形变 delta，长度一致）；多个图元可累加后再相除。 */
export function residualSums(all, parts) {
  let num = 0, den = 0;
  for (let i = 0; i < all.length; i++) {
    let s = 0;
    for (const p of parts) s += p[i];
    const r = all[i] - s;
    num += r * r; den += all[i] * all[i];
  }
  return [num, den];
}

export function residualRatio(all, parts) {
  const [num, den] = residualSums(all, parts);
  return den > 0 ? num / den : Infinity;
}

/** 形变能量落在嘴部区域（mask[v]=1 的顶点）的比例；delta 为 xyz 交错。 */
export function regionShare(delta, mask) {
  let inMask = 0, total = 0;
  for (let v = 0; v < mask.length; v++) {
    const e = delta[3 * v] ** 2 + delta[3 * v + 1] ** 2 + delta[3 * v + 2] ** 2;
    total += e;
    if (mask[v]) inMask += e;
  }
  return total > 0 ? inMask / total : 0;
}

/** 一句话的直接表情目标：hold 秒内接管，过期后慢慢交还 PAD。 */
export class ExpressionCue {
  constructor() {
    this.weights = null;
    this.neutral = 0;      // 读数里"没有特定语气"的份额：显示声明情绪先验，没有则显示 PAD 心情
    this.prior = null;     // 这句台词的声明情绪先验（DECLARED_EMOTIONS）
    this.until = -Infinity;
    this.blend = 0;
    this.meta = null;
  }

  /** weights: {happy, sad, angry, surprised, relaxed, neutral?}（0..1）。neutral 缺省为 1−max。 */
  set(weights, { now, hold = Infinity, meta = null, declared = null } = {}) {
    const w = {};
    for (const k of EXPR_CHANNELS) w[k] = clamp01(weights?.[k]);
    this.weights = w;
    this.neutral = typeof weights?.neutral === 'number' ? clamp01(weights.neutral) : 1 - Math.max(...Object.values(w));
    this.prior = declaredPrior(declared);
    this.conflict = false;
    // 一致性闸门：读数最强的通道与台词声明情绪效价相反（如"好开心啊"读成 sad），
    // 两个独立信号打架时不信读数——它在短句上最常见的错误正是效价翻转。
    if (this.prior) {
      const pv = Math.sign(Object.entries(this.prior).reduce((s, [k, v]) => s + v * (VALENCE[k] ?? 0), 0));
      const [top, topW] = Object.entries(w).reduce((a, b) => (b[1] > a[1] ? b : a));
      if (pv && topW > 0 && topW < CONFLICT_MAX_WEIGHT && (VALENCE[top] ?? 0) * pv < 0) {
        for (const k of EXPR_CHANNELS) w[k] *= CONFLICT_KEEP;
        this.neutral = Math.min(1, this.neutral + (1 - CONFLICT_KEEP) * topW);
        this.conflict = true;
      }
    }
    this.until = hold === Infinity ? Infinity : now + (Number.isFinite(hold) ? Math.max(0, hold) : 0);
    this.meta = meta;
  }

  /** after 秒后结束接管（仍按 BLEND_OUT 渐出，不跳变）；只会提前、不会延长。 */
  release(now, after = 0) { this.until = Math.min(this.until, now + Math.max(0, after)); }

  get active() { return this.weights != null; }

  /** 每帧推进，返回 blend 0..1。 */
  step(now, dt) {
    const on = this.weights != null && now < this.until;
    this.blend = damp(this.blend, on ? 1 : 0, on ? BLEND_IN : BLEND_OUT, dt);
    if (!on && this.blend < 0.005) { this.blend = 0; this.weights = null; this.meta = null; }
    return this.blend;
  }
}

/** 逐通道目标：(1−blend)·PAD + blend·(cue·gain + neutral·fallback)，均已映射到本模型通道。
    fallback = 这句台词的声明情绪先验（×gain），没有声明时为 PAD 心情。
    一句"读不出特定语气"的话（neutral 高）不该把脸清空；读数越确定，这句话自己的表情占比越大。 */
export function mixTargets(presetExpr, cue, plan, gain = 1) {
  const pad = mapWeights(presetExpr, plan);
  if (!cue?.weights || cue.blend <= 0) return pad;
  const tone = mapWeights(cue.weights, plan);
  const prior = cue.prior ? mapWeights(cue.prior, plan) : null;
  const b = cue.blend, n = cue.neutral ?? 0;
  const out = {};
  for (const k of EXPR_CHANNELS) {
    const fallback = prior ? prior[k] * gain : pad[k];
    out[k] = Math.min(1, (1 - b) * pad[k] + b * (tone[k] * gain + n * fallback));
  }
  return out;
}
