import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName } from '@pixiv/three-vrm';
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from '@pixiv/three-vrm-animation';

/* ────────────────────────── state ────────────────────────── */
const state = {
  characters: null,
  models: [],
  voices: { fish: [], edge: [] },
  agentId: 'luna',
  modelUrl: null,
  currentVrm: null,
  currentRobot: null,
  mixer: null,
  speakingLevel: 0,
  audioAnalyser: null,
  currentAudio: null,
  busy: false,
  linked: false,
};

const $ = (id) => document.getElementById(id);

/* ────────────────────────── three stage ────────────────────────── */
const canvas = $('stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.95;

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.05).texture;

const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 50);
camera.position.set(0, 1.32, 2.9);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 1.05, 0);
controls.enableDamping = true;
controls.minDistance = 1.2;
controls.maxDistance = 6;
controls.maxPolarAngle = Math.PI * 0.55;

const key = new THREE.DirectionalLight(0xffe2b0, 1.15);
key.position.set(-1.6, 2.6, 2.2);
scene.add(key);
const rim = new THREE.DirectionalLight(0x63e6c8, 0.5);
rim.position.set(2.2, 1.6, -2.4);
scene.add(rim);
scene.add(new THREE.HemisphereLight(0xcfe4ff, 0x2a1e12, 0.35));

const ground = new THREE.Mesh(
  new THREE.CircleGeometry(1.6, 72),
  new THREE.MeshStandardMaterial({ color: 0x10151f, roughness: 0.85, metalness: 0.1 }),
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

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));

/* ── VRMA 动作播放（动捕级动画替代程序化大动作）──
   独立加载器：animation 插件与 VRM0 模型解析在同一 loader 上会冲突 */
const vrmaLoader = new GLTFLoader();
vrmaLoader.register((parser) => new VRMAnimationLoaderPlugin(parser));
const vrmaCache = new Map();
let vrmMixer = null;
let vrmaAction = null;
let vrmaUntil = 0;

async function playVRMA(url) {
  const vrm = state.currentVrm;
  if (!vrm) return;
  let vrmAnimation = vrmaCache.get(url);
  if (!vrmAnimation) {
    const gltf = await vrmaLoader.loadAsync(url);
    vrmAnimation = gltf.userData.vrmAnimations?.[0];
    if (!vrmAnimation) { addMsg('agent', '⚠ 该文件不含 VRMA 动画', 'system'); return; }
    vrmaCache.set(url, vrmAnimation);
  }
  const animClip = createVRMAnimationClip(vrmAnimation, vrm);
  vrmMixer = new THREE.AnimationMixer(vrm.scene);
  vrmaAction = vrmMixer.clipAction(animClip);
  vrmaAction.setLoop(THREE.LoopOnce, 1);
  vrmaAction.clampWhenFinished = false;
  vrmaAction.play();
  vrmaUntil = clock.elapsedTime + animClip.duration;
  state.performance = null;             // 程序化表演让位于动捕数据
}

async function loadModel(url, kind) {
  disposeCurrent();
  $('cap-detail').textContent = '召唤中…';
  try {
    const gltf = await loader.loadAsync(url);
    if (kind !== 'robot' && gltf.userData.vrm) {
      const vrm = gltf.userData.vrm;
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
      VRMUtils.rotateVRM0(vrm);
      vrm.scene.traverse((o) => { o.frustumCulled = false; });
      normalize(vrm.scene, 1.55);
      scene.add(vrm.scene);
      state.currentVrm = vrm;
      const gaze = new THREE.Object3D();
      gaze.position.set(0, 1.35, 2.5);
      scene.add(gaze);
      if (vrm.lookAt) vrm.lookAt.target = gaze;
      controls.target.set(0, 1.05, 0);
      camera.position.set(0, 1.32, 2.9);
    } else {
      const root = gltf.scene;
      root.traverse((o) => { o.frustumCulled = false; });
      normalize(root, 1.05);
      scene.add(root);
      controls.target.set(0, 0.55, 0);
      camera.position.set(0, 0.8, 2.4);
      state.currentRobot = root;
      state.mixer = new THREE.AnimationMixer(root);
      state.robotClips = gltf.animations;
      const idle = gltf.animations.find((c) => c.name === 'Idle');
      if (idle) state.mixer.clipAction(idle).play();
    }
    $('cap-detail').textContent = decodeURIComponent(url.split('/').pop());
  } catch (err) {
    $('cap-detail').textContent = `模型加载失败：${err.message ?? err}`;
  }
}

function normalize(root, targetHeight) {
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  root.scale.setScalar(targetHeight / Math.max(0.1, size.y));
  const scaled = new THREE.Box3().setFromObject(root);
  root.position.y = -scaled.min.y;
  root.userData.floorY = root.position.y;
}

function disposeCurrent() {
  if (state.currentVrm) { scene.remove(state.currentVrm.scene); VRMUtils.deepDispose(state.currentVrm.scene); }
  if (state.currentRobot) scene.remove(state.currentRobot);
  state.currentVrm = null;
  state.currentRobot = null;
  state.mixer = null;
}

const clock = new THREE.Clock();

/* ── AliveDriver：借鉴 Ani 式“灵动”的分层生命感 ─────────────────────────
   层1 呼吸/重心（慢正弦） 层2 阻尼头部+眼睛鼠标追踪（快阻尼，眼先头后）
   层3 随机小动作 fidget（6-12s 一次，包络进出） 层4 情绪渗透姿态与表情
   所有通道走指数阻尼——没有任何姿态是瞬间到位的。 */
const alive = {
  head: { x: 0, y: 0, z: 0 }, headT: { x: 0, y: 0, z: 0 },
  gaze: new THREE.Vector2(0, 0),            // 鼠标在舞台的归一位置
  mood: { name: 'neutral', level: 0 },      // level 随时间衰减
  nextFidget: 3, fidget: null,              // {name,start,dur}
  nextBlink: 2.5, blinking: 0, doubleBlink: false,
};
const damp = (cur, target, lambda, dt) => cur + (target - cur) * (1 - Math.exp(-lambda * dt));

canvas.parentElement.addEventListener('pointermove', (e) => {
  const r = canvas.getBoundingClientRect();
  alive.gaze.set(((e.clientX - r.left) / r.width) * 2 - 1,
                 ((e.clientY - r.top) / r.height) * 2 - 1);
});
canvas.parentElement.addEventListener('pointerleave', () => alive.gaze.set(0, 0));

const FIDGETS = ['glance_left', 'glance_right', 'tilt', 'weight', 'chin_up'];

function aliveIdle(vrm, t, dt, breath) {
  // gaze：眼睛立即跟鼠标，头部阻尼慢半拍（Ani 的“眼先头后”）
  if (vrm.lookAt?.target) {
    vrm.lookAt.target.position.set(alive.gaze.x * 1.6, 1.35 - alive.gaze.y * 0.8, 2.2);
  }
  alive.headT.y = alive.gaze.x * 0.32;
  alive.headT.x = alive.gaze.y * 0.18;
  alive.headT.z = alive.gaze.x * -0.05;

  // fidget 调度
  if (!alive.fidget && t > alive.nextFidget) {
    alive.fidget = { name: FIDGETS[Math.floor(Math.random() * FIDGETS.length)],
                     start: t, dur: 1.6 + Math.random() * 1.2 };
  }
  let fx = 0, fy = 0, fz = 0, hipY = 0, chestZ = 0;
  if (alive.fidget) {
    const p = (t - alive.fidget.start) / alive.fidget.dur;
    if (p >= 1) { alive.fidget = null; alive.nextFidget = t + 5 + Math.random() * 7; }
    else {
      const env = Math.sin(Math.min(1, p) * Math.PI);      // 进出包络
      switch (alive.fidget.name) {
        case 'glance_left': fy = 0.35 * env; fz = 0.06 * env; break;
        case 'glance_right': fy = -0.35 * env; fz = -0.06 * env; break;
        case 'tilt': fz = 0.14 * env; fx = 0.04 * env; break;
        case 'weight': hipY = 0.12 * env; chestZ = -0.05 * env; break;
        case 'chin_up': fx = -0.1 * env; break;
      }
    }
  }

  // 说话节奏：音频包络驱动头部小点动 + 情绪
  const talk = state.speakingLevel;
  const mood = alive.mood;
  mood.level = Math.max(0, mood.level - dt * 0.08);
  const playful = mood.name === 'playful' ? mood.level : 0;

  alive.head.x = damp(alive.head.x, alive.headT.x + fx + talk * 0.05 * Math.sin(t * 7), 6, dt);
  alive.head.y = damp(alive.head.y, alive.headT.y + fy, 5, dt);
  alive.head.z = damp(alive.head.z, alive.headT.z + fz + playful * 0.06 * Math.sin(t * 1.1), 5, dt);

  setBone(vrm, VRMHumanBoneName.Hips, 0, damp(0, hipY, 1, 1) + Math.sin(t * 0.4) * 0.03, breath * 0.4);
  setBone(vrm, VRMHumanBoneName.Chest, breath + 0.02 + talk * 0.02,
    Math.sin(t * 0.6) * 0.03 + hipY * -0.4, chestZ + playful * 0.03 * Math.sin(t * 1.1));
  setBone(vrm, VRMHumanBoneName.Neck, alive.head.x * 0.3, alive.head.y * 0.35, alive.head.z * 0.3);
  setBone(vrm, VRMHumanBoneName.Head, alive.head.x, alive.head.y, alive.head.z);
  const armLift = talk * 0.12 + playful * 0.05;
  setBone(vrm, VRMHumanBoneName.LeftUpperArm, 0.06 + breath + armLift * Math.sin(t * 3.1), 0.04, 1.3 - armLift);
  setBone(vrm, VRMHumanBoneName.RightUpperArm, 0.06 + breath + armLift * Math.sin(t * 3.4 + 1), -0.04, -1.3 + armLift);
  setBone(vrm, VRMHumanBoneName.LeftLowerArm, -0.18 - talk * 0.15, 0, 0.1);
  setBone(vrm, VRMHumanBoneName.RightLowerArm, -0.18 - talk * 0.18, 0, -0.1);

  // 眨眼：变间隔 + 偶发双眨（Ani 的小细节）
  if (t > alive.nextBlink) {
    alive.blinking = t;
    alive.doubleBlink = Math.random() < 0.25;
    alive.nextBlink = t + 2.2 + Math.random() * 3.5;
  }
  let blink = 0;
  if (alive.blinking) {
    const bp = t - alive.blinking;
    if (bp < 0.12) blink = Math.sin((bp / 0.12) * Math.PI);
    else if (alive.doubleBlink && bp < 0.3 && bp > 0.18) blink = Math.sin(((bp - 0.18) / 0.12) * Math.PI);
    else if (bp > 0.3) alive.blinking = 0;
  }
  return blink;
}

function setMood(name, level = 1) { alive.mood = { name, level }; }
function setBone(vrm, name, x, y, z) {
  const node = vrm.humanoid?.getNormalizedBoneNode(name);
  if (node) node.rotation.set(x, y, z);
}

function animate() {
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  const t = clock.elapsedTime;
  controls.update();
  halo.material.opacity = 0.28 + 0.1 * Math.sin(t * 1.4);

  // live lipsync level from the playing reply audio
  if (state.audioAnalyser) {
    const buf = new Uint8Array(state.audioAnalyser.frequencyBinCount);
    state.audioAnalyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) { const c = (v - 128) / 128; sum += c * c; }
    state.speakingLevel = Math.min(1, Math.sqrt(sum / buf.length) * 5);
  } else {
    state.speakingLevel *= 0.9;
  }

  const vrm = state.currentVrm;
  if (vrm) {
    const breath = Math.sin(t * 1.6) * 0.02;
    const perf = state.performance && t < state.performance.until ? state.performance : null;
    if (!perf && state.performance) {
      state.performance = null;
      vrm.scene.rotation.y = 0;
      vrm.scene.position.y = vrm.scene.userData.floorY ?? vrm.scene.position.y;
    }

    if (perf) {
      const p = t - perf.start;
      const beat = Math.sin(p * 6.0);
      const offbeat = Math.sin(p * 6.0 + Math.PI / 2);
      if (perf.name === 'dance') {
        vrm.scene.position.y = (vrm.scene.userData.floorY ?? 0)
          + Math.abs(Math.sin(p * 6.0)) * 0.05;
        setBone(vrm, VRMHumanBoneName.Hips, 0, Math.sin(p * 3.0) * 0.18, beat * 0.08);
        setBone(vrm, VRMHumanBoneName.Chest, 0.05, -Math.sin(p * 3.0) * 0.12, -beat * 0.06);
        setBone(vrm, VRMHumanBoneName.Head, Math.sin(p * 3.0) * 0.06, Math.sin(p * 1.5) * 0.15, beat * 0.08);
        setBone(vrm, VRMHumanBoneName.LeftUpperArm, 0.2 - Math.max(0, beat) * 0.9, 0.1, 1.15 - Math.max(0, beat) * 1.5);
        setBone(vrm, VRMHumanBoneName.RightUpperArm, 0.2 - Math.max(0, -beat) * 0.9, -0.1, -1.15 + Math.max(0, -beat) * 1.5);
        setBone(vrm, VRMHumanBoneName.LeftLowerArm, -0.5 - Math.max(0, beat) * 0.4, 0, 0.35);
        setBone(vrm, VRMHumanBoneName.RightLowerArm, -0.5 - Math.max(0, -beat) * 0.4, 0, -0.35);
      } else if (perf.name === 'wave') {
        setBone(vrm, VRMHumanBoneName.Chest, 0.02, 0.06, 0.03);
        setBone(vrm, VRMHumanBoneName.Head, 0.02, 0.1, 0.08);
        setBone(vrm, VRMHumanBoneName.LeftUpperArm, 0.06, 0.04, 1.3);
        setBone(vrm, VRMHumanBoneName.LeftLowerArm, -0.18, 0, 0.1);
        setBone(vrm, VRMHumanBoneName.RightUpperArm, 0.15, -0.2, -2.4);
        setBone(vrm, VRMHumanBoneName.RightLowerArm, -0.3, 0, -0.5 - Math.sin(p * 9) * 0.35);
      } else if (perf.name === 'spin') {
        vrm.scene.rotation.y = Math.min(1, p / 1.6) * Math.PI * 2;
        setBone(vrm, VRMHumanBoneName.LeftUpperArm, 0.1, 0.04, 0.9);
        setBone(vrm, VRMHumanBoneName.RightUpperArm, 0.1, -0.04, -0.9);
        setBone(vrm, VRMHumanBoneName.Chest, 0.03, 0, offbeat * 0.04);
        setBone(vrm, VRMHumanBoneName.Head, 0, 0, 0);
        setBone(vrm, VRMHumanBoneName.LeftLowerArm, -0.2, 0, 0.15);
        setBone(vrm, VRMHumanBoneName.RightLowerArm, -0.2, 0, -0.15);
      } else if (perf.name === 'stretch') {
        const up = Math.min(1, p / 0.9);
        setBone(vrm, VRMHumanBoneName.Chest, -0.12 * up, 0, 0);
        setBone(vrm, VRMHumanBoneName.Head, -0.2 * up, 0, 0);
        setBone(vrm, VRMHumanBoneName.LeftUpperArm, -0.4 * up, 0.1, 1.3 - 2.5 * up);
        setBone(vrm, VRMHumanBoneName.RightUpperArm, -0.4 * up, -0.1, -1.3 + 2.5 * up);
        setBone(vrm, VRMHumanBoneName.LeftLowerArm, -0.1, 0, 0.05);
        setBone(vrm, VRMHumanBoneName.RightLowerArm, -0.1, 0, -0.05);
      } else if (perf.name === 'bow') {
        const bow = Math.sin(Math.min(1, p / 1.2) * Math.PI) * 0.55;
        setBone(vrm, VRMHumanBoneName.Chest, bow, 0, 0);
        setBone(vrm, VRMHumanBoneName.Head, bow * 0.5, 0, 0);
        setBone(vrm, VRMHumanBoneName.LeftUpperArm, 0.1, 0.04, 1.32);
        setBone(vrm, VRMHumanBoneName.RightUpperArm, 0.1, -0.04, -1.32);
        setBone(vrm, VRMHumanBoneName.LeftLowerArm, -0.15, 0, 0.1);
        setBone(vrm, VRMHumanBoneName.RightLowerArm, -0.15, 0, -0.1);
      }
      setBone(vrm, VRMHumanBoneName.Neck, 0, 0, 0);
    }
    const vrmaLive = vrmaAction && t < vrmaUntil;
    if (vrmaLive) {
      vrmMixer.update(dt);              // 动捕数据全权接管骨骼
    } else if (vrmaAction) {
      vrmaAction = null; vrmMixer = null;
    }
    let blink = 0;
    if (!perf && !vrmaLive) blink = aliveIdle(vrm, t, dt, breath);
    const em = vrm.expressionManager;
    if (em) {
      const mood = alive.mood;
      const moodHappy = mood.name === 'playful' || mood.name === 'warm' ? mood.level * 0.3 : 0;
      em.setValue('blink', blink);
      em.setValue('aa', state.speakingLevel * 0.85);
      em.setValue('happy', 0.12 + state.speakingLevel * 0.18 + moodHappy);
      em.setValue('relaxed', mood.name === 'warm' ? mood.level * 0.25 : 0.1);
    }
    vrm.update(dt);
  }
  if (state.mixer) {
    state.mixer.update(dt);
    if (state.currentRobot && state.speakingLevel > 0.05) {
      state.currentRobot.rotation.y = Math.sin(t * 3) * 0.05 * state.speakingLevel;
    }
  }
  renderer.render(scene, camera);
}

/* ────────────────────────── data loading ────────────────────────── */
async function boot() {
  resize();
  animate();
  const [status, characters, models, voices, animations] = await Promise.all([
    fetch('/api/status').then((r) => r.json()),
    fetch('/api/characters').then((r) => r.json()),
    fetch('/api/models').then((r) => r.json()),
    fetch('/api/voices').then((r) => r.json()),
    fetch('/api/animations').then((r) => r.json()),
  ]);
  state.animations = animations;
  $('anim-grid').innerHTML = animations.map((a) => `
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

  // agents
  const agentSelect = $('agent-select');
  agentSelect.innerHTML = characters.characters
    .map((c) => `<option value="${c.id}">${c.name} · ${c.role_label ?? c.archetype}</option>`)
    .join('');
  agentSelect.onchange = () => selectAgent(agentSelect.value);

  // archetypes
  const archetypes = Object.keys(characters.archetypes ?? {}).filter((k) => !k.startsWith('$'));
  $('p-archetype').innerHTML = archetypes
    .map((a) => `<option value="${a}">${a}</option>`).join('');

  // voices
  const providerSelect = $('v-provider');
  providerSelect.innerHTML = [
    voices.fish_available ? '<option value="fish">fish.audio · 真人级</option>' : '',
    '<option value="edge">Edge TTS · 神经语音</option>',
  ].join('');
  providerSelect.onchange = fillVoices;

  // models
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

  // default model = the character's own embodiment
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
  if (provider === 'fish') {
    voiceSelect.innerHTML = state.voices.fish
      .map((v) => `<option value="${v.id}" data-speed="${v.speed}">${v.label}</option>`).join('');
    const c = character?.id ? character : characterOf(state.agentId);
    const own = c?.voice?.fish?.reference_id;
    if (own) voiceSelect.value = own;
  } else {
    voiceSelect.innerHTML = state.voices.edge
      .map((v) => `<option value="${v.id}">${v.label}</option>`).join('');
    const c = character?.id ? character : characterOf(state.agentId);
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
    // 情绪从决策渗透到姿态与表情（Ani 式：整个人跟着情绪变）
    const style = (data.decision?.reason ?? '') + (data.decision?.intent ?? '');
    if (style.includes('perform') || style.includes('playful')) setMood('playful', 1);
    else if (style.includes('comfort') || style.includes('warm')) setMood('warm', 1);
    else setMood('neutral', 0.5);
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
   Decisions carry micro actions; here the body actually PERFORMS them.
   VRM bodies use procedural clips above; the robot uses its own GLTF clips. */
const PERF_DURATION = { dance: 6, wave: 3, spin: 2.4, stretch: 3, bow: 2.2,
                        clap: 3, jump: 2.2, think: 3, look_around: 3.5 };
const ROBOT_CLIP = { dance: 'Dance', wave: 'Wave', spin: 'Jump', stretch: 'ThumbsUp',
                     bow: 'Yes', clap: 'ThumbsUp', jump: 'Jump', think: 'Idle',
                     look_around: 'Idle' };
// 表演优先走动捕 VRMA（MIT, tk256ailab/vrm-viewer）；无对应资产才用程序化
const PERF_TO_VRMA = { wave: 'Goodbye', stretch: 'Relax', clap: 'Clapping',
                       jump: 'Jump', think: 'Thinking', look_around: 'LookAround' };

function triggerPerformance(actions) {
  let name = null;
  for (const action of actions) {
    if (action.params?.performance) { name = action.params.performance; break; }
    if (PERF_DURATION[action.name]) { name = action.name; break; }
  }
  if (!name) return;
  startPerformance(name);
}

function startPerformance(name) {
  // VRM 身体：能用动捕就不用程序化
  if (state.currentVrm && PERF_TO_VRMA[name]) {
    const asset = (state.animations ?? []).find(
      (a) => a.url.toLowerCase().includes(PERF_TO_VRMA[name].toLowerCase()));
    if (asset) { playVRMA(asset.url); return; }
  }
  const now = clock.elapsedTime;
  state.performance = { name, start: now, until: now + (PERF_DURATION[name] ?? 4) };
  if (state.currentRobot && state.mixer) {
    const clipName = ROBOT_CLIP[name] ?? 'Dance';
    const clip = state.robotClips?.find((c) => c.name === clipName);
    if (clip) {
      const action = state.mixer.clipAction(clip);
      action.reset();
      action.setLoop(name === 'dance' ? THREE.LoopRepeat : THREE.LoopOnce, 3);
      action.clampWhenFinished = false;
      action.fadeIn(0.2).play();
      setTimeout(() => action.fadeOut(0.4), (PERF_DURATION[name] ?? 4) * 1000);
    }
  }
}

/* ────────────────────────── mic input + barge-in ──────────────────────────
   Web Speech API (Chrome, zh-CN, needs network). Barge-in mirrors the
   perception layer's BargeInController semantics client-side:
   speech onset while the reply is playing → stop playback (safe pause of the
   only "motion" this body has) → echo-filter → fresh decision. */
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
    // barge-in: any speech onset while the character is talking stops her
    if (state.currentAudio && !state.currentAudio.paused) {
      state.currentAudio.pause();
      state.audioAnalyser = null;
      addMsg('agent', '（她停下来，听你说。）', 'system');
    }
    input.value = transcript;
    if (result.isFinal && transcript) {
      // echo filter: ignore recognition of her own just-played sentence
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
  recognition.onend = () => { if (micOn) recognition.start(); };  // keep-alive
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
    state.audioAnalyser = analyser;
    state.currentAudio = audio;
    const finish = () => {
      state.audioAnalyser = null;
      state.currentAudio = null;
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onended = audio.onerror = audio.onpause = finish;
    audio.play().catch(finish);
  });
}

boot();
