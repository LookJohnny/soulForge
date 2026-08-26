/* PAD → VRM 表情引擎（浏览器侧）。

   移植自 packages/gateway/src/gateway/face_engine.py 的模型层：
   - 情绪惯性：目标 PAD 由网关每轮推来，当前值指数逼近，目标再向基线缓慢衰减
   - 配方分层：selectRecipe(p,a,d) 与 Python 版逐条同序、同阈值（parity 测试保证）
   - 微行为节律：眨眼频率 / 目光游移随 A 缩放，D 低时目光回避

   与舵机脸唯一的差别在输出：配方 key → VRM 表情权重 + 头部姿态预设，
   由 VrmBody 逐帧阻尼插值，而不是 fire-and-forget 的 HTTP 步骤序列。 */

export const BASELINE = [0.10, 0.00, 0.05];
export const APPROACH = 0.35;   // Python: 每 tick 逼近比例
export const DECAY = 0.06;      // Python: 每 tick 目标向基线衰减比例
export const DEFAULT_INTENSITY = 0.4;

const clamp = (v, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));

/** PAD → 配方 key。顺序即优先级，与 face_engine.select_recipe 一致。 */
export function selectRecipe(p, a, d, intensity = DEFAULT_INTENSITY) {
  const calm = 1 - clamp(intensity, 0, 1);
  const m = Math.max(Math.abs(p), Math.abs(a), Math.abs(d));
  const strong = 0.35 * calm;

  if (p > 0.45 + strong) return 'big_happy';
  if (a > 0.55 + strong && Math.abs(p) < 0.35) return 'surprised';
  if (p < -0.35 - strong && d > 0.25) return 'angry';
  if (p < -0.45 - strong) return 'big_sad';

  if (a < -0.45) return 'sleepy';
  if (p > 0.12 && d < -0.25) return 'shy';
  if (p > 0.30) return 'warm_smile';
  if (p > 0.15) return 'soft_smile';
  if (a > 0.25 && Math.abs(p) <= 0.15) return 'curious';
  if (p < -0.15 && d >= 0) return 'stern';
  if (p < -0.15) return 'down';
  if (m < 0.15) return 'rest';
  return 'neutralish';
}

/* 配方 key → VRM 预设。
   expr: VRM 1.0 preset 表情（缺失的由 VrmBody.setExpr 静默跳过）
   head: 头部附加姿态 (x=俯仰 +低头, y=偏航, z=侧倾)
   gaze: 注视目标附加偏移 (y 向下为负)
   blinkMul: 眨眼间隔倍率 (<1 更频繁)
   eyeAvert: 目光回避概率权重 */
export const RECIPE_PRESETS = {
  big_happy:  { expr: { happy: 0.9, relaxed: 0.1 },              head: { x: -0.06, y: 0, z: 0.05 },  gaze: { y: 0.05 }, blinkMul: 0.8 },
  surprised:  { expr: { surprised: 0.9 },                          head: { x: -0.10, y: 0, z: 0 },     gaze: { y: 0.08 }, blinkMul: 1.6 },
  angry:      { expr: { angry: 0.85 },                             head: { x: 0.08, y: 0, z: 0 },      gaze: { y: 0 },    blinkMul: 1.3 },
  big_sad:    { expr: { sad: 0.9 },                                head: { x: 0.16, y: 0, z: 0.04 },   gaze: { y: -0.25 }, blinkMul: 1.2 },
  sleepy:     { expr: { relaxed: 0.7, sad: 0.15 },                 head: { x: 0.14, y: 0, z: 0.08 },   gaze: { y: -0.3 }, blinkMul: 0.55 },
  shy:        { expr: { happy: 0.35, relaxed: 0.3 },               head: { x: 0.10, y: 0.12, z: 0.10 }, gaze: { y: -0.22 }, blinkMul: 0.85, eyeAvert: 1 },
  warm_smile: { expr: { happy: 0.55, relaxed: 0.2 },               head: { x: -0.02, y: 0, z: 0.03 },  gaze: { y: 0 },    blinkMul: 1.0 },
  soft_smile: { expr: { happy: 0.3, relaxed: 0.15 },               head: { x: 0, y: 0, z: 0.02 },      gaze: { y: 0 },    blinkMul: 1.0 },
  curious:    { expr: { surprised: 0.25, happy: 0.1 },             head: { x: -0.06, y: 0.08, z: -0.10 }, gaze: { y: 0.1 }, blinkMul: 1.1 },
  stern:      { expr: { angry: 0.35 },                             head: { x: 0.04, y: 0, z: 0 },      gaze: { y: 0 },    blinkMul: 1.2 },
  down:       { expr: { sad: 0.45 },                               head: { x: 0.12, y: 0, z: 0.03 },   gaze: { y: -0.18 }, blinkMul: 1.1 },
  rest:       { expr: { relaxed: 0.12 },                           head: { x: 0, y: 0, z: 0 },         gaze: { y: 0 },    blinkMul: 1.0 },
  neutralish: { expr: { relaxed: 0.08 },                           head: { x: 0, y: 0, z: 0 },         gaze: { y: 0 },    blinkMul: 1.0 },
};

export const EXPR_CHANNELS = ['happy', 'sad', 'angry', 'surprised', 'relaxed'];

/** 连续时间版的 PadFaceEngine 情绪状态。 */
export class PadMood {
  constructor({ intensity = DEFAULT_INTENSITY } = {}) {
    this.intensity = intensity;
    this.cur = [...BASELINE];
    this.target = [...BASELINE];
    this.key = 'rest';
    this.speaking = false;
    this._acc = 0;
    this.onChange = null; // (key, pad) => void
  }

  /** 网关推来的 PAD 快照：与 Python 一致，立即向目标迈 0.7 一大步。 */
  onPad(pad) {
    if (!pad) return;
    const p = clamp(Number(pad.p ?? pad.pleasure ?? 0));
    const a = clamp(Number(pad.a ?? pad.arousal ?? 0));
    const d = clamp(Number(pad.d ?? pad.dominance ?? 0));
    this.target = [p, a, d];
    this._step(0.7);
    this._refresh(true);
  }

  onSpeaking(flag) { this.speaking = !!flag; }

  /** Python 的 tick 间隔：A 高节奏快，A 低迟缓。 */
  tickInterval() {
    const calm = 1 - this.intensity;
    const a = this.cur[1];
    return clamp(2.1 - 1.2 * a + calm, 0.9 + calm, 3.2 + calm);
  }

  /** 每帧调用；内部按 tickInterval 离散推进，保持与舵机版同一时间常数。 */
  update(dt) {
    this._acc += dt;
    const iv = this.tickInterval();
    while (this._acc >= iv) {
      this._acc -= iv;
      this._step(APPROACH);
      this._refresh(false);
    }
  }

  get pad() { return { p: this.cur[0], a: this.cur[1], d: this.cur[2] }; }
  get preset() { return RECIPE_PRESETS[this.key] ?? RECIPE_PRESETS.rest; }

  _step(approach) {
    for (let i = 0; i < 3; i++) {
      this.cur[i] += (this.target[i] - this.cur[i]) * approach;
      this.target[i] += (BASELINE[i] - this.target[i]) * DECAY;
    }
  }

  _refresh(force) {
    const key = selectRecipe(this.cur[0], this.cur[1], this.cur[2], this.intensity);
    if (!force && key === this.key) return;
    this.key = key;
    this.onChange?.(key, this.pad);
  }
}
