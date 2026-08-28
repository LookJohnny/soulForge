/* SoulForge Live —— VRM 作为 gateway 的一个"身体"，完整陪伴应用壳。
   语音/记忆/PAD/关系/事件全部来自 gateway 真实管道；本页只负责：渲染、
   口型、PAD→表情、麦克风上行、HUD/气泡/事件卡/记忆图的呈现。 */

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { VrmBody } from '/studio/lib/vrm_body.js';
import { GatewayClient } from '/studio/lib/gateway_client.js';
import { MemoryGraph } from '/studio/lib/memory_graph.js';
import { BodyClient } from '/studio/lib/body_client.js';
import { buildHome } from '/studio/lib/home_props.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
// 宿主契约：Tauri 悬浮窗经 URL 参数或注入的 window.__SOULFORGE_HOST__ 声明透明/无 HUD
const host = {
  transparent: params.get('transparent') === '1',
  hud: params.get('hud') !== '0',
  ...(window.__SOULFORGE_HOST__ ?? {}),
};
if (!host.hud) document.documentElement.classList.add('no-hud');
if (host.transparent) document.documentElement.classList.add('transparent');
// 无边框悬浮窗：按住画布拖动窗口（Tauri 提供 start_drag）
if (window.__TAURI__?.core?.invoke && host.transparent) {
  document.getElementById('c').addEventListener('pointerdown', (e) => { if (e.button === 0 && !e.shiftKey) window.__TAURI__.core.invoke('start_drag').catch(() => {}); });
}

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
if (!host.transparent) scene.background = new THREE.Color(0x14121c);
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

// ── 舞台：多个角色同台（agent_id → VrmBody）。primary = 用户面前的那位（gateway 语音/PAD 绑定它）
const stage = new Map();
let primaryAgent = null;
const personaById = new Map();           // /api/characters 条目
const bodyFor = (agentId) => stage.get(agentId) ?? (agentId === primaryAgent || !primaryAgent ? body : null);
const STAGE_SLOTS = { 1: [0], 2: [-0.62, 0.62], 3: [-1.15, 0, 1.15], 4: [-1.6, -0.55, 0.55, 1.6] };
// 家的地图（与 engine/planner/space.py HOME 一致）：walk_to 的目的地；同一地点多人时错开站位
const PLACES = { sofa: { label: '客厅沙发', x: 0, z: 0.3 }, kitchen: { label: '厨房', x: -1.7, z: -0.4 }, desk: { label: '书桌', x: 1.5, z: 0 }, plants: { label: '阳台花架', x: 1.9, z: -1.3 } };
const slotOffset = (agentId) => { const ids = [...stage.keys()]; const i = ids.indexOf(agentId); return ids.length > 1 ? (i - (ids.length - 1) / 2) * 0.8 : 0; };
let home = null;
function ensureHome() {
  if (home || host.transparent) return;
  home = buildHome(scene, PLACES);
  scene.traverse((o) => { if (o.geometry?.type === 'CircleGeometry' && o.parent === scene) o.visible = false; }); // 单人圆盘让位给整间屋子
}
const placeLabels = new Map();
function ensurePlaceLabels() {
  if (placeLabels.size || !stage.size) return;
  for (const [id, pl] of Object.entries(PLACES)) {
    const el = document.createElement('div'); el.className = 'place-label'; el.textContent = pl.label; document.body.appendChild(el);
    placeLabels.set(id, el);
  }
}
// 镜头跟随：多人时机位缓慢跟着大家的重心走（他们会走去厨房/书桌）
const follow = { x: 0, z: 0 };
function followStage(dt) {
  if (stage.size < 2) return;
  let cx = 0, cz = 0, n = 0;
  for (const b of stage.values()) { cx += b.origin.x; cz += b.origin.z; n++; }
  if (!n) return;
  cx /= n; cz /= n;
  const k = 1 - Math.exp(-1.8 * dt);
  follow.x += (cx - follow.x) * k; follow.z += (cz - follow.z) * k;
  controls.target.x = follow.x; controls.target.z = follow.z - 0.2;
  camera.position.x = follow.x; camera.position.z = follow.z + 4.4;
}
function placePlaceLabels() {
  if (!placeLabels.size) return;
  const v = new THREE.Vector3();
  for (const [id, el] of placeLabels) {
    const pl = PLACES[id]; v.set(pl.x, 0.02, pl.z).project(camera);
    el.style.left = ((v.x + 1) * 50) + '%'; el.style.top = Math.min(84, (-v.y + 1) * 50) + '%';
    const here = [...stage].filter(([a]) => a).length;
    el.classList.toggle('hidden', v.z > 1 || here === 0);
  }
}
async function arrangeStage(agentIds) {
  // 第一位站在 primary 身体上（已加载），其余按人格 embodiment.model 各加载一具
  const ids = agentIds.length ? agentIds : [primaryAgent].filter(Boolean);
  if (!ids.length) return;
  primaryAgent = ids[0];
  for (const [id, b] of [...stage]) if (!ids.includes(id) && b !== body) { b.dispose(); scene.remove(b.gazeTarget); stage.delete(id); }
  stage.set(primaryAgent, body);
  for (const id of ids.slice(1)) {
    if (stage.has(id)) continue;
    const persona = personaById.get(id);
    const model = persona?.embodiment?.model;
    if (!model) { log(`角色 ${id} 没有 embodiment.model，无法上台`, 'sys'); continue; }
    const b = new VrmBody(scene, { height: persona.embodiment.target_height ?? 1.55, idleUrls: body.idleUrls, talkingUrl: body.talkingUrl });
    b.onLog = (m) => log(`[${persona.name}] ${m}`, 'sys');
    stage.set(id, b);
    try { await b.load(model, { kind: persona.embodiment.kind }); log(`${persona.name} 上台了`, 'sys'); }
    catch (e) { log(`${id} 模型加载失败: ${e.message}`, 'sys'); stage.delete(id); b.dispose(); }
  }
  // everyone starts on the sofa (engine default place) side by side; walk_to moves them from there
  const slots = STAGE_SLOTS[Math.min(4, stage.size)] ?? STAGE_SLOTS[4];
  [...stage.keys()].forEach((id, i) => { const b = stage.get(id); if (stage.size > 1) b.place(PLACES.sofa.x + slotOffset(id), PLACES.sofa.z); else b.place(slots[i] ?? 0, 0); });
  // 双人/群像：拉远成中景，视线高度略降
  controls.target.set(0, stage.size > 1 ? 1.0 : 1.05, 0);
  camera.position.set(0, stage.size > 1 ? 1.15 : 1.25, stage.size > 1 ? 3.2 + 1.0 * (stage.size - 1) : 2.6);
  controls.maxDistance = Math.max(5, 3.5 + stage.size);
  if (stage.size > 1) { ensurePlaceLabels(); ensureHome(); camera.position.set(0, 1.3, 4.6); controls.target.set(0, 0.95, -0.3); controls.enabled = false; }
}

async function loadAssets() {
  // idle/talking 动捕片段（assets/animations，来自 aikeya，MIT）
  try {
    const anims = await (await fetch('/api/animations')).json();
    animationsList.splice(0, animationsList.length, ...anims);
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
    const vrms = (list.models ?? list).filter((m) => ['vrm', 'glb', 'fbx', 'mmd'].includes(m.kind ?? 'vrm'));
    for (const m of vrms) {
      const o = document.createElement('option'); o.value = m.url; o.dataset.kind = m.kind; o.textContent = `${m.name ?? m.url.split('/').pop()} · ${(m.kind ?? 'vrm').toUpperCase()}${m.license ? ' · ' + m.license.slice(0, 24) : ''}`; sel.appendChild(o);
    }
    // 优先带完整表情的模型：aikeya utsuwa(VRM1) → VRoid 样例 → 其它
    const pref = params.get('model');
    const first = (pref && vrms.find((m) => m.url.includes(pref)))
      ?? vrms.find((m) => /AvatarSample_B/i.test(m.url)) ?? vrms.find((m) => /utsuwa/i.test(m.url)) ?? vrms[0];
    if (first) { sel.value = first.url; await pick(first.url); }
  } catch (e) { log('模型列表获取失败: ' + e.message, 'sys'); }
  sel.onchange = () => pick(sel.value, sel.selectedOptions[0]?.dataset.kind);
}
async function pick(url, kind) {
  try {
    await body.load(url, { kind: kind ?? $('model').selectedOptions[0]?.dataset.kind });
    if (!document.documentElement.dataset.persona) $('hud-name').textContent = decodeURIComponent(url.split('/').pop()).replace(/\.(vrm|glb|gltf|fbx|pmx)$/i, '');
    const a = body.vrm?.userData?.adapter;
    log('已换装 ' + decodeURIComponent(url.split('/').pop()) + (a ? `（${a.rig} 骨架 ${a.bones} 根，表情 ${a.expressions.length} 通道）` : ''), 'sys');
    if (a && a.expressions.length === 0) toast('这个模型没有表情 morph：只有身体动作和注视，不会有口型/表情');
    $('opt-toon').checked = !!body.toon;
  } catch (e) { log('模型加载失败: ' + e.message, 'sys'); toast('模型加载失败: ' + e.message, 6000); }
}
$('opt-idle').onchange = () => { const u = $('model').value; if (u) { loadAssets(); } };
$('opt-toon').onchange = () => body.setToon($('opt-toon').checked);

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
let typingTimer = 0;
const agentBubbles = new Map(); // 非 primary 角色各自的气泡 {el, until}
function showBubble(text, agentId = null) {
  if (agentId && agentId !== primaryAgent && stage.has(agentId)) {
    let bb = agentBubbles.get(agentId);
    if (!bb) {
      const el = document.createElement('div'); el.className = 'bubble agent-bubble';
      el.style.borderLeftColor = personaById.get(agentId)?.color ?? ''; document.body.appendChild(el);
      bb = { el, until: 0 }; agentBubbles.set(agentId, bb);
    }
    bb.el.textContent = text; bb.el.classList.remove('hidden'); bb.until = performance.now() + 6000 + text.length * 120;
    return;
  }
  $('bubble-text').textContent = text;
  $('bubble').classList.remove('hidden'); $('typing').classList.add('hidden');
  bubbleUntil = performance.now() + 6000 + text.length * 120;
}
function placeBubbles() {
  const set = (el, pos, dx, dy) => {
    if (!pos) { el.style.left = '58%'; el.style.top = '22%'; return; }
    el.style.left = Math.min(Math.max(pos.x + dx, 4), 70) + '%';
    el.style.top = Math.min(Math.max(pos.y + dy, 4), 70) + '%';
  };
  const pos = body.getHeadScreenPos(camera);
  set($('bubble'), pos, 4, -9); set($('typing'), pos, 2, -6);
  if (bubbleUntil && performance.now() > bubbleUntil && !gw?.speaking) { $('bubble').classList.add('hidden'); bubbleUntil = 0; }
  for (const [id, bb] of agentBubbles) {
    const b = stage.get(id);
    if (!b) { bb.el.remove(); agentBubbles.delete(id); continue; }
    set(bb.el, b.getHeadScreenPos(camera), 4, -9);
    if (bb.until && performance.now() > bb.until && !b.speaking) { bb.el.classList.add('hidden'); bb.until = 0; }
  }
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

/** The UI wears her colour: persona `color` → --soul. */
function setSoulColor(hex, name) {
  if (/^#[0-9a-f]{6}$/i.test(hex ?? '')) document.documentElement.style.setProperty('--soul', hex);
  if (name) { document.documentElement.dataset.persona = name; $('hud-name').textContent = name; }
}

// ── .soul 灵魂包：整角色（人格+音色+外观+表情）导出/导入 ──
async function loadSoulCharacters() {
  const sel = $('soul-char'); sel.innerHTML = '';
  try {
    const list = await (await fetch('/api/characters')).json();
    for (const c of (list.characters ?? list)) {
      personaById.set(c.id, c);
      const o = document.createElement('option'); o.value = c.id; o.textContent = `${c.name} (${c.id})`; sel.appendChild(o);
    }
    const first = (list.characters ?? list)[0]; if (first) setSoulColor(first.color, first.name);
    sel.onchange = () => { const c = (list.characters ?? list).find((c) => c.id === sel.value); if (c) setSoulColor(c.color, c.name); };
  } catch (e) { log('角色列表获取失败: ' + e.message, 'sys'); }
}
$('btn-soul-export').onclick = async () => {
  const id = $('soul-char').value; if (!id) return toast('没有可导出的角色');
  const pass = prompt('发布口令（留空 = 不加密，任何人可加载）：', '') ?? null;
  if (pass === null) return;
  try {
    const r = await fetch('/api/soul/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ character_id: id, passphrase: pass || null, include_model: true }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    const blob = await r.blob();
    const name = decodeURIComponent((r.headers.get('Content-Disposition') || '').match(/filename\*?=(?:UTF-8'')?"?([^";]+)/)?.[1] || `${id}.soul`);
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click();
    toast(`已导出 ${name}${pass ? '（口令加密）' : ''}`);
  } catch (e) { toast('导出 .soul 失败: ' + e.message, 6000); }
};
$('btn-soul-import').onclick = () => $('file-soul').click();
$('file-soul').onchange = async () => {
  const f = $('file-soul').files[0]; $('file-soul').value = ''; if (!f) return;
  try {
    const buf = new Uint8Array(await f.arrayBuffer());
    let b64 = ''; for (let i = 0; i < buf.length; i += 0x8000) b64 += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    b64 = btoa(b64);
    const head = await (await fetch('/api/soul/peek', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ soul_b64: b64 }) })).json();
    let passphrase = null;
    if (head.encrypted) { passphrase = prompt(`「${f.name}」需要发布口令：`); if (!passphrase) return; }
    const r = await fetch('/api/soul/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ soul_b64: b64, passphrase }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    toast(`已导入角色 ${j.name}（${j.id}）${j.model_url ? '，模型已安装' : ''}${j.ai_core ? '，已入库' : ''}`, 5000);
    await loadSoulCharacters(); $('soul-char').value = j.id;
    if (j.model_url) { await loadAssets(); const sel = $('model'); sel.value = j.model_url; if (sel.value === j.model_url) await pick(j.model_url, j.model_kind); }
  } catch (e) { toast('导入 .soul 失败: ' + e.message, 6000); }
};
loadSoulCharacters();

// ── Runtime Server /body（Protocol 0.2 web 身体）──────
let bodyClient = null;
const animationsList = [];
async function connectBody() {
  bodyClient?.close();
  const url = $('runtime').value.trim() || params.get('runtime');
  if (!url) { $('body-status').textContent = '未连接（可选）'; return; }
  const agentIds = ($('runtime-agents').value || params.get('agents') || '').split(',').map((x) => x.trim()).filter(Boolean);
  if (!personaById.size) await loadSoulCharacters();
  await arrangeStage(agentIds);
  // 台词：没有 gateway 时全部由本页念；有 gateway 时用户对话走 gateway，角色之间的对话仍由本页念
  const standalone = !gw;
  const speak = (text, agentId, cmd) => (standalone || isAgentTalk(cmd)) ? speakStandalone(text, agentId) : Promise.resolve();
  bodyClient = new BodyClient({ url, bodyId: 'web-vrm-live', agentIds, speech: true }).attach(bodyFor, { animations: animationsList, speak, places: PLACES, slotOffset });
  bodyClient.addEventListener('action', (e) => {
    const { cmd, prim } = e.detail;
    if (cmd.dialogue && (standalone || isAgentTalk(cmd))) { const n = personaById.get(cmd.agent_id)?.name ?? cmd.agent_id; log(`${n}: ${cmd.dialogue}`); showBubble(cmd.dialogue, cmd.agent_id); }
    if (isAgentTalk(cmd)) faceEachOther(cmd.agent_id, cmd.gaze_target, prim.duration_s);
    log(`▶ ${cmd.agent_id} ${cmd.name} → ${prim.kind}${prim.clip ? ':' + prim.clip : ''}`, 'sys');
  });
  bodyClient.addEventListener('welcome', (e) => { $('body-status').textContent = `身体已注册 ${e.detail.body_id} · ${(e.detail.accepted_agents ?? agentIds).join('+') || '全部'} · ${e.detail.supported_steps.length} 步`; log('runtime 已接入（web 身体）', 'sys'); });
  bodyClient.addEventListener('close', () => { $('body-status').textContent = '身体连接断开'; });
  bodyClient.addEventListener('error', () => { $('body-status').textContent = '身体连接失败'; });
  try { await bodyClient.connect(); } catch { /* status shown */ }
}
const isAgentTalk = (cmd) => !!cmd.gaze_target && cmd.gaze_target !== 'user' && stage.has(cmd.gaze_target);
let faceTimer = 0;
/** 两人对话：说话者看向对方，对方看回来并点头；结束后各自回到看观众。 */
function faceEachOther(speakerId, listenerId, seconds = 3) {
  const a = stage.get(speakerId), b = stage.get(listenerId);
  if (!a || !b) return;
  const ah = a.getHeadWorld(), bh = b.getHeadWorld();
  if (ah && bh) { a.lookAtPoint(bh); b.lookAtPoint(ah); b.nod?.(); }
  clearTimeout(faceTimer);
  faceTimer = setTimeout(() => { for (const x of stage.values()) x.lookAtPoint(null); }, (seconds + 2.5) * 1000);
}
/** 把两位角色拉进一场对话：`@luna @kai 今晚吃什么`（走 Runtime Server /control）。 */
function startConversation(a, b, topic = '') {
  const base = ($('runtime').value.trim() || params.get('runtime') || '').replace(/\/body\/?$/, '');
  if (!base) return toast('先连接 Runtime Server（⚙ 设置）');
  const ws = new WebSocket(base + '/control');
  ws.onopen = () => ws.send(JSON.stringify({ type: 'start_conversation', agents: [a, b], topic }));
  ws.onmessage = (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === 'conversation') { toast(`${personaById.get(a)?.name ?? a} 和 ${personaById.get(b)?.name ?? b} 聊起了「${m.topic}」`); ws.close(); }
    else if (m.type === 'error') { toast('无法开始对话: ' + m.error, 5000); ws.close(); }
  };
  ws.onerror = () => toast('连不上 Runtime Server /control');
}
let standaloneAudio = null;
const speakQueue = new Map(); // agent → promise chain，同一角色的台词按顺序念
async function speakStandalone(text, agentId = primaryAgent) {
  if (!text) return;
  const b = bodyFor(agentId) ?? body;
  const edge = personaById.get(agentId)?.voice?.edge ?? {};
  const voice = { provider: 'edge', id: edge.voice ?? 'zh-CN-XiaoxiaoNeural', rate: edge.rate ? Math.round((edge.rate - 100) * 0.5) : 0, pitch: 0 };
  const run = async () => {
    try {
      const res = await fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, voice }) });
      if (!res.ok) return;
      const url = URL.createObjectURL(await res.blob());
      await new Promise((resolve) => {
        const audio = new Audio(url); standaloneAudio = audio;
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const src = ctx.createMediaElementSource(audio); const an = ctx.createAnalyser(); an.fftSize = 256; src.connect(an); an.connect(ctx.destination);
        b.setAudioAnalyser(an); b.setSpeaking(true);
        const done = () => { b.setSpeaking(false); b.setAudioAnalyser(gw && b === body ? gw.analyser : null); URL.revokeObjectURL(url); standaloneAudio = null; resolve(); };
        audio.onended = audio.onerror = done; audio.play().catch(done);
      });
    } catch { /* TTS optional */ }
  };
  const chained = (speakQueue.get(agentId) ?? Promise.resolve()).then(run);
  speakQueue.set(agentId, chained);
  return chained;
}
$('connect-body').onclick = connectBody;
$('runtime').value = params.get('runtime') ?? '';
$('runtime-agents').value = params.get('agents') ?? '';
$('runtime-agents').placeholder = 'luna,kai';

// ── Gateway ───────────────────────────────────────────
let gw = null;
let reconnectTimer = null;
let reconnectTries = 0;
let lastErrorToast = 0;
const serverDefaults = { gateway_ws_url: '', runtime_ws_url: '' };
async function loadServerDefaults() {
  try { Object.assign(serverDefaults, await (await fetch('/api/status')).json()); } catch { /* optional */ }
  if (!$('gw').value) $('gw').placeholder = serverDefaults.gateway_ws_url || 'ws://localhost:8080/ws';
  if (!$('runtime').value && serverDefaults.runtime_ws_url) $('runtime').value = serverDefaults.runtime_ws_url;
}
async function connect() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  gw?.close();
  const url = $('gw').value.trim() || params.get('gateway') || serverDefaults.gateway_ws_url || `ws://${location.hostname}:8080/ws`;
  gw = new GatewayClient({ url, sessionName: 'vrm-live' });
  gw.addEventListener('open', (e) => { reconnectTries = 0; $('status').textContent = `已连接 ${e.detail.device_id}`; $('hud-stage').textContent = '已连接'; log('gateway 已连接', 'sys'); body.setAudioAnalyser(gw.analyser); });
  gw.addEventListener('close', () => {
    $('status').textContent = '连接断开，3 秒后重连…'; $('hud-stage').textContent = '未连接'; $('mic').classList.remove('on'); body.setAudioAnalyser(null);
    $('typing').classList.add('hidden'); body.setSpeaking(false);
    if (++reconnectTries > 5) { $('status').textContent = '连接断开（已停止重连，点"重新连接"）'; return; }
    if (!reconnectTimer) reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, 3000);
  });
  gw.addEventListener('error', (e) => {
    const d = e.detail;
    const m = d?.message ?? (d instanceof Event ? `连接 ${url} 失败` : String(d));
    log('⚠ ' + m, 'sys');
    if (Date.now() - lastErrorToast > 4000) { lastErrorToast = Date.now(); toast('⚠ ' + m); }
    $('typing').classList.add('hidden');
  });
  gw.addEventListener('sentence', (e) => { clearTimeout(typingTimer); log(e.detail.text); showBubble(e.detail.text); });
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
  gw.addEventListener('mic', (e) => { $('mic').classList.toggle('on', e.detail.on); if (e.detail.on) toast(`🎙 ${e.detail.native ?? e.detail.format ?? ''} 常听中（停顿约 1 秒断句）`); });
  try { await gw.ensureAudio(); await gw.connect(); }
  catch (e) { log('连接失败: ' + (e.message ?? e), 'sys'); $('status').textContent = '连接失败'; }
}

$('connect').onclick = connect;
$('chatbar').onsubmit = (e) => {
  e.preventDefault();
  const t = $('text').value.trim();
  if (!t) return;
  const at = [...t.matchAll(/@([\w-]+)/g)].map((m) => m[1]);
  if (at.length >= 2) { startConversation(at[0], at[1], t.replace(/@[\w-]+/g, '').trim()); log(t, 'user'); $('text').value = ''; return; }
  if (gw?.ws?.readyState === 1) { gw.sendText(t); }
  else if (gw) { toast('gateway 未连接，正在重连…'); connect(); return; }
  else if (bodyClient?.welcome) { bodyClient.sendUtterance(t); }
  else { toast('先连接 gateway 或 Runtime Server（⚙ 设置）'); return; }
  log(t, 'user'); $('text').value = '';
  $('typing').classList.remove('hidden'); $('bubble').classList.add('hidden');
  clearTimeout(typingTimer); typingTimer = setTimeout(() => { if (!$('typing').classList.contains('hidden')) { $('typing').classList.add('hidden'); toast('等了 40 秒没有回复——看看 gateway/ai-core 日志'); } }, 40000);
};
$('stop').onclick = () => gw?.abort();
$('mic').onclick = async () => {
  if (!gw) return toast('麦克风需要 gateway（语音链路）；无 gateway 时请用文字');
  try { if (gw.mic) gw.stopMic(); else await gw.startMic(); }
  catch (e) { toast('⚠ ' + e.message); }
};
$('btn-memory').onclick = () => $('memory-panel').classList.toggle('hidden');
$('btn-settings').onclick = () => $('settings-panel').classList.toggle('hidden');
document.querySelectorAll('[data-close]').forEach((b) => { b.onclick = () => $(b.dataset.close).classList.add('hidden'); });
$('gw').value = params.get('gateway') ?? '';

// ── 主循环 ────────────────────────────────────────────
let lastPad = '';
const followClock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  resizeIfNeeded();
  followStage(Math.min(0.1, followClock.getDelta()));
  controls.update();
  if (gw && !body.lipsync.analyser) body.setSpeakingLevel(gw.level());
  for (const b of stage.values()) if (b !== body) b.update();
  body.update();
  placeBubbles(); placePlaceLabels();
  const k = body.mood.pad; const sig = `${k.p.toFixed(2)}${k.a.toFixed(2)}${k.d.toFixed(2)}`;
  if (sig !== lastPad) { lastPad = sig; padUI(); }
  renderer.render(scene, camera);
}
padUI();
loadServerDefaults().then(loadAssets).then(() => {
  if (params.get('autoconnect') !== '0') connect();
  if (params.get('runtime') || $('runtime').value) connectBody();
});
animate();

// 供 Playwright 冒烟测试与控制台调试
window.__live = { stage,  body, camera, get gw() { return gw; }, get bodyClient() { return bodyClient; }, connect, connectBody, logs, renderRelationship, renderMood, showEvent, session, graph, refreshMemoryGraph };
