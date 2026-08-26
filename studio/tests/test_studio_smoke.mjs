/* Headless smoke for the Studio workbench (/) after the VrmBody migration.
   Run: node studio/tests/test_studio_smoke.mjs */
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const PORT = process.env.STUDIO_PORT ?? '8898';
const proc = spawn('uv', ['run', 'python', 'studio/server.py', '--port', PORT], { stdio: 'ignore' });
process.on('exit', () => { try { proc.kill(); } catch { /* gone */ } });
const t0 = Date.now();
while (Date.now() - t0 < 30000) { try { if ((await fetch(`http://127.0.0.1:${PORT}/api/models`)).ok) break; } catch { /* retry */ } await sleep(300); }

const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required', '--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
await page.goto(`http://127.0.0.1:${PORT}/`);
await page.waitForFunction(() => window.__studio?.body?.vrm || window.__studio?.robot?.root, null, { timeout: 90000 });
const checks = {};
checks.vrmLoaded = await page.evaluate(() => !!window.__studio.body.vrm);
checks.idleAnimated = await page.evaluate(() => window.__studio.body.animated);
checks.capDetail = await page.evaluate(() => document.getElementById('cap-detail').textContent);
// mock brain chat round-trip (no LLM key → deterministic mock)
await page.fill('#chat-text', '你好');
await page.press('#chat-text', 'Enter');
await page.waitForFunction(() => document.querySelectorAll('#chat-log .msg.agent').length >= 1, null, { timeout: 30000 });
checks.reply = await page.evaluate(() => document.querySelector('#chat-log .msg.agent')?.textContent?.slice(0, 40));
checks.decisionRendered = await page.evaluate(() => !!document.querySelector('#decision .card'));
// switch to the robot GLB if present and back
const robotCard = await page.$('#model-grid .model-card[data-kind="robot"]');
if (robotCard) { await robotCard.click(); await page.waitForFunction(() => !!window.__studio.robot.root, null, { timeout: 60000 }); checks.robotLoaded = true; }
await page.screenshot({ path: 'outputs/studio_smoke.png' });
await browser.close();
proc.kill();
const ok = errors.length === 0 && checks.vrmLoaded && checks.decisionRendered;
console.log(JSON.stringify({ ok, checks, errors }, null, 1));
process.exit(ok ? 0 : 1);
