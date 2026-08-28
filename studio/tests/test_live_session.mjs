// Structured live session against the REAL stack: functional coverage, character fit, motion quality.
import { chromium } from 'playwright';
import fs from 'node:fs';
const OUT = process.argv[2] || '/tmp/film';
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on('pageerror', (e) => errors.push(String(e))); p.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
const t0 = Date.now(); const shots = []; let n = 0;
const shot = async (tag) => { const f = `${OUT}/${String(n++).padStart(2, '0')}_${tag}.png`; await p.screenshot({ path: f }); shots.push(f); };
await p.goto('http://127.0.0.1:8899/live?gateway=ws://127.0.0.1:8081/ws&runtime=ws://127.0.0.1:8765/body&agents=luna,kai', { waitUntil: 'load' });
await p.waitForFunction(() => window.__live?.body?.vrm, null, { timeout: 30000 });
await p.waitForFunction(() => window.__live.bodyClient?.welcome, null, { timeout: 30000 }); // auto-connects from ?runtime=
await p.waitForFunction(() => window.__live.stage.size === 2 && [...window.__live.stage.values()].every((x) => x.vrm && x.animated), null, { timeout: 60000 });
// motion sampler
await p.evaluate(() => {
  window.__S = { samples: [], frames: 0, lastT: performance.now(), maxDt: 0 };
  const raf = () => { const now = performance.now(); window.__S.frames++; window.__S.maxDt = Math.max(window.__S.maxDt, now - window.__S.lastT); window.__S.lastT = now; requestAnimationFrame(raf); }; requestAnimationFrame(raf);
  setInterval(() => {
    const row = { t: performance.now(), bodies: {} };
    for (const [id, x] of window.__live.stage) {
      const head = x.vrm.humanoid.getNormalizedBoneNode('head').rotation; const arm = x.vrm.humanoid.getNormalizedBoneNode('leftUpperArm').rotation;
      row.bodies[id] = { x: x.origin.x, z: x.origin.z, yaw: x.vrm.scene.rotation.y, walking: !!x.walking, pose: x.pose?.name ?? null, speaking: x.speaking, y: x.vrm.scene.position.y, head: [head.x, head.y, head.z], arm: [arm.x, arm.y, arm.z], look: !!x.lookPoint };
    }
    row.bubbles = [...document.querySelectorAll('.bubble:not(.hidden):not(.typing)')].map((e) => e.textContent.length);
    window.__S.samples.push(row);
  }, 100);
});
const gwOk = await p.evaluate(() => new Promise((r) => { let n = 0; const i = setInterval(() => { if (window.__live.gw?.ws?.readyState === 1) { clearInterval(i); r(true); } if (++n > 60) { clearInterval(i); r(false); } }, 250); }));
await shot('start');
// 1. autonomy: watch them live for 25 s
await p.waitForTimeout(12000); await shot('autonomy_a'); await p.waitForTimeout(13000); await shot('autonomy_b');
// 2. conversation
await p.fill('#text', '@luna @kai 今晚吃什么'); await p.press('#text', 'Enter');
const linesAt = () => p.evaluate(() => window.__live.logs.filter((l) => /^(Luna|Kai): /.test(l.text)).map((l) => l.text));
let lines = []; const convStart = Date.now();
for (let i = 0; i < 40 && Date.now() - convStart < 200000; i++) {
  await p.waitForTimeout(5000); const cur = await linesAt();
  if (cur.length > lines.length) { lines = cur; await shot(`talk_${lines.length}`); }
  if (lines.length >= 6) break;
}
const convMs = Date.now() - convStart;
await p.waitForTimeout(6000); await shot('after_talk');
// 3. user talks to Luna through the gateway (if up)
let gwReply = null, hud = null;
if (gwOk) {
  await p.fill('#text', '我今天加班到八点，有点累'); await p.press('#text', 'Enter');
  const before = (await p.evaluate(() => window.__live.logs.length));
  await p.waitForFunction((n) => window.__live.logs.length > n && !document.getElementById('bubble').classList.contains('hidden'), before, { timeout: 60000 }).catch(() => {});
  await p.waitForTimeout(1500); await shot('user_chat');
  gwReply = await p.evaluate(() => document.getElementById('bubble-text').textContent);
  await p.waitForTimeout(8000);
  hud = await p.evaluate(() => ({ stage: document.getElementById('hud-stage').textContent, emotion: document.getElementById('hud-emotion').textContent, causes: document.getElementById('hud-causes').textContent, axes: [...document.querySelectorAll('.axis')].map((a) => a.textContent.trim().slice(0, 12)) }));
}
// 4. UI surface
await p.click('#btn-settings'); await p.waitForTimeout(400); await shot('settings');
const ui = await p.evaluate(() => ({ models: document.querySelectorAll('#model option').length, anims: document.querySelectorAll('#anim option').length, soulChars: document.querySelectorAll('#soul-char option').length, bodyStatus: document.getElementById('body-status').textContent, status: document.getElementById('status').textContent }));
await p.click('#btn-settings'); await p.click('#btn-memory'); await p.waitForTimeout(3000); await shot('memory');
const mem = await p.evaluate(() => document.getElementById('memory-stats').textContent + ' | ' + document.getElementById('memory-hint').textContent);
// metrics
const m = await p.evaluate(() => {
  const S = window.__S; const out = { frames: S.frames, seconds: (performance.now() - S.samples[0].t) / 1000, maxFrameGapMs: Math.round(S.maxDt), teleports: [], yawJumps: [], poseWhileWalking: 0, overlap: 0, walkSamples: 0, lookSamples: 0, poses: {}, ySink: 0 };
  let prev = null;
  for (const row of S.samples) {
    let speaking = 0;
    for (const [id, b] of Object.entries(row.bodies)) {
      if (b.speaking) speaking++;
      if (b.walking) { out.walkSamples++; if (b.pose) out.poseWhileWalking++; }
      if (b.look) out.lookSamples++;
      if (b.pose) out.poses[b.pose] = (out.poses[b.pose] ?? 0) + 1;
      if (b.y < -0.02 && !b.pose) out.ySink++;
      if (prev?.bodies[id]) {
        const q = prev.bodies[id]; const d = Math.hypot(b.x - q.x, b.z - q.z); if (d > 0.25) out.teleports.push({ id, d: +d.toFixed(2), t: Math.round(row.t - S.samples[0].t) });
        let dy = Math.abs(b.yaw - q.yaw); dy = Math.min(dy, Math.abs(dy - Math.PI * 2)); if (dy > 0.6) out.yawJumps.push({ id, dy: +dy.toFixed(2), t: Math.round(row.t - S.samples[0].t) });
      }
    }
    if (speaking > 1) out.overlap++;
    prev = row;
  }
  out.fps = +(out.frames / out.seconds).toFixed(1); out.samples = S.samples.length;
  return out;
});
console.log(JSON.stringify({ gwOk, convMs, lines, gwReply, hud, ui, mem, metrics: m, errors: errors.slice(0, 8), shots }, null, 1));
await b.close();
