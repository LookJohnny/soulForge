/* Headless smoke test for /live against the fake gateway.
   Run: node studio/tests/test_live_smoke.mjs  (starts studio server + fake gateway itself)
   Env: STUDIO_PORT (8899), FAKE_GW_PORT (8081), SMOKE_OUT (screenshot path) */

import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const STUDIO_PORT = process.env.STUDIO_PORT ?? '8899';
const GW_PORT = process.env.FAKE_GW_PORT ?? '8081';
const OUT = process.env.SMOKE_OUT ?? 'outputs/live_smoke.png';

const procs = [];
const start = (args) => { const p = spawn('uv', ['run', 'python', ...args], { stdio: 'ignore' }); procs.push(p); return p; };
start(['studio/server.py', '--port', STUDIO_PORT]);
start(['studio/tests/fake_gateway.py', GW_PORT]);
const cleanup = () => { for (const p of procs) { try { p.kill(); } catch { /* gone */ } } };
process.on('exit', cleanup);

async function waitHttp(url, ms = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if ((await fetch(url)).ok) return; } catch { /* retry */ } await sleep(300); }
  throw new Error('server not up: ' + url);
}
await waitHttp(`http://127.0.0.1:${STUDIO_PORT}/api/models`);

const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

const checks = {};
const fail = (k, v) => { checks[k] = v; };

await page.goto(`http://127.0.0.1:${STUDIO_PORT}/live?gateway=ws://127.0.0.1:${GW_PORT}/ws`);
await page.waitForFunction(() => window.__live?.logs.some((l) => l.text.startsWith('已换装')), null, { timeout: 90000 });
checks.modelLoaded = await page.evaluate(() => !!window.__live.body.vrm);
checks.modelName = await page.evaluate(() => document.getElementById('hud-name').textContent);
await page.waitForFunction(() => window.__live.logs.some((l) => l.text === 'gateway 已连接'), null, { timeout: 15000 });

// idle VRMA took over the skeleton
await page.waitForFunction(() => window.__live.body.animated === true, null, { timeout: 30000 }).catch(() => fail('idleAnimated', false));
checks.idleAnimated = await page.evaluate(() => window.__live.body.animated);
checks.idleClip = await page.evaluate(() => window.__live.body.idleUrls[window.__live.body.idleIndex]?.split('/').pop());
// initial relationship snapshot rendered
checks.hudStage = await page.evaluate(() => document.getElementById('hud-stage').textContent);
checks.hudAxes = await page.evaluate(() => document.querySelectorAll('#hud-rel .axis').length);

// one text turn
await page.fill('#text', '你好 事件');
await page.press('#text', 'Enter');
await page.waitForFunction(() => window.__live.gw.speaking === true, null, { timeout: 8000 });
checks.talkingRunning = await page.evaluate(() => !!window.__live.body.talkingAction?.isRunning());
let maxViseme = 0, maxLevel = 0;
for (let i = 0; i < 20; i++) {
  await sleep(60);
  const w = await page.evaluate(() => ({ ...window.__live.body.lipsync.weights, lvl: window.__live.body.speakingLevel }));
  maxViseme = Math.max(maxViseme, w.aa, w.oh, w.ee, w.ih, w.ou); maxLevel = Math.max(maxLevel, w.lvl);
}
checks.maxViseme = +maxViseme.toFixed(3);
checks.maxLevel = +maxLevel.toFixed(3);
checks.bubble = await page.evaluate(() => document.getElementById('bubble-text').textContent);
checks.bubbleVisible = await page.evaluate(() => !document.getElementById('bubble').classList.contains('hidden'));
checks.moodKey = await page.evaluate(() => window.__live.body.mood.key);
checks.hudEmotion = await page.evaluate(() => document.getElementById('hud-emotion').textContent);
checks.hudCauses = await page.evaluate(() => document.getElementById('hud-causes').textContent);
checks.headPos = await page.evaluate(() => window.__live.body.getHeadScreenPos(window.__live.camera));
await page.waitForFunction(() => window.__live.gw.speaking === false, null, { timeout: 10000 });
checks.idleBackAfterTalk = await page.evaluate(() => !!window.__live.body.idleAction?.isRunning());

// event scene card + choice round trip
await page.waitForFunction(() => !document.getElementById('event-overlay').classList.contains('hidden'), null, { timeout: 5000 }).catch(() => fail('eventShown', false));
checks.eventShown = await page.evaluate(() => !document.getElementById('event-overlay').classList.contains('hidden'));
checks.eventChoices = await page.evaluate(() => document.querySelectorAll('#event-overlay .choices button').length);
await page.screenshot({ path: OUT });
if (checks.eventChoices) {
  await page.click('#event-overlay .choices button');
  await sleep(300);
  checks.intimacyAfterChoice = await page.evaluate(() => document.querySelectorAll('#hud-rel .axis')[2]?.querySelector('.bar i')?.style.width);
}

await browser.close();
cleanup();

const ok = errors.length === 0 && checks.modelLoaded && checks.idleAnimated && checks.hudAxes === 6
  && checks.maxViseme > 0.02 && checks.bubble === 'echo: 你好 事件' && checks.eventChoices === 2
  && ['big_happy', 'warm_smile'].includes(checks.moodKey);
console.log(JSON.stringify({ ok, checks, errors }, null, 1));
process.exit(ok ? 0 : 1);
