/* Generic-humanoid smoke: every non-VRM model in /api/models must load through
   humanoid_adapter, get a synthesized VRM, play the idle VRMA on the normalized
   rig, and project its head into the viewport.
   Run: node studio/tests/test_models_smoke.mjs   (starts its own studio on STUDIO_PORT) */
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const PORT = process.env.STUDIO_PORT ?? '8896';
const proc = spawn('uv', ['run', 'python', 'studio/server.py', '--port', PORT], { stdio: 'ignore' });
process.on('exit', () => { try { proc.kill(); } catch { /* gone */ } });
const t0 = Date.now();
while (Date.now() - t0 < 30000) { try { if ((await fetch(`http://127.0.0.1:${PORT}/api/models`)).ok) break; } catch { /* retry */ } await sleep(300); }
const models = await (await fetch(`http://127.0.0.1:${PORT}/api/models`)).json();
const targets = models.filter((m) => ['fbx', 'glb', 'mmd'].includes(m.kind));

const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 140)); });
await page.goto(`http://127.0.0.1:${PORT}/live?autoconnect=0&hud=0`);
await page.waitForFunction(() => window.__live?.body?.vrm, null, { timeout: 90000 });

const results = [];
for (const m of targets) {
  const r = { name: m.name, kind: m.kind, license: m.license };
  try {
    await page.evaluate(async ({ url, kind }) => { await window.__live.body.load(url, { kind }); }, { url: m.url, kind: m.kind });
    await page.waitForFunction(() => window.__live.body.animated === true, null, { timeout: 20000 }).catch(() => {});
    const q0 = await page.evaluate(() => window.__live.body.vrm.humanoid.getNormalizedBoneNode('head').quaternion.toArray());
    await sleep(1500);
    const info = await page.evaluate(() => {
      const b = window.__live.body, h = b.vrm.humanoid;
      const q1 = h.getNormalizedBoneNode('head').quaternion.toArray();
      const sz = new (b.gazeTarget.position.constructor)(); // Vector3 ctor
      b.vrm.scene.updateMatrixWorld(true);
      const headY = h.getNormalizedBoneNode('head').getWorldPosition(sz).y;
      return { adapter: b.vrm.userData?.adapter, animated: b.animated, native: b.native, toon: b.toon, headY: +headY.toFixed(2), q1, pos: b.getHeadScreenPos(window.__live.camera), hasHappy: b.hasExpr('happy'), hasAa: b.hasExpr('aa') };
    });
    r.rig = info.adapter?.rig; r.bones = info.adapter?.bones; r.expressions = info.adapter?.expressions?.length ?? 0;
    r.idleAnimated = info.animated; r.headMoved = q0.some((v, i) => Math.abs(v - info.q1[i]) > 1e-4);
    r.headY = info.headY; r.headOnScreen = !!info.pos && info.pos.x > 0 && info.pos.x < 100 && info.pos.y > 0 && info.pos.y < 100; r.toon = info.toon;
    await page.evaluate(() => { window.__live.camera.position.set(0, 1.1, 3.2); window.__live.camera.lookAt(0, 0.9, 0); });
    await sleep(200);
    await page.screenshot({ path: `outputs/model_${m.name.replace(/\W+/g, '_')}.png` });
    r.ok = r.idleAnimated && r.headMoved && r.headOnScreen && r.headY > 1.0 && r.headY < 1.7;
  } catch (e) { r.error = String(e.message ?? e).slice(0, 200); r.ok = false; }
  results.push(r);
}
// Expression binding on a synthetic ARKit / VRoid / MMD morph mesh (samples above have no morphs)
const exprCheck = await page.evaluate(async () => {
  const THREE = await import('three');
  const A = await import('/studio/lib/humanoid_adapter.js');
  const mk = (names) => {
    const g = new THREE.BoxGeometry(); g.morphAttributes.position = names.map(() => g.attributes.position.clone());
    const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial()); m.updateMorphTargets(); m.morphTargetDictionary = Object.fromEntries(names.map((n, i) => [n, i])); return m;
  };
  const out = {};
  for (const [label, names] of [['arkit', ['jawOpen', 'mouthSmileLeft', 'mouthSmileRight', 'eyeBlinkLeft', 'eyeBlinkRight', 'browDownLeft', 'browDownRight', 'mouthFunnel', 'mouthPucker']], ['vroid', ['Fcl_MTH_A', 'Fcl_MTH_I', 'Fcl_MTH_U', 'Fcl_MTH_E', 'Fcl_MTH_O', 'Fcl_EYE_Close', 'Fcl_ALL_Joy', 'Fcl_ALL_Sorrow']], ['mmd', ['あ', 'い', 'う', 'え', 'お', 'まばたき', '笑い', '怒り']]]) {
    const root = new THREE.Group(); root.add(mk(names));
    const { manager, bound } = A.buildExpressions(root);
    manager.setValue('aa', 1); manager.update();
    out[label] = { bound, aaValue: manager.getValue('aa') };
  }
  return out;
});
results.push({ name: 'synthetic-expressions', ok: exprCheck.arkit.bound.includes('happy') && exprCheck.arkit.bound.includes('blink') && exprCheck.vroid.bound.includes('aa') && exprCheck.mmd.bound.includes('angry') && exprCheck.arkit.aaValue === 1, detail: exprCheck });

await browser.close(); proc.kill();
const ok = results.length > 0 && results.every((r) => r.ok) && errors.length === 0;
console.log(JSON.stringify({ ok, results, errors: errors.slice(0, 6) }, null, 1));
process.exit(ok ? 0 : 1);
