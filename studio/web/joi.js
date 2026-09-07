/* 「面对面」—— AI 原生互动媒介的第一块试验田。

   画面里只有她：黑场、电影三点布光、泛光、浅推轨运镜、电影字幕。
   引擎完全复用：VrmBody（三层动画/PAD 表情/口型）、GatewayClient（语音
   全链路）、BodyClient（Protocol 0.2 大脑节拍）。呈现层从零，不带一块 HUD。

   URL 参数：?gateway=ws://host:8081/ws  ?runtime=ws://host:8765  ?agent=joi */

import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { VrmBody } from './lib/vrm_body.js';
import { GatewayClient } from './lib/gateway_client.js';
import { BodyClient } from './lib/body_client.js';

const params = new URLSearchParams(location.search);
const AGENT = params.get('agent') ?? 'joi';
const GATEWAY_URL = params.get('gateway') ?? `ws://${location.hostname}:8081/ws`;
const RUNTIME_URL = params.get('runtime') ?? `ws://${location.hostname}:8765/body`;
const MODEL_URL = params.get('model') ?? '/assets/vtubers/vroid_samples/AvatarSample_B.vrm';

const $ = (id) => document.getElementById(id);

// ── 舞台 ────────────────────────────────────────────────
const canvas = $('stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);
scene.fog = new THREE.FogExp2(0x05030a, 0.16);

const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 30);

// ── 电影布光（开场为 0，接通后缓缓亮起）────────────────
const key = new THREE.SpotLight(0xdfe8ff, 0, 8, Math.PI / 5, 0.55, 1.2);
key.position.set(0.9, 2.0, 1.6);
const rimMagenta = new THREE.SpotLight(0xff2f92, 0, 9, Math.PI / 4, 0.5, 1.0);
rimMagenta.position.set(-1.5, 1.9, -1.3);
const rimCyan = new THREE.SpotLight(0x29d7ff, 0, 9, Math.PI / 4, 0.6, 1.0);
rimCyan.position.set(1.6, 0.9, -1.4);
const ambient = new THREE.AmbientLight(0x1a1626, 0);
const lightTarget = new THREE.Object3D();
lightTarget.position.set(0, 1.3, 0);
scene.add(lightTarget);
for (const light of [key, rimMagenta, rimCyan]) { light.target = lightTarget; scene.add(light); }
scene.add(ambient);
const LIGHT_TARGETS = [[key, 2.6], [rimMagenta, 4.2], [rimCyan, 2.0], [ambient, 0.5]];
let lightRamp = 0; // 0→1 over the reveal

// ── 地面辉光：她站在自己的光里 ──────────────────────────
function glowTexture() {
  const size = 512;
  const cnv = document.createElement('canvas');
  cnv.width = cnv.height = size;
  const ctx = cnv.getContext('2d');
  const grad = ctx.createRadialGradient(size / 2, size / 2, 10, size / 2, size / 2, size / 2);
  grad.addColorStop(0, 'rgba(255,64,150,0.55)');
  grad.addColorStop(0.45, 'rgba(120,50,160,0.18)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(cnv);
}
const glow = new THREE.Mesh(
  new THREE.PlaneGeometry(3.4, 3.4),
  new THREE.MeshBasicMaterial({ map: glowTexture(), transparent: true, depthWrite: false }),
);
glow.rotation.x = -Math.PI / 2;
glow.position.y = 0.005;
scene.add(glow);

// ── 空气中的尘埃：让光有体积 ────────────────────────────
const DUST_COUNT = 260;
const dustPositions = new Float32Array(DUST_COUNT * 3);
for (let i = 0; i < DUST_COUNT; i++) {
  dustPositions[i * 3] = (Math.random() - 0.5) * 2.6;
  dustPositions[i * 3 + 1] = Math.random() * 2.1;
  dustPositions[i * 3 + 2] = (Math.random() - 0.5) * 2.2;
}
const dustGeometry = new THREE.BufferGeometry();
dustGeometry.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3));
const dust = new THREE.Points(dustGeometry, new THREE.PointsMaterial({
  color: 0xffc4e2, size: 0.008, transparent: true, opacity: 0.0,
  blending: THREE.AdditiveBlending, depthWrite: false,
}));
scene.add(dust);

// ── 泛光 ────────────────────────────────────────────────
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.65, 0.55, 0.82);
composer.addPass(bloom);
composer.addPass(new OutputPass());

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  composer.setSize(w, h);
  bloom.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);
resize();

// ── 她 ──────────────────────────────────────────────────
const body = new VrmBody(scene, { height: 1.62 });
let ready = false;
(async () => {
  try {
    const anims = await fetch('/api/animations').then((r) => r.json()).catch(() => []);
    const byName = (re) => anims.filter((a) => re.test(a.url)).map((a) => a.url);
    body.idleUrls = byName(/\/idle(_\d+)?\.vrma$/);
    body.talkingUrl = byName(/\/talking\.vrma$/)[0] ?? null;
    await body.load(MODEL_URL, { kind: 'vrm' });
    frameOnHead();
    ready = true;
  } catch (e) {
    $('gate-hint').textContent = '模型加载失败：' + (e?.message ?? e);
  }
})();

// ── 运镜：只有两句台词——注视，与靠近 ────────────────────
const cam = {
  base: { x: 0, y: 1.36, z: 2.1 },
  near: { x: 0.06, y: 1.42, z: 1.52 },
  cur: { x: 0, y: 1.36, z: 2.35 },   // 开场略远，接通后缓缓靠近
  lookY: 1.38,
  speaking: false,
};
function frameOnHead() {
  // frame on the model's REAL head, whatever its proportions — hardcoded
  // heights put this model's face at the bottom of the screen
  const head = body.vrm?.humanoid?.getNormalizedBoneNode?.('head')
    ?? body.vrm?.humanoid?.getBoneNode?.('head');
  if (!head) return;
  const p = new THREE.Vector3();
  head.getWorldPosition(p);
  const headY = p.y + 0.04; // eyes sit slightly above the head bone pivot
  cam.base = { x: 0, y: headY - 0.03, z: 2.05 };
  cam.near = { x: 0.05, y: headY + 0.01, z: 1.48 };
  cam.cur = { x: 0, y: headY - 0.03, z: 2.3 };
  cam.lookY = headY - 0.07;
  lightTarget.position.y = headY - 0.18;
}

function updateCamera(dt, t) {
  const target = cam.speaking ? cam.near : cam.base;
  const damp = 1 - Math.exp(-0.55 * dt);       // 极缓，像斯坦尼康
  cam.cur.x += (target.x - cam.cur.x) * damp;
  cam.cur.y += (target.y - cam.cur.y) * damp;
  cam.cur.z += (target.z - cam.cur.z) * damp;
  // 呼吸般的漂移
  const driftX = Math.sin(t * 0.11) * 0.035 + Math.sin(t * 0.041) * 0.02;
  const driftY = Math.sin(t * 0.083) * 0.018;
  camera.position.set(cam.cur.x + driftX, cam.cur.y + driftY, cam.cur.z);
  camera.lookAt(0, cam.lookY + driftY * 0.4, 0);
}

// ── 字幕 ────────────────────────────────────────────────
const subtitle = $('subtitle');
let subtitleTimer = null;
let line = '';
function showSubtitle(text, { append = false } = {}) {
  line = append ? line + text : text;
  subtitle.textContent = line;
  subtitle.classList.add('on');
  clearTimeout(subtitleTimer);
}
function fadeSubtitle(after = 2200) {
  clearTimeout(subtitleTimer);
  subtitleTimer = setTimeout(() => { subtitle.classList.remove('on'); line = ''; }, after);
}
const heard = $('heard');
let heardTimer = null;
function showHeard(text) {
  heard.textContent = text;
  heard.classList.add('on');
  clearTimeout(heardTimer);
  heardTimer = setTimeout(() => heard.classList.remove('on'), 3600);
}

// ── 接通 ────────────────────────────────────────────────
let gw = null;
let bodyClient = null;

async function enter() {
  $('enter').disabled = true;
  $('gate-hint').textContent = '正在接通…';
  if (!ready) { await new Promise((r) => { const t = setInterval(() => { if (ready) { clearInterval(t); r(); } }, 120); }); }

  gw = new GatewayClient({ url: GATEWAY_URL, sessionName: 'joi-face' });
  gw.addEventListener('open', () => { $('dot').classList.add('live'); body.setAudioAnalyser(gw.analyser); });
  gw.addEventListener('close', () => { $('dot').classList.remove('live'); body.setAudioAnalyser(null); body.setSpeaking(false); setTimeout(() => gw?.connect().catch(() => {}), 3000); });
  gw.addEventListener('sentence', (e) => showSubtitle(e.detail.text, { append: line.length > 0 }));
  gw.addEventListener('speaking', (e) => {
    cam.speaking = e.detail.speaking;
    body.setSpeaking(e.detail.speaking);
    if (!e.detail.speaking) fadeSubtitle();
  });
  gw.addEventListener('emotion', (e) => body.setPad(e.detail.pad));
  gw.addEventListener('reaction', (e) => { if (e.detail?.text) showHeard(e.detail.text); });

  bodyClient = new BodyClient({ url: RUNTIME_URL, bodyId: 'web-joi-face', agentIds: [AGENT], speech: false });
  bodyClient.attach(() => body, {});

  try {
    await gw.ensureAudio();
    await gw.connect();
    await gw.startMic();   // 常听：停顿约 1 秒自动断句
  } catch (e) { $('gate-hint').textContent = '语音接通失败：' + (e?.message ?? e); }
  try { await bodyClient.connect(); } catch { /* 大脑不在时她仍然在 */ }

  $('gate').classList.add('leaving');
  setTimeout(() => $('gate').remove(), 1800);
  revealStart = performance.now();
}
$('enter').onclick = enter;
let revealStart = 0;

// ── 换魂：拖一个 .soul 进来，一秒后是另一个人 ─────────────
async function installSoul(file) {
  showSubtitle('…正在读取灵魂…');
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    const b64 = btoa(binary);
    const importResponse = await fetch('/api/soul/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ soul_b64: b64 }),
    });
    const imported = await importResponse.json();
    if (!importResponse.ok) throw new Error(imported?.error ?? 'soul 导入失败');
    if (!imported?.id) throw new Error(imported?.error ?? 'soul 导入失败');

    // 大脑热装载 → 语音通道热切换 → 本页换身体
    const switched = await fetch('/api/runtime/agent', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: imported.id }),
    });
    const switchResult = await switched.json();
    if (!switched.ok || !switchResult.ok) {
      throw new Error(switchResult.error ?? '大脑未确认换魂，请检查本地服务');
    }

    // 电影式交接：黑场 → 新模型 → 新名字浮现
    const fade = document.createElement('div');
    fade.style.cssText = 'position:fixed;inset:0;background:#000;opacity:0;transition:opacity 1.1s;z-index:9';
    document.body.appendChild(fade);
    requestAnimationFrame(() => (fade.style.opacity = '1'));
    await new Promise((r) => setTimeout(r, 1200));

    if (imported.model_url) {
      try { await body.load(imported.model_url, { kind: imported.model_kind ?? 'vrm' }); frameOnHead(); } catch { /* 模型缺失沿用当前 */ }
    }
    bodyClient?.close?.();
    bodyClient = new BodyClient({ url: RUNTIME_URL, bodyId: 'web-joi-face', agentIds: [imported.id], speech: false });
    bodyClient.attach(() => body, {});
    bodyClient.connect().catch(() => {});

    fade.style.opacity = '0';
    setTimeout(() => fade.remove(), 1300);
    showSubtitle(`—— ${imported.name} ——`);
    fadeSubtitle(3200);
  } catch (e) {
    showSubtitle('换魂失败：' + (e?.message ?? e));
    fadeSubtitle(3000);
  }
}
// 导演接口：拍摄脚本可程序化接通/换魂/打字幕
window.__joi = {
  enter,
  installSoul,
  installSoulFromUrl: async (url, name = 'demo.soul') => {
    const blob = await fetch(url).then((r) => r.blob());
    return installSoul(new File([blob], name));
  },
  showSubtitle,
  fadeSubtitle,
};

addEventListener('dragover', (e) => e.preventDefault());
addEventListener('drop', (e) => {
  e.preventDefault();
  const file = e.dataTransfer?.files?.[0];
  if (file && file.name.endsWith('.soul')) installSoul(file);
});

// ── 主循环 ──────────────────────────────────────────────
const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(clock.getDelta(), 0.1);
  const t = clock.elapsedTime;

  if (revealStart) {
    lightRamp = Math.min(1, (performance.now() - revealStart) / 3000);
    const eased = lightRamp * lightRamp * (3 - 2 * lightRamp);
    for (const [light, max] of LIGHT_TARGETS) light.intensity = max * eased;
    dust.material.opacity = 0.35 * eased;
    glow.material.opacity = eased;
  }

  // 尘埃缓慢上升回环
  const positions = dust.geometry.attributes.position;
  for (let i = 0; i < DUST_COUNT; i++) {
    let y = positions.getY(i) + dt * 0.02 * (0.4 + (i % 5) * 0.2);
    if (y > 2.15) y = 0;
    positions.setY(i, y);
  }
  positions.needsUpdate = true;

  if (gw && !body.lipsync?.analyser) body.setSpeakingLevel(gw.level());
  body.update();
  updateCamera(dt, t);
  composer.render();
}
frame();
