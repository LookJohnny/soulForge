/* SoulForge Live —— VRM 作为 gateway 的一个"身体"，完整陪伴应用壳。
   语音/记忆/PAD/关系/事件全部来自 gateway 真实管道；本页只负责：渲染、
   口型、PAD→表情、麦克风上行、HUD/气泡/事件卡/记忆图的呈现。 */

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { VrmBody } from '/studio/lib/vrm_body.js';
import { GatewayClient } from '/studio/lib/gateway_client.js';
import { MemoryGraph } from '/studio/lib/memory_graph.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const host = window.__SOULFORGE_HOST__ ?? { transparent: false }; // Tauri 悬浮窗预留钩子

// ── 日志 / toast ──────────────────────────────────────
const logs = [];
function log(text, cls = 'agent') {
  logs.push({ text, cls });
  const el = document.createElement('div');
  el.className = 'msg ' + cls; el.textContent = text;
  $('log').appendChild(el);
}
let toastTimer = 0;
function toast(text, ms = 2600) {
  const t = $('toast'); t.textContent = text; t.classList.remove('hidden');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hidden'), ms);
}

// ── 舞台 ──────────────────────────────────────────────
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: host.transparent, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(2, devicePixelRatio));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
if (host.transparent) renderer.setClearColor(0x000000, 0);
// WebGL 上下文丢失/恢复（aikeya）：不让页面死掉
canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); log('WebGL 上下文丢失', 'sys'); });
canvas.addEventListener('webglcontextrestored', () => log('WebGL 上下文已恢复', 'sys'));

const scene = new THREE.Scene();
if (!host.transparent) scene.background = new THREE.Color(0x0d0f14);
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
camera.position.set(0, 1.25, 2.6);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 1.05, 0);
controls.enableDamping = true; controls.enablePan = false;
controls.minDistance = 0.8; controls.maxDistance = 5;

const hemi = new THREE.HemisphereLight(0xfff4e0, 0x2a2438, 1.2); scene.add(hemi);
const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(1.5, 3, 2.5);
key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -0.0001;
Object.assign(key.shadow.camera, { left: -3, right: 3, top: 3, bottom: -3 });
scene.add(key);
const rim = new THREE.DirectionalLight(0x8ecae6, 0.8); rim.position.set(-2, 2, -2); scene.add(rim);
if (!host.transparent) {
  const ground = new THREE.Mesh(new THREE.CircleGeometry(2, 64), new THREE.ShadowMaterial({ opacity: 0.35 }));
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  const disc = new THREE.Mesh(new THREE.CircleGeometry(1.6, 64), new THREE.MeshStandardMaterial({ color: 0x151820, roughness: 1 }));
  disc.rotation.x = -Math.PI / 2; disc.position.y = -0.002; scene.add(disc);
}

// 渲染循环内 resize（与渲染同帧，避免黑闪；aikeya Scene.svelte）
let lastW = 0, lastH = 0;
function resizeIfNeeded() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (w !== lastW || h !== lastH) {
    lastW = w; lastH = h;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
}

// ── 身体 ──────────────────────────────────────────────
const body = new VrmBody(scene, { height: 1.55 });
body.onLog = (m) => log(m, 'sys');
body.mood.onChange = (k) => { const r = $('recipe'); if (r) r.textContent = k; };
canvas.addEventListener('pointermove', (e) => {
  const r = canvas.getBoundingClientRect();
  body.setGaze(((e.clientX - r.left) / r.width) * 2 - 1, ((e.clientY - r.top) / r.height) * 2 - 1);
});
canvas.addEventListener('pointerleave', () => body.setGaze(0, 0));

async function loadAssets() {
  // idle/talking 动捕片段（assets/animations，来自 aikeya，MIT）
  try {
    const anims = await (await fetch('/api/animations')).json();
    const byName = (re) => anims.filter((a) => re.test(a.url)).map((a) => a.url);
    body.idleUrls = $('opt-idle').checked ? byName(/\/idle(_\d+)?\.vrma$/) : [];
    body.talkingUrl = byName(/\/talking\.vrma$/)[0] ?? null;
    const sel = $('anim');
    for (const a of anims.filter((a) => /vrma_/.test(a.url))) {
      const o = document.createElement('option'); o.value = a.url; o.textContent = a.name; sel.appendChild(o);
    }
    sel.onchange = () => { if (sel.value) body.playVRMA(sel.value).catch((e) => log('动作失败: ' + e.message, 'sys')); sel.value = ''; };
  } catch (e) { log('动画列表获取失败: ' + e.message, 'sys'); }

  const sel = $('model');
  try {
    const list = await (await fetch('/api/models')).json();
    const vrms = (list.models ?? list).filter((m) => (m.kind ?? 'vrm') === 'vrm');
    for (const m of vrms) {
      const o = document.createElement('option'); o.value = m.url; o.textContent = m.name ?? m.url.split('/').pop(); sel.appendChild(o);
    }
    // 优先带完整表情的模型：aikeya utsuwa(VRM1) → VRoid 样例 → 其它
    const pref = params.get('model');
    const first = (pref && vrms.find((m) => m.url.includes(pref)))
      ?? vrms.find((m) => /utsuwa/i.test(m.url)) ?? vrms.find((m) => /AvatarSample_B/i.test(m.url)) ?? vrms[0];
    if (first) { sel.value = first.url; await pick(first.url); }
  } catch (e) { log('模型列表获取失败: ' + e.message, 'sys'); }
  sel.onchange = () => pick(sel.value);
}
async function pick(url) {
  try {
    await body.load(url);
    $('hud-name').textContent = decodeURIComponent(url.split('/').pop()).replace(/\.vrm$/i, '');
    log('已换装 ' + decodeURIComponent(url.split('/').pop()), 'sys');
  } catch (e) { log('模型加载失败: ' + e.message, 'sys'); }
}
$('opt-idle').onchange = () => { const u = $('model').value; if (u) { loadAssets(); } };

// ── HUD ───────────────────────────────────────────────
const AXES = [['affection', '好感', 1000], ['trust', '信任', 100], ['intimacy', '亲密', 100], ['comfort', '自在', 100], ['respect', '尊重', 100], ['energy', '精力', 100]];
const STAGE_ZH = { STRANGER: '陌生', ACQUAINTANCE: '认识', FRIEND: '朋友', CLOSE_FRIEND: '挚友', ROMANTIC_INTEREST: '心动', DATING: '交往', COMMITTED: '承诺', SOULMATE: '灵魂伴侣', COMPANION: '陪伴', FAMILIAR: '熟悉', BESTFRIEND: '挚友' };
function renderRelationship(r) {
  if (!r) return;
  $('hud-stage').textContent = (STAGE_ZH[r.stage] ?? r.stage) + (r.app_mode === 'companion' ? ' · 陪伴模式' : '');
  const axes = r.axes ?? {};
  $('hud-rel').innerHTML = AXES.filter(([k]) => k in axes).map(([k, zh, max]) => {
    const d = r.deltas?.[k] ?? 0;
    return `<div class="axis"><span>${zh}</span><span class="bar"><i style="width:${Math.min(100, (axes[k] / max) * 100)}%"></i></span><span class="delta ${d < 0 ? 'neg' : ''}">${d ? (d > 0 ? '+' : '') + d : ''}</span></div>`;
  }).join('');
  if (r.stage_changed) toast(`关系进入新阶段：${STAGE_ZH[r.stage] ?? r.stage}`);
}
function renderMood(e) {
  $('hud-emotion').textContent = e.emotion ? `情绪 · ${e.emotion}` : '';
  $('hud-causes').textContent = (e.causes ?? []).slice(0, 3).join('；');
}
function padUI() {
  const { p, a, d } = body.mood.pad;
  const bar = (v) => { const w = Math.abs(v) * 45; const left = v >= 0 ? 45 : 45 - w; return `<span class="bar"><i style="left:${left}px;width:${w}px"></i></span>`; };
  $('pad').innerHTML = `P${bar(p)}${p.toFixed(2)}<br>A${bar(a)}${a.toFixed(2)}<br>D${bar(d)}${d.toFixed(2)}<br>配方 <span id="recipe">${body.mood.key}</span>`;
}

// ── 气泡 ──────────────────────────────────────────────
let bubbleUntil = 0;
function showBubble(text) {
  $('bubble-text').textContent = text;
  $('bubble').classList.remove('hidden'); $('typing').classList.add('hidden');
  bubbleUntil = performance.now() + 6000 + text.length * 120;
}
function placeBubbles() {
  const pos = body.getHeadScreenPos(camera);
  const set = (el, dx, dy) => {
    if (!pos) { el.style.left = '58%'; el.style.top = '22%'; return; }
    el.style.left = Math.min(Math.max(pos.x + dx, 4), 70) + '%';
    el.style.top = Math.min(Math.max(pos.y + dy, 4), 70) + '%';
  };
  set($('bubble'), 4, -9); set($('typing'), 2, -6);
  if (bubbleUntil && performance.now() > bubbleUntil && !gw?.speaking) { $('bubble').classList.add('hidden'); bubbleUntil = 0; }
}

// ── 事件场景卡（Phase 4 后端就绪后自动生效）────────────
function showEvent(ev) {
  const box = $('event-overlay');
  const sc = ev.scene ?? {};
  box.innerHTML = `<div class="scene"><h3>${ev.name ?? ev.event_id}</h3>${sc.intro ? `<p class="muted">${sc.intro}</p>` : ''}<p>${sc.dialogue ?? ''}</p><div class="choices">${(sc.choices ?? []).map((c, i) => `<button data-i="${i}">${c.text}</button>`).join('')}</div></div>`;
  box.classList.remove('hidden');
  box.querySelectorAll('button').forEach((b) => { b.onclick = () => { gw?.send({ type: 'event_choice', event_id: ev.event_id, choice_index: +b.dataset.i }); box.classList.add('hidden'); }; });
  if (!(sc.choices ?? []).length) setTimeout(() => box.classList.add('hidden'), 6000);
}

// ── ai-core 数据（经 studio 代理）────────────────────
const session = { end_user_id: null, character_id: null };
const core = {
  async get(path) { const r = await fetch('/api/core/' + path); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText); return r.json(); },
  async send(method, path, body) { const r = await fetch('/api/core/' + path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }); if (!r.ok) throw new Error(r.statusText); return r.json(); },
};
const graph = new MemoryGraph($('memory-canvas'));
async function refreshMemoryGraph() {
  if (!session.end_user_id) { $('memory-hint').textContent = '连接后显示（需 ai-core）'; return; }
  try {
    const g = await core.get(`memory/graph?end_user_id=${session.end_user_id}&character_id=${session.character_id}`);
    graph.setData(g);
    $('memory-hint').classList.toggle('hidden', g.nodes.length > 0);
    $('memory-stats').textContent = `${g.nodes.length} 条记忆 · ${g.edges.length} 条关联 · ${g.source ?? ''}`;
  } catch (e) { $('memory-hint').textContent = '记忆图不可用: ' + e.message; $('memory-hint').classList.remove('hidden'); }
}
async function refreshNearEvents() {
  if (!session.end_user_id) return;
  try {
    const { near } = await core.get(`relationship/${session.end_user_id}/${session.character_id}/events/near`);
    $('near-events').textContent = near.length ? '快要发生：' + near.slice(0, 3).map((n) => `${n.name} ${n.progress}%`).join(' · ') : '';
  } catch { /* optional */ }
}
$('btn-memory-refresh').onclick = refreshMemoryGraph;
$('opt-companion').onchange = () => gw?.send({ type: 'set_app_mode', app_mode: $('opt-companion').checked ? 'companion' : 'dating_sim' });
$('btn-export').onclick = async () => {
  try {
    const data = await core.get(`relationship/${session.end_user_id}/${session.character_id}/export`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `soulforge-save-${new Date().toISOString().slice(0, 10)}.json`; a.click();
    toast('存档已导出');
  } catch (e) { toast('导出失败: ' + e.message); }
};
$('btn-import').onclick = () => $('file-import').click();
$('file-import').onchange = async () => {
  const f = $('file-import').files[0]; if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    const mode = confirm('覆盖当前进度？（取消 = 合并）') ? 'replace' : 'merge';
    const r = await core.send('POST', `relationship/${session.end_user_id}/${session.character_id}/import`, { ...data, mode });
    if (r.relationship) renderRelationship(r.relationship);
    toast(`已导入（${mode}）`); refreshMemoryGraph();
  } catch (e) { toast('导入失败: ' + e.message); }
  $('file-import').value = '';
};

// ── Gateway ───────────────────────────────────────────
let gw = null;
async function connect() {
  gw?.close();
  const url = $('gw').value.trim() || params.get('gateway') || `ws://${location.hostname}:8080/ws`;
  gw = new GatewayClient({ url, sessionName: 'vrm-live' });
  gw.addEventListener('open', (e) => { $('status').textContent = `已连接 ${e.detail.device_id}`; $('hud-stage').textContent = '已连接'; log('gateway 已连接', 'sys'); body.setAudioAnalyser(gw.analyser); });
  gw.addEventListener('close', () => { $('status').textContent = '连接断开'; $('hud-stage').textContent = '未连接'; $('mic').classList.remove('on'); body.setAudioAnalyser(null); });
  gw.addEventListener('error', (e) => { const m = e.detail?.message ?? String(e.detail); log('⚠ ' + m, 'sys'); toast('⚠ ' + m); });
  gw.addEventListener('sentence', (e) => { log(e.detail.text); showBubble(e.detail.text); });
  gw.addEventListener('speaking', (e) => { body.setSpeaking(e.detail.speaking); if (!e.detail.speaking) { bubbleUntil = performance.now() + 2500; setTimeout(() => { refreshMemoryGraph(); refreshNearEvents(); }, 4000); } });
  gw.addEventListener('emotion', (e) => { body.setPad(e.detail.pad); renderMood(e.detail); padUI(); });
  gw.addEventListener('control:session', (e) => {
    session.end_user_id = e.detail.end_user_id; session.character_id = e.detail.character_id;
    if (e.detail.character_name) $('hud-name').textContent = e.detail.character_name;
    const ok = !!(session.end_user_id && session.character_id);
    $('btn-export').disabled = !ok; $('btn-import').disabled = !ok;
    if (ok) { refreshMemoryGraph(); refreshNearEvents(); }
  });
  gw.addEventListener('control:relationship', (e) => { renderRelationship(e.detail); $('opt-companion').checked = e.detail.app_mode === 'companion'; });
  gw.addEventListener('control:event', (e) => showEvent(e.detail));
  gw.addEventListener('mic', (e) => $('mic').classList.toggle('on', e.detail.on));
  try { await gw.ensureAudio(); await gw.connect(); }
  catch (e) { log('连接失败: ' + (e.message ?? e), 'sys'); $('status').textContent = '连接失败'; }
}

$('connect').onclick = connect;
$('chatbar').onsubmit = (e) => {
  e.preventDefault();
  const t = $('text').value.trim();
  if (!t || !gw) return;
  log(t, 'user'); gw.sendText(t); $('text').value = '';
  $('typing').classList.remove('hidden'); $('bubble').classList.add('hidden');
};
$('stop').onclick = () => gw?.abort();
$('mic').onclick = async () => {
  if (!gw) return toast('先连接 gateway');
  try { if (gw.mic) gw.stopMic(); else await gw.startMic(); }
  catch (e) { toast('⚠ ' + e.message); }
};
$('btn-memory').onclick = () => $('memory-panel').classList.toggle('hidden');
$('btn-settings').onclick = () => $('settings-panel').classList.toggle('hidden');
document.querySelectorAll('[data-close]').forEach((b) => { b.onclick = () => $(b.dataset.close).classList.add('hidden'); });
$('gw').value = params.get('gateway') ?? '';

// ── 主循环 ────────────────────────────────────────────
let lastPad = '';
function animate() {
  requestAnimationFrame(animate);
  resizeIfNeeded();
  controls.update();
  if (gw && !body.lipsync.analyser) body.setSpeakingLevel(gw.level());
  body.update();
  placeBubbles();
  const k = body.mood.pad; const sig = `${k.p.toFixed(2)}${k.a.toFixed(2)}${k.d.toFixed(2)}`;
  if (sig !== lastPad) { lastPad = sig; padUI(); }
  renderer.render(scene, camera);
}
padUI();
loadAssets().then(() => { if (params.get('autoconnect') !== '0') connect(); });
animate();

// 供 Playwright 冒烟测试与控制台调试
window.__live = { body, camera, get gw() { return gw; }, connect, logs, renderRelationship, renderMood, showEvent, session, graph, refreshMemoryGraph };
