import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';

const args = parseArgs(process.argv.slice(2));
const out = resolve(args.out ?? 'outputs/webgl/vtuber_life_30min.mp4');
const framesDir = resolve(args.framesDir ?? 'outputs/webgl/vtuber_life_frames');
const durationMinutes = Number(args.durationMinutes ?? 30);
const fps = Number(args.fps ?? 6);
const width = Number(args.width ?? 1280);
const height = Number(args.height ?? 720);
const totalFrames = Math.max(1, Math.round(durationMinutes * 60 * fps));
const port = Number(args.port ?? 5178);
const page_ = String(args.page ?? 'index.html');
const clean = args.clean === true || args.clean === 'true' || args.clean === '1';
const resume = args.resume === true || args.resume === 'true';
const simStartMinutes = Number(args.simStartMinutes ?? 0);
const simDurationMinutes = Number(args.simDurationMinutes ?? durationMinutes);

mkdirSync(resolve('outputs/webgl'), { recursive: true });
if (!resume) rmSync(framesDir, { recursive: true, force: true });
mkdirSync(framesDir, { recursive: true });

const vite = spawn(
  process.platform === 'win32' ? 'npx.cmd' : 'npx',
  ['vite', '--config', 'demo/vtuber_life_web/vite.record.config.mjs', '--host', '127.0.0.1', '--port', String(port)],
  { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'pipe'] },
);

try {
  await waitForServer(port);
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  const url = `http://127.0.0.1:${port}/demo/vtuber_life_web/${page_}${clean ? '?clean=1' : ''}`;
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => window.__soulforge?.ready?.() === true, null, { timeout: 120000 });

  for (let frame = 0; frame < totalFrames; frame += 1) {
    const progress = totalFrames <= 1 ? 0 : frame / (totalFrames - 1);
    const simTime = (simStartMinutes + progress * simDurationMinutes) * 60;
    await page.evaluate((t) => window.__soulforge.setTime(t), simTime);
    const framePath = join(framesDir, `frame_${String(frame).padStart(6, '0')}.png`);
    if (resume && existsSync(framePath)) continue;  // state advanced; screenshot present
    await page.screenshot({ path: framePath, animations: 'disabled' });
    if (frame % 300 === 0) {
      console.log(`captured ${frame}/${totalFrames}`);
    }
  }
  await browser.close();

  await run('ffmpeg', [
    '-y',
    '-framerate',
    String(fps),
    '-i',
    join(framesDir, 'frame_%06d.png'),
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    '-crf',
    '18',
    out,
  ]);
  console.log(`wrote ${out}`);
  console.log(`frames ${totalFrames}`);
  console.log(`duration_s ${durationMinutes * 60}`);
  console.log(`sim_start_min ${simStartMinutes}`);
  console.log(`sim_duration_min ${simDurationMinutes}`);
} finally {
  vite.kill('SIGTERM');
}

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith('--')) continue;
    const name = key.slice(2).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      parsed[name] = true;
    } else {
      parsed[name] = next;
      i += 1;
    }
  }
  return parsed;
}

async function waitForServer(port) {
  const url = `http://127.0.0.1:${port}/demo/vtuber_life_web/index.html`;
  const started = Date.now();
  while (Date.now() - started < 60000) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      // keep waiting
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 500));
  }
  throw new Error(`Vite did not start on ${port}`);
}

function run(command, commandArgs) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, commandArgs, { stdio: 'inherit' });
    child.on('exit', (code) => {
      if (code === 0) resolveRun();
      else rejectRun(new Error(`${command} exited ${code}`));
    });
  });
}
