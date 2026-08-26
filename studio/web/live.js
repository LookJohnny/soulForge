/* SoulForge Live —— VRM 作为 gateway 的一个"身体"。
   语音/记忆/PAD 全部来自 gateway 真实管道；本页只负责：渲染、口型、
   PAD→表情、麦克风上行。与小智 ESP32 平级。 */

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { VrmBody } from '/studio/lib/vrm_body.js';
import { GatewayClient } from '/studio/lib/gateway_client.js';

const $ = (id) => document.getElementById(id);
const log = (text, cls = 'agent') => {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.textContent = text;
  $('log').appendChild(el);
  $('log').scrollTop = $('log').scrollHeight;
};

// ── 舞台 ──────────────────────────────────────────────
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(2, devicePixelRatio));
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d0f14);
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
camera.position.set(0, 1.32, 2.9);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 1.05, 0);
controls.enablePan = false;
scene.add(new THREE.HemisphereLight(0xfff4e0, 0x2a2438, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(1.5, 3, 2.5); scene.add(key);
const rim = new THREE.DirectionalLight(0x8ecae6, 0.8); rim.position.set(-2, 2, -2); scene.add(rim);
const ground = new THREE.Mesh(new THREE.CircleGeometry(1.6, 64), new THREE.MeshStandardMaterial({ color: 0x151820, roughness: 1 }));
ground.rotation.x = -Math.PI / 2; scene.add(ground);

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / h; camera.updateProjectionMatrix();
}
addEventListener('resize', resize); resize();

const body = new VrmBody(scene, { height: 1.55 });
body.mood.onChange = (k) => { $('recipe').textContent = k; };
canvas.parentElement.addEventListener('pointermove', (e) => {
  const r = canvas.getBoundingClientRect();
  body.setGaze(((e.clientX - r.left) / r.width) * 2 - 1, ((e.clientY - r.top) / r.height) * 2 - 1);
});
canvas.parentElement.addEventListener('pointerleave', () => body.setGaze(0, 0));

// ── 模型列表（复用 studio 的 /api/models）────────────
async function loadModels() {
  const sel = $('model');
  try {
    const list = await (await fetch('/api/models')).json();
    const vrms = (list.models ?? list).filter((m) => (m.kind ?? 'vrm') === 'vrm');
    for (const m of vrms) {
      const o = document.createElement('option');
      o.value = m.url; o.textContent = m.name ?? m.url.split('/').pop();
      sel.appendChild(o);
    }
    // 优先带情绪表情的 VRoid 样例；open_source_avatars 里多数只有口型+眨眼
    const first = vrms.find((m) => /AvatarSample_B/i.test(m.url)) ?? vrms.find((m) => m.url.includes('vroid_samples')) ?? vrms[0];
    if (first) { sel.value = first.url; await pick(first.url); }
  } catch (e) { log('模型列表获取失败: ' + e.message, 'sys'); }
  sel.onchange = () => pick(sel.value);
}
async function pick(url) {
  try { await body.load(url); log('已换装 ' + decodeURIComponent(url.split('/').pop()), 'sys'); }
  catch (e) { log('模型加载失败: ' + e.message, 'sys'); }
}

// ── Gateway ───────────────────────────────────────────
let gw = null;
const padUI = () => {
  const { p, a, d } = body.mood.pad;
  const bar = (v) => { const w = Math.abs(v) * 45; const left = v >= 0 ? 45 : 45 - w; return `<span class="bar"><i style="left:${left}px;width:${w}px"></i></span>`; };
  $('pad').innerHTML = `P${bar(p)}${p.toFixed(2)}<br>A${bar(a)}${a.toFixed(2)}<br>D${bar(d)}${d.toFixed(2)}<br>配方 <span id="recipe">${body.mood.key}</span>`;
};

async function connect() {
  gw?.close();
  const url = $('gw').value.trim() || `ws://${location.hostname}:8080/ws`;
  gw = new GatewayClient({ url, sessionName: 'vrm-live' });
  gw.addEventListener('open', (e) => { $('status').innerHTML = `已连接 <b>${e.detail.device_id}</b>`; log('gateway 已连接', 'sys'); });
  gw.addEventListener('close', () => { $('status').textContent = '连接断开'; $('mic').classList.remove('on'); });
  gw.addEventListener('error', (e) => log('⚠ ' + (e.detail?.message ?? e.detail), 'sys'));
  gw.addEventListener('sentence', (e) => log(e.detail.text));
  gw.addEventListener('speaking', (e) => body.setSpeaking(e.detail.speaking));
  gw.addEventListener('emotion', (e) => { body.setPad(e.detail.pad); padUI(); });
  gw.addEventListener('mic', (e) => $('mic').classList.toggle('on', e.detail.on));
  try {
    await gw.ensureAudio();
    await gw.connect();
  } catch (e) { log('连接失败: ' + (e.message ?? e), 'sys'); }
}

$('connect').onclick = connect;
$('form').onsubmit = (e) => {
  e.preventDefault();
  const t = $('text').value.trim();
  if (!t || !gw) return;
  log(t, 'user'); gw.sendText(t); $('text').value = '';
};
$('stop').onclick = () => gw?.abort();
$('mic').onclick = async () => {
  if (!gw) return log('先连接 gateway', 'sys');
  try { if (gw.mic) gw.stopMic(); else await gw.startMic(); }
  catch (e) { log('⚠ ' + e.message, 'sys'); }
};

// ── 主循环 ────────────────────────────────────────────
let lastPad = '';
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  if (gw) body.setSpeakingLevel(gw.level());
  body.update();
  const k = body.mood.pad; const sig = `${k.p.toFixed(2)}${k.a.toFixed(2)}${k.d.toFixed(2)}`;
  if (sig !== lastPad) { lastPad = sig; padUI(); }
  renderer.render(scene, camera);
}
padUI();
loadModels();
animate();
// 供 Playwright 冒烟测试与控制台调试
window.__live = { body, get gw() { return gw; }, connect };
