// expression_mixer：通道映射 / cue 混合 / 说话让位 / 部位拆分判定（含真实 VRM 资产上的形变分析）。
// 运行：node studio/tests/test_expression_mixer.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  planChannels, mapWeights, mixTargets, unshownHead, speakingGain, residualSums, residualRatio, regionShare,
  ExpressionCue, MOUTH_SPEAKING_GAIN, SPLIT_RESIDUAL_MAX, declaredPrior, CONFLICT_KEEP,
} from '../web/lib/expression_mixer.js';
import { RECIPE_PRESETS } from '../web/lib/pad_expression.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('ok', name); };
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);

test('full / partial / none channel plans', () => {
  const full = planChannels(() => true);
  assert.equal(full.support, 'full'); assert.deepEqual(full.missing, []);
  const noRelaxed = planChannels((k) => k !== 'relaxed' && k !== 'surprised');
  assert.equal(noRelaxed.support, 'partial');
  assert.deepEqual(noRelaxed.map.relaxed, [['happy', 0.5]]);   // warmth → 浅一点的 happy
  assert.deepEqual(noRelaxed.map.surprised, []);              // 无安全替身 → 交给头姿
  assert.deepEqual(noRelaxed.fallbacks, { relaxed: 'happy×0.5' });
  const none = planChannels(() => false);
  assert.equal(none.support, 'none'); assert.equal(none.missing.length, 5);
});

test('mapWeights: fallbacks combine by max, never exceed 1, junk is zero', () => {
  const plan = planChannels((k) => k !== 'relaxed');
  const w = mapWeights({ happy: 0.3, relaxed: 0.8, neutral: 0.2, angry: 'x', sad: NaN, surprised: 5 }, plan);
  near(w.happy, 0.4); near(w.relaxed, 0); near(w.angry, 0); near(w.sad, 0); near(w.surprised, 1);
  assert.ok(!('neutral' in w));
  near(mapWeights({ happy: 0.9, relaxed: 0.9 }, plan).happy, 0.9);
});

test('cue blends in, holds, then hands back to PAD smoothly', () => {
  const plan = planChannels(() => true), cue = new ExpressionCue();
  const pad = RECIPE_PRESETS.soft_smile.expr;                  // happy 0.3, relaxed 0.15
  assert.deepEqual(mixTargets(pad, cue, plan), mapWeights(pad, plan));
  cue.set({ sad: 0.8, neutral: 0 }, { now: 0, hold: 2 });
  let t = 0; const dt = 1 / 60;
  for (; t < 1; t += dt) cue.step(t, dt);
  assert.ok(cue.blend > 0.99, 'blended in within 1s');
  const mid = mixTargets(pad, cue, plan, 0.8);
  near(mid.sad, 0.8 * 0.8 * cue.blend, 1e-9); assert.ok(mid.happy < 0.01);
  const blendAtExpiry = (() => { for (; t < 2; t += dt) cue.step(t, dt); return cue.blend; })();
  assert.ok(blendAtExpiry > 0.99);
  cue.step(t + dt, dt); assert.ok(cue.blend < blendAtExpiry && cue.blend > 0.95, 'no snap after expiry');
  for (let i = 0; i < 600; i++) { t += dt; cue.step(t, dt); }
  assert.equal(cue.blend, 0); assert.equal(cue.active, false);
  assert.deepEqual(mixTargets(pad, cue, plan), mapWeights(pad, plan));
});

test('a neutral reading keeps the PAD mood instead of blanking the face', () => {
  const plan = planChannels(() => true), pad = RECIPE_PRESETS.warm_smile.expr; // happy 0.55, relaxed 0.2
  const neutral = new ExpressionCue(); neutral.set({ neutral: 0.94, happy: 0.0 }, { now: 0 }); neutral.blend = 1;
  const m = mixTargets(pad, neutral, plan, 0.8);
  near(m.happy, 0.94 * 0.55, 1e-9); near(m.relaxed, 0.94 * 0.2, 1e-9);
  const sure = new ExpressionCue(); sure.set({ sad: 0.9, neutral: 0.1 }, { now: 0 }); sure.blend = 1;
  const s2 = mixTargets(pad, sure, plan, 0.8);
  near(s2.sad, 0.9 * 0.8, 1e-9); near(s2.happy, 0.1 * 0.55, 1e-9);           // a confident sentence dominates
  const implied = new ExpressionCue(); implied.set({ happy: 0.3 }, { now: 0 }); near(implied.neutral, 0.7, 1e-9);
  const capped = new ExpressionCue(); capped.set({ happy: 1, neutral: 1 }, { now: 0 }); capped.blend = 1;
  assert.ok(mixTargets({ happy: 0.9 }, capped, plan, 1).happy <= 1);
});

test("a neutral reading shows the line's declared emotion before falling back to PAD", () => {
  const plan = planChannels(() => true), pad = RECIPE_PRESETS.neutralish.expr;            // relaxed 0.08
  const c = new ExpressionCue(); c.set({ happy: 0.016, neutral: 0.984 }, { now: 0, declared: 'happy' }); c.blend = 1;
  const m = mixTargets(pad, c, plan, 0.8);
  near(m.happy, 0.016 * 0.8 + 0.984 * 0.6 * 0.8, 1e-9); near(m.relaxed, 0);             // 真实栈里的"太棒了！"
  const unknown = new ExpressionCue(); unknown.set({ neutral: 1 }, { now: 0, declared: 'attentive' }); unknown.blend = 1;
  near(mixTargets(pad, unknown, plan, 0.8).relaxed, 0.08);                                 // 不认识的声明 → PAD
  assert.deepEqual(declaredPrior('Happy'), { happy: 0.6 }); assert.deepEqual(declaredPrior('难过'), { sad: 0.6 });
  assert.equal(declaredPrior(''), null); assert.equal(declaredPrior(3), null);
  const sure = new ExpressionCue(); sure.set({ sad: 0.95, neutral: 0.05 }, { now: 0, declared: 'happy' }); sure.blend = 1;
  assert.equal(sure.conflict, false); assert.ok(mixTargets(pad, sure, plan, 0.8).sad > 0.7); // 非常确定的读数压过声明
});

test('a readout whose valence contradicts the declared emotion is distrusted', () => {
  const plan = planChannels(() => true), pad = RECIPE_PRESETS.rest.expr;
  // 真实栈："好开心啊，终于考过驾照了！" 读成 sad 0.555 / neutral 0.445，声明 excited
  const c = new ExpressionCue(); c.set({ sad: 0.555, neutral: 0.445 }, { now: 0, declared: 'excited' }); c.blend = 1;
  assert.equal(c.conflict, true);
  near(c.weights.sad, 0.555 * CONFLICT_KEEP, 1e-9); near(c.neutral, 0.445 + (1 - CONFLICT_KEEP) * 0.555, 1e-9);
  const m = mixTargets(pad, c, plan, 0.8);
  assert.ok(m.happy > m.sad, `happy ${m.happy} should beat sad ${m.sad}`);
  // agreeing or neutral-valence declarations do not trigger it
  const ok = new ExpressionCue(); ok.set({ sad: 0.8 }, { now: 0, declared: 'worried' }); assert.equal(ok.conflict, false);
  const sur = new ExpressionCue(); sur.set({ sad: 0.8 }, { now: 0, declared: 'surprised' }); assert.equal(sur.conflict, false);
  const none = new ExpressionCue(); none.set({ sad: 0.8 }, { now: 0 }); assert.equal(none.conflict, false); near(none.weights.sad, 0.8);
});

test('a newer sentence replaces the cue; release only shortens', () => {
  const cue = new ExpressionCue();
  cue.set({ happy: 1 }, { now: 0, hold: Infinity });
  cue.set({ angry: 0.5 }, { now: 1, hold: 3 });
  near(cue.weights.happy, 0); near(cue.weights.angry, 0.5); near(cue.until, 4);
  cue.release(1, 10); near(cue.until, 4);
  cue.release(1, 1.2); near(cue.until, 2.2);
  cue.set({ happy: 1 }, { now: 5 }); assert.equal(cue.until, Infinity);
  cue.set({ happy: 1 }, { now: 5, hold: -3 }); near(cue.until, 5);
});

test('speaking gain applies to the mouth share only', () => {
  near(speakingGain(0, 1), 1);                      // 眉眼表情说话时满值
  near(speakingGain(1, 1), MOUTH_SPEAKING_GAIN);    // 纯嘴部表情 = 旧的整脸 ×0.45
  near(speakingGain(null, 1), MOUTH_SPEAKING_GAIN); // 未知占比 → 旧行为
  near(speakingGain(0.5, 0.5), 1 - (1 - MOUTH_SPEAKING_GAIN) * 0.25);
  near(speakingGain(1, 0), 1);
});

test('emotions a face cannot show go to the head pose', () => {
  const none = planChannels(() => false);
  const h = unshownHead({ sad: 1 }, none);
  near(h.x, RECIPE_PRESETS.down.head.x); near(h.gazeY, RECIPE_PRESETS.down.gaze.y); near(h.amount, 1);
  const half = unshownHead({ sad: 0.5 }, none); near(half.x, 0.5 * RECIPE_PRESETS.down.head.x);
  const full = unshownHead({ sad: 1, happy: 1 }, planChannels(() => true)); near(full.amount, 0); near(full.x, 0);
  const mix = unshownHead({ sad: 1, angry: 1 }, none);   // 权重和 >1 → 归一
  near(mix.x, (RECIPE_PRESETS.down.head.x + RECIPE_PRESETS.stern.head.x) / 2);
});

test('residual and region share math', () => {
  const a = new Float32Array([1, 2, 3, 0, 0, 0]), b = new Float32Array([1, 0, 0, 0, 0, 0]), c = new Float32Array([0, 2, 3, 0, 0, 0]);
  near(residualRatio(a, [b, c]), 0); near(residualRatio(a, [b]), 13 / 14, 1e-6);
  assert.deepEqual(residualSums(a, [b, c]), [0, 14]);
  near(regionShare(a, new Uint8Array([1, 0])), 1); near(regionShare(a, new Uint8Array([0, 1])), 0);
  assert.equal(residualRatio(new Float32Array(3), [b.subarray(0, 3)]), Infinity);
});

// ── 真实资产：VrmBody._regionsFor 的同一判定（ALL ≈ BRW+EYE+MTH？嘴部占比？）──
function loadGlb(path) {
  const buf = readFileSync(path);
  const jlen = buf.readUInt32LE(12);
  const json = JSON.parse(buf.subarray(20, 20 + jlen).toString('utf8'));
  const bin = 20 + jlen + 8;
  const acc = (i) => {
    const a = json.accessors[i], bv = json.bufferViews[a.bufferView];
    assert.ok(!a.sparse, 'dense morph targets expected');
    const off = bin + (bv.byteOffset ?? 0) + (a.byteOffset ?? 0);
    return new Float32Array(buf.buffer.slice(buf.byteOffset + off, buf.byteOffset + off + a.count * 12));
  };
  return { json, acc };
}

function analyzeFace(path) {
  const { json, acc } = loadGlb(path);
  const namesOf = (m) => m.extras?.targetNames ?? m.primitives[0]?.extras?.targetNames ?? [];
  const mesh = json.meshes.find((m) => namesOf(m).some((x) => x.includes('Fcl_ALL_Joy')));
  const names = namesOf(mesh), idx = (suffix) => names.findIndex((x) => x.endsWith(suffix));
  const out = {};
  for (const suf of ['Joy', 'Fun', 'Angry', 'Sorrow', 'Surprised']) {
    let num = 0, den = 0, inMouth = 0, total = 0;
    for (const prim of mesh.primitives) {
      const t = (i) => acc(prim.targets[i].POSITION);
      const all = t(idx('Fcl_ALL_' + suf));
      const parts = ['Fcl_BRW_', 'Fcl_EYE_', 'Fcl_Eye_', 'Fcl_MTH_'].map((p) => idx(p + suf)).filter((i, k, arr) => i >= 0 && arr.indexOf(i) === k).map(t);
      const [a, b] = residualSums(all, parts); num += a; den += b;
      const mask = new Uint8Array(all.length / 3);
      for (const v of ['Fcl_MTH_A', 'Fcl_MTH_I', 'Fcl_MTH_U', 'Fcl_MTH_E', 'Fcl_MTH_O']) {
        const d = t(idx(v)); for (let i = 0; i < mask.length; i++) if (Math.abs(d[3 * i]) + Math.abs(d[3 * i + 1]) + Math.abs(d[3 * i + 2]) > 1e-5) mask[i] = 1;
      }
      let e = 0; for (const x of all) e += x * x;
      total += e; inMouth += e * regionShare(all, mask);
    }
    out[suf] = { residual: num / den, mouthShare: total ? inMouth / total : 0 };
  }
  return out;
}

test('utsuwa: every emotion decomposes exactly → split drive; joy has no mouth part', () => {
  const f = analyzeFace(join(ROOT, 'assets/vtubers/aikeya/utsuwa.vrm'));
  for (const [k, v] of Object.entries(f)) assert.ok(v.residual < SPLIT_RESIDUAL_MAX, `${k} residual ${v.residual}`);
  assert.ok(f.Joy.mouthShare < 0.1, `joy mouth share ${f.Joy.mouthShare}`); // 旧的整脸 ×0.45 白白压暗了笑眼
  console.log('   utsuwa mouth share', Object.fromEntries(Object.entries(f).map(([k, v]) => [k, +v.mouthShare.toFixed(2)])));
});

test('AvatarSample_B: ALL is not the sum of parts → keep whole-expression drive', () => {
  const f = analyzeFace(join(ROOT, 'assets/vtubers/vroid_samples/AvatarSample_B.vrm'));
  assert.ok(f.Joy.residual > SPLIT_RESIDUAL_MAX && f.Angry.residual > SPLIT_RESIDUAL_MAX);
  console.log('   AvatarSample_B mouth share', Object.fromEntries(Object.entries(f).map(([k, v]) => [k, +v.mouthShare.toFixed(2)])));
});

console.log(`\n${n} passed`);
