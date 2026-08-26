/* SoulForge Studio — 人格 × 音色 × 模型 自由组合的对话工作台。

   渲染层已收敛到 lib/vrm_body.js（与 /live 同一份身体）：idle 动捕轮换、
   注视眼先头后、PAD 情绪→表情、五视素口型、VRMA 表演。Studio 自己只保留：
   决策面板、人格/音色编辑、机器人 GLB（RobotExpressive）的一个小壳、
   Web Speech 麦克风与 barge-in。 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { VrmBody } from '/studio/lib/vrm_body.js';
import { PERFORMANCE_TO_CLIP } from '/studio/lib/action_map.js';

/* ────────────────────────── state ────────────────────────── */
const state = {
  characters: null,
  models: [],
  voices: { fish: [], edge: [] },
  animations: [],
  agentId: 'luna',
  modelUrl: null,
  currentAudio: null,
  busy: false,
  linked: false,
};

const $ = (id) => document.getElementById(id);

/* ────────────────────────── three stage ────────────────────────── */
const canvas = $('stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(2, devicePixelRatio));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
canvas.addEventListener('webglcontextlost', (e) => e.preventDefault());

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 50);
camera.position.set(0, 1.32, 2.9);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 1.05, 0);
controls.enableDamping = true;
controls.enablePan = false;
controls.minDistance = 1.2;
controls.maxDistance = 6;

const key = new THREE.DirectionalLight(0xffe2b0, 1.15);
key.position.set(1.5, 3, 2.5);
scene.add(key);
const rim = new THREE.DirectionalLight(0x63e6c8, 0.5);
rim.position.set(-2, 2, -2);
scene.add(rim);
scene.add(new THREE.HemisphereLight(0xfff2dc, 0x1e2230, 0.7));
const ground = new THREE.Mesh(
  new THREE.CircleGeometry(1.4, 64),
  new THREE.MeshStandardMaterial({ color: 0x11141c, roughness: 0.95, metalness: 0 }),
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground);
const halo = new THREE.Mesh(
  new THREE.RingGeometry(1.18, 1.24, 96),
  new THREE.MeshBasicMaterial({ color: 0xe8b34b, transparent: true, opacity: 0.35, side: THREE.DoubleSide }),
);
halo.rotation.x = -Math.PI / 2;
halo.position.y = 0.012;
scene.add(halo);

let lastW = 0, lastH = 0;
function resizeIfNeeded() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  if (w === lastW && h === lastH) return;
  lastW = w; lastH = h;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

/* ────────────────────────── bodies ──────────────────────────
   VRM → VrmBody（共享库）。RobotExpressive GLB → RobotBody（只在 studio 用）。 */
const body = new VrmBody(scene, { height: 1.55 });
canvas.parentElement.addEventListener('pointermove', (e) => {
  const r = canvas.getBoundingClientRect();
  body.setGaze(((e.clientX - r.left) / r.width) * 2 - 1, ((e.clientY - r.top) / r.height) * 2 - 1);
});
canvas.parentElement.addEventListener('pointerleave', () => body.setGaze(0, 0));

class RobotBody {
  constructor() { this.root = null; this.mixer = null; this.clips = []; this.loader = new GLTFLoader(); }
  async load(url) {
    this.dispose();
    const gltf = await this.loader.loadAsync(url);
    const root = gltf.scene;
    root.traverse((o) => { o.frustumCulled = false; });
    const box = new THREE.Box3().setFromObject(root);
    root.scale.setScalar(1.05 / Math.max(0.1, box.getSize(new THREE.Vector3()).y));
    root.position.y = -new THREE.Box3().setFromObject(root).min.y;
    scene.add(root);
    this.root = root; this.mixer = new THREE.AnimationMixer(root); this.clips = gltf.animations;
    const idle = this.clips.find((c) => c.name === 'Idle');
    if (idle) this.mixer.clipAction(idle).play();
  }
  perform(name) {
    const map = { dance: 'Dance', wave: 'Wave', spin: 'Jump', stretch: 'ThumbsUp', bow: 'Yes', clap: 'ThumbsUp', jump: 'Jump', think: 'Idle', look_around: 'Idle' };
    const clip = this.clips.find((c) => c.name === (map[name] ?? 'Dance'));
    if (!clip || !this.mixer) return;
    const action = this.mixer.clipAction(clip);
    action.reset(); action.setLoop(name === 'dance' ? THREE.LoopRepeat : THREE.LoopOnce, 3); action.clampWhenFinished = false;
    action.fadeIn(0.2).play();
    setTimeout(() => action.fadeOut(0.4), (name === 'dance' ? 6 : 3) * 1000);
  }
  update(dt) { this.mixer?.update(dt); }
  dispose() { if (this.root) scene.remove(this.root); this.root = null; this.mixer = null; this.clips = []; }
}
const robot = new RobotBody();
const robotClock = new THREE.Clock();

async function loadModel(url, kind) {
  $('cap-detail').textContent = '召唤中…';
  try {
    if (kind === 'robot') {
      body.dispose();
      await robot.load(url);
      controls.target.set(0, 0.55, 0); camera.position.set(0, 0.8, 2.4);
    } else {
      robot.dispose();
      await body.load(url);
      controls.target.set(0, 1.05, 0); camera.position.set(0, 1.32, 2.9);
    }
    $('cap-detail').textContent = decodeURIComponent(url.split('/').pop());
  } catch (err) {
    $('cap-detail').textContent = `模型加载失败：${err.message ?? err}`;
  }
}

async function playVRMA(url) {
  if (!body.vrm) return;
  try { await body.playVRMA(url); } catch (e) { addMsg('agent', `⚠ ${e.message}`, 'system'); }
}

function animate() {
  requestAnimationFrame(animate);
  resizeIfNeeded();
  controls.update();
  halo.material.opacity = 0.28 + 0.1 * Math.sin(performance.now() / 1000 * 1.4);
  body.update();
  robot.update(robotClock.getDelta());
  renderer.render(scene, camera);
}

/* ────────────────────────── boot ────────────────────────── */
async function boot() {
  animate();
  const [status, characters, models, voices, animations] = await Promise.all([
    fetch('/api/status').then((r) => r.json()),
    fetch('/api/characters').then((r) => r.json()),
    fetch('/api/models').then((r) => r.json()),
    fetch('/api/voices').then((r) => r.json()),
    fetch('/api/animations').then((r) => r.json()),
  ]);
  state.animations = animations;
  // idle/talking 动捕片段交给 VrmBody；表演类 VRMA 列在动作面板
  body.idleUrls = animations.filter((a) => /\/idle(_\d+)?\.vrma$/.test(a.url)).map((a) => a.url);
  body.talkingUrl = animations.find((a) => /\/talking\.vrma$/.test(a.url))?.url ?? null;
  const performances = animations.filter((a) => /vrma_/.test(a.url));
  $('anim-grid').innerHTML = performances.map((a) => `
    <div class="model-card" data-anim="${a.url}"><span class="tag">VRMA</span>
      <b>${a.name}</b><i>点击播放</i></div>`).join('')
    || '<div class="hint">把 .vrma 文件放进 assets/animations/ 即出现在这里</div>';
  for (const card of document.querySelectorAll('#anim-grid .model-card')) {
    card.onclick = () => playVRMA(card.dataset.anim);
  }
  state.characters = characters;
  state.models = models;
  state.voices = voices;

  const statusEl = $('status');
  state.linked = Boolean(status.linked_runtime);
  if (state.linked) {
    statusEl.textContent = `⬖ 联动：${status.linked_runtime} · Studio 为语音身体（人格由中枢托管）`;
    for (const id of ['p-name', 'p-archetype', 'p-traits', 'p-goals', 'p-comfort', 'p-energy']) {
      $(id).disabled = true;
    }
  } else if (status.llm_is_mock) {
    statusEl.textContent = '⬖ 决策：规则 Mock（配 DEEPSEEK_API_KEY 可接真 LLM）';
    statusEl.classList.add('warn');
  } else {
    statusEl.textContent = `⬖ 决策：${status.llm} · 在线`;
  }

  const agentSelect = $('agent-select');
  agentSelect.innerHTML = characters.characters
    .map((c) => `<option value="${c.id}">${c.name} · ${c.role_label ?? c.archetype}</option>`)
    .join('');
  agentSelect.onchange = () => selectAgent(agentSelect.value);

  const archetypes = Object.keys(characters.archetypes ?? {}).filter((k) => !k.startsWith('$'));
  $('p-archetype').innerHTML = archetypes.map((a) => `<option value="${a}">${a}</option>`).join('');

  const providerSelect = $('v-provider');
  providerSelect.innerHTML = [
    voices.fish_available ? '<option value="fish">fish.audio · 真人级</option>' : '',
    '<option value="edge">Edge TTS · 神经语音</option>',
  ].join('');
  providerSelect.onchange = fillVoices;

  $('model-grid').innerHTML = models.map((m, i) => `
    <div class="model-card" data-url="${m.url}" data-kind="${m.kind}" id="model-${i}">
      <span class="tag">${m.kind.toUpperCase()}</span>
      <b>${m.name}</b><i>${m.size_mb} MB</i>
    </div>`).join('');
  for (const card of document.querySelectorAll('#model-grid .model-card')) {
    card.onclick = () => {
      document.querySelectorAll('#model-grid .model-card').forEach((c) => c.classList.remove('active'));
      card.classList.add('active');
      state.modelUrl = card.dataset.url;
      loadModel(card.dataset.url, card.dataset.kind);
    };
  }

  $('p-energy').oninput = () => { $('p-energy-val').textContent = $('p-energy').value; };
  $('v-rate').oninput = () => { $('v-rate-val').textContent = $('v-rate').value; };
  $('v-preview').onclick = previewVoice;
  $('chat-form').onsubmit = onChat;
  setupMic();

  selectAgent(characters.characters[0].id);
}

function characterOf(id) {
  return state.characters.characters.find((c) => c.id === id);
}

function selectAgent(agentId) {
  state.agentId = agentId;
  const c = characterOf(agentId);
  $('p-name').value = c.name;
  $('p-archetype').value = c.archetype;
  $('p-traits').value = (c.traits ?? []).join(', ');
  $('p-goals').value = (c.daily_goals ?? []).join(', ');
  $('p-comfort').value = c.comfort_line ?? '';
  $('p-energy').value = c.energy ?? 0.8;
  $('p-energy-val').textContent = $('p-energy').value;
  $('cap-name').textContent = c.name;
  fillVoices(c);

  const embodiment = c.embodiment?.model ?? '';
  const match = state.models.findIndex((m) => embodiment.endsWith(m.url.split('/').pop()));
  const index = match >= 0 ? match : 0;
  document.querySelectorAll('#model-grid .model-card').forEach((el) => el.classList.remove('active'));
  const card = $(`model-${index}`);
  if (card) { card.classList.add('active'); loadModel(card.dataset.url, card.dataset.kind); }
}

function fillVoices(character) {
  const provider = $('v-provider').value || (state.voices.fish_available ? 'fish' : 'edge');
  const voiceSelect = $('v-voice');
  const c = character?.id ? character : characterOf(state.agentId);
  if (provider === 'fish') {
    voiceSelect.innerHTML = state.voices.fish
      .map((v) => `<option value="${v.id}" data-speed="${v.speed}">${v.label}</option>`).join('');
    const own = c?.voice?.fish?.reference_id;
    if (own) voiceSelect.value = own;
  } else {
    voiceSelect.innerHTML = state.voices.edge
      .map((v) => `<option value="${v.id}">${v.label}</option>`).join('');
    const own = c?.voice?.edge?.voice;
    if (own && state.voices.edge.some((v) => v.id === own)) voiceSelect.value = own;
  }
}

/* ────────────────────────── persona + voice payloads ────────────────────────── */
function personaOverrides() {
  return {
    name: $('p-name').value.trim(),
    archetype: $('p-archetype').value,
    traits: $('p-traits').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    daily_goals: $('p-goals').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    comfort_line: $('p-comfort').value.trim(),
    energy: Number($('p-energy').value),
  };
}

function voiceConfig() {
  const provider = $('v-provider').value;
  const voiceSelect = $('v-voice');
  const rate = Number($('v-rate').value);
  if (provider === 'fish') {
    const speed = Number(voiceSelect.selectedOptions[0]?.dataset.speed ?? 1) * (1 + rate / 100);
    return { provider: 'fish', id: voiceSelect.value, speed: Number(speed.toFixed(2)) };
  }
  return { provider: 'edge', id: voiceSelect.value, rate, pitch: 0 };
}

/* ────────────────────────── chat ────────────────────────── */
// 决策里的情绪线索 → PAD（VrmBody 再阻尼成表情/头姿）
const MOOD_PAD = {
  playful: { p: 0.6, a: 0.5, d: 0.3 },
  warm: { p: 0.45, a: -0.1, d: 0.1 },
  comfort: { p: 0.3, a: -0.3, d: 0.0 },
  neutral: { p: 0.1, a: 0.0, d: 0.05 },
};

async function onChat(event) {
  event.preventDefault();
  if (state.busy) return;
  const input = $('chat-text');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMsg('user', text);
  state.busy = true;
  $('chat-send').disabled = true;
  try {
    const res = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: state.agentId, text, persona: personaOverrides() }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    addMsg('agent', data.reply, personaOverrides().name || state.agentId);
    renderDecision(data);
    updateRelationship(data.relationship_user);
    triggerPerformance(data.actions ?? []);
    const style = (data.decision?.reason ?? '') + (data.decision?.intent ?? '');
    const mood = style.includes('perform') || style.includes('playful') ? 'playful'
      : style.includes('comfort') ? 'comfort' : style.includes('warm') ? 'warm' : 'neutral';
    body.setPad(MOOD_PAD[mood]);
    await speak(data.reply);
  } catch (err) {
    addMsg('agent', `⚠ ${err.message ?? err}`, 'system');
  } finally {
    state.busy = false;
    $('chat-send').disabled = false;
    input.focus();
  }
}

function addMsg(side, text, who = '') {
  $('chat-hint')?.remove();
  const log = $('chat-log');
  const el = document.createElement('div');
  el.className = `msg ${side}`;
  el.innerHTML = side === 'agent'
    ? `<span class="who">${who}</span>${escapeHtml(text)}`
    : escapeHtml(text);
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
}

function renderDecision(data) {
  const d = data.decision ?? {};
  const memory = Object.entries(data.memory ?? {}).slice(-3)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`).join('<br/>') || '—';
  $('decision').innerHTML = `
    <div class="card">
      <div class="row"><span class="k">IMPACT</span>
        <span class="v impact-${d.impact ?? 'LOW'}">${d.impact ?? '—'} · ${d.scope ?? ''}</span></div>
      <div class="row"><span class="k">意图</span><span class="v">${d.intent ?? '—'}</span></div>
      <div class="row"><span class="k">情绪解读</span><span class="v">${d.emotional_read || '—'}</span></div>
      <div class="row"><span class="k">理由</span><span class="v">${escapeHtml(d.reason ?? '—')}</span></div>
      <div class="row"><span class="k">近期记忆</span><span class="v">${memory}</span></div>
      <div class="row"><span class="k">决策引擎</span><span class="v">${data.llm}</span></div>
    </div>`;
}

function updateRelationship(value) {
  if (typeof value !== 'number') return;
  $('rel-fill').style.width = `${Math.round(value * 100)}%`;
  $('rel-val').textContent = value.toFixed(2);
}

/* ────────────────────────── action performance ──────────────────────────
   决策带的微动作 → 身体真的做出来。VRM 走动捕 VRMA（action_map 的同一张表），
   机器人走自带 GLTF clip。 */
function triggerPerformance(actions) {
  let name = null;
  for (const action of actions) {
    if (action.params?.performance) { name = action.params.performance; break; }
    if (PERFORMANCE_TO_CLIP[action.name]) { name = action.name; break; }
  }
  if (!name) return;
  if (robot.root) { robot.perform(name); return; }
  const clip = PERFORMANCE_TO_CLIP[name];
  const asset = clip && state.animations.find((a) => a.url.toLowerCase().includes(`vrma_${clip}`.toLowerCase()));
  if (asset) playVRMA(asset.url);
}

/* ────────────────────────── mic input + barge-in ──────────────────────────
   Web Speech API (Chrome, zh-CN, needs network). 她说话时你一开口 → 停播 →
   回声过滤 → 新决策。 */
let recognition = null;
let micOn = false;
let lastSpokenReply = '';

function setupMic() {
  const button = $('mic-btn');
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    button.classList.add('unsupported');
    button.title = '此浏览器不支持 Web Speech API（请用 Chrome）';
    return;
  }
  button.onclick = () => (micOn ? stopMic() : startMic(SR));
}

function startMic(SR) {
  recognition = new SR();
  recognition.lang = 'zh-CN';
  recognition.continuous = true;
  recognition.interimResults = true;
  const input = $('chat-text');

  recognition.onresult = (event) => {
    const result = event.results[event.results.length - 1];
    const transcript = result[0].transcript.trim();
    if (state.currentAudio && !state.currentAudio.paused) {
      state.currentAudio.pause();
      addMsg('agent', '（她停下来，听你说。）', 'system');
    }
    input.value = transcript;
    if (result.isFinal && transcript) {
      if (lastSpokenReply && transcript.replace(/[，。！？\s]/g, '')
          === lastSpokenReply.replace(/[，。！？\s]/g, '')) {
        input.value = '';
        return;
      }
      $('chat-form').requestSubmit();
    }
  };
  recognition.onerror = (event) => {
    if (event.error !== 'no-speech') {
      addMsg('agent', `⚠ 语音识别：${event.error}`, 'system');
      stopMic();
    }
  };
  recognition.onend = () => { if (micOn) recognition.start(); };
  recognition.start();
  micOn = true;
  $('mic-btn').classList.add('live');
}

function stopMic() {
  micOn = false;
  recognition?.stop();
  recognition = null;
  $('mic-btn').classList.remove('live');
}

/* ────────────────────────── tts + lipsync ────────────────────────── */
let audioContext = null;

async function speak(text) {
  if (!text || text.startsWith('（')) return;
  lastSpokenReply = text;
  const res = await fetch('/api/tts', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice: voiceConfig() }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    addMsg('agent', `⚠ 语音失败：${err.error ?? res.status}`, 'system');
    return;
  }
  const fallback = res.headers.get('X-TTS-Fallback');
  if (fallback) addMsg('agent', `ℹ ${decodeURIComponent(fallback)}`, 'system');
  const blob = await res.blob();
  await playWithLipsync(URL.createObjectURL(blob));
}

async function previewVoice() {
  const button = $('v-preview');
  button.disabled = true;
  try { await speak('你好呀，我是这个声音，喜欢吗？'); }
  finally { button.disabled = false; }
}

function playWithLipsync(url) {
  return new Promise((resolve) => {
    const audio = new Audio(url);
    audioContext ??= new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaElementSource(audio);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(audioContext.destination);
    body.setAudioAnalyser(analyser);
    body.setSpeaking(true);
    state.currentAudio = audio;
    const finish = () => {
      body.setSpeaking(false);
      body.setAudioAnalyser(null);
      state.currentAudio = null;
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onended = audio.onerror = audio.onpause = finish;
    audio.play().catch(finish);
  });
}

window.__studio = { body, robot, state };
boot();
