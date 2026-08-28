// Two characters on one /live stage, talking to each other via the Runtime Server.
// Needs: studio 8899 + `python -m engine.server.server --port 8765 --mock-llm --time-scale 2`.
import { chromium } from 'playwright';
const shot = process.argv[2];
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
p.on('pageerror', (e) => consoleErrors.push(String(e)));
await p.goto('http://127.0.0.1:8899/live?gw=ws://127.0.0.1:1/ws&runtime=ws://127.0.0.1:8765/body&agents=luna,kai', { waitUntil: 'load' });
await p.waitForFunction(() => window.__live?.body?.vrm, null, { timeout: 30000 });
await p.evaluate(() => window.__live.connectBody());
await p.waitForFunction(() => window.__live.stage.size === 2 && [...window.__live.stage.values()].every((x) => x.vrm), null, { timeout: 60000 });
// stage 2: activities have places — Luna (drawing) should have walked to the desk, Kai (cleaning) stays on the sofa
await p.waitForFunction(() => { const l = window.__live.stage.get('luna'); return l && l.origin.x > 0.8; }, null, { timeout: 30000 });
const before = await p.evaluate(() => [...window.__live.stage].map(([id, b]) => [id, +b.origin.x.toFixed(2), +b.origin.z.toFixed(2)]));
await p.fill('#text', '@luna @kai 今晚吃什么'); await p.press('#text', 'Enter');
await p.waitForFunction(() => window.__live.logs.filter((l) => /^(Luna|Kai): /.test(l.text)).length >= 4, null, { timeout: 60000 });
await p.waitForTimeout(800);
if (shot) await p.screenshot({ path: shot });
const r = await p.evaluate(() => {
  const st = window.__live.stage; const [a, k] = [...st.values()];
  const heads = [a.getHeadScreenPos(window.__live.camera), k.getHeadScreenPos(window.__live.camera)];
  return {
    stageSize: st.size, heads, apart: Math.abs(heads[0].x - heads[1].x),
    lines: window.__live.logs.filter((l) => /^(Luna|Kai): /.test(l.text)).map((l) => l.text),
    lookingAtEachOther: [...st.values()].some((x) => x.lookPoint),
    bubbles: [...document.querySelectorAll('.bubble:not(.hidden)')].map((e) => e.textContent.slice(0, 20)),
    after: [...st].map(([id, b]) => [id, +b.origin.x.toFixed(2), +b.origin.z.toFixed(2)]),
    placeLabels: [...document.querySelectorAll('.place-label:not(.hidden)')].map((e) => e.textContent),
  };
});
const speakers = r.lines.map((l) => l.split(':')[0]);
const alternate = speakers.every((s, i) => i === 0 || s !== speakers[i - 1]);
// to talk, Luna walked over to Kai: both now stand at the same place (sofa), offset side by side
const together = Math.abs(r.after[0][2] - r.after[1][2]) < 0.05 && Math.abs(r.after[0][1] - r.after[1][1]) < 0.7;
const ok = r.stageSize === 2 && r.apart > 5 && r.lines.length >= 4 && alternate && together && r.placeLabels.length === 4 && consoleErrors.length === 0;
console.log(JSON.stringify({ ok, before, ...r, alternate, together, consoleErrors }, null, 1));
await b.close(); process.exit(ok ? 0 : 1);
