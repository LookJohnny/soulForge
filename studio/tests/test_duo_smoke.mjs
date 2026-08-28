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
  };
});
const speakers = r.lines.map((l) => l.split(':')[0]);
const alternate = speakers.every((s, i) => i === 0 || s !== speakers[i - 1]);
const ok = r.stageSize === 2 && r.apart > 15 && r.lines.length >= 4 && alternate && consoleErrors.length === 0;
console.log(JSON.stringify({ ok, ...r, alternate, consoleErrors }, null, 1));
await b.close(); process.exit(ok ? 0 : 1);
