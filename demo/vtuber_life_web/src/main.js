import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { VRMHumanBoneName, VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import './style.css';

const canvas = document.querySelector('#scene');
const cardsEl = document.querySelector('#cards');
const nameTagsEl = document.querySelector('#nametags');
const queueEl = document.querySelector('#queue');
const clockEl = document.querySelector('#clock');
const bubbleEl = document.querySelector('#bubble');
const dialogueEl = document.querySelector('#dialogue');
const dialogueSpeakerEl = document.querySelector('#dialogue-speaker');
const dialogueLineEl = document.querySelector('#dialogue-line');
const dialogueMetaEl = document.querySelector('#dialogue-meta');
const loadingEl = document.querySelector('#loading');

const searchParams = new URLSearchParams(window.location.search);
if (searchParams.get('clean') === '1') {
  document.body.classList.add('clean');
}

const AGENTS = [
  {
    id: 'lydia',
    name: 'Astra-F',
    type: 'female humanoid companion robot',
    role: 'Creative Care',
    voiceLabel: 'Warm CN voiceprint',
    model: '/assets/vtubers/open_source_avatars/lydia.vrm',
    portrait: '/assets/vtubers/open_source_avatars/lydia_thumbnail.gif',
    color: '#ff6fb1',
    accent: '#f3d56b',
    scale: 0.96,
    targetHeight: 1.56,
    pose: { upperZ: 1.62, upperX: -0.12, lowerX: -0.34, shoulderZ: 0.02 },
    robotForm: 'female-humanoid',
    phase: 0.0,
    schedule: [
      ['Sensor wake', [-1.02, -0.58], 'coffee', 'Morning companion mode online.'],
      ['Human check-in', [-0.98, -0.18], 'talk', 'Reading your mood state.'],
      ['Motion sketch', [-1.10, 0.42], 'sketch', 'Mapping today into actions.'],
      ['Servo calibration', [-0.84, -0.62], 'dance', 'Joint loop looks stable.'],
      ['Memory recap', [-1.08, -0.04], 'read', 'Compressing the day log.'],
    ],
  },
  {
    id: 'robert',
    name: 'Mason-M',
    type: 'male biped service robot',
    role: 'Care & Cook',
    voiceLabel: 'Low steady voice',
    model: '/assets/vtubers/open_source_avatars/robert.vrm',
    portrait: '/assets/vtubers/open_source_avatars/robert_thumbnail.gif',
    color: '#6ba9ff',
    accent: '#6ee7b7',
    scale: 1.05,
    targetHeight: 1.42,
    pose: { upperZ: 1.58, upperX: -0.14, lowerX: -0.28, shoulderZ: 0.02 },
    robotForm: 'male-biped',
    phase: 1.8,
    schedule: [
      ['Kitchen safety', [-0.18, -0.72], 'cook', 'Thermal loop is stable.'],
      ['News parsing', [-0.26, -0.02], 'read', 'Scanning the morning brief.'],
      ['Talk with Astra', [-0.32, -0.24], 'talk', 'Plan confirmed.'],
      ['Desk compute', [-0.36, 0.52], 'desk', 'Checking the numbers.'],
      ['Evening uplink', [-0.24, -0.64], 'call', 'Tomorrow schedule locked.'],
    ],
  },
  {
    id: 'polybot',
    name: 'Hex-01',
    type: 'non-human scout robot',
    role: 'AI Scout',
    voiceLabel: 'Synthetic scout voice',
    model: '/assets/vtubers/open_source_avatars/polybot.vrm',
    portrait: '/assets/vtubers/open_source_avatars/polybot_thumbnail.gif',
    color: '#48e2c3',
    accent: '#f66dff',
    scale: 0.88,
    targetHeight: 1.18,
    pose: { upperZ: 1.50, upperX: -0.10, lowerX: -0.22, shoulderZ: 0.00 },
    robotForm: 'non-human',
    phase: 3.4,
    schedule: [
      ['Boot sequence', [1.02, -0.62], 'boot', 'Scout chassis online.'],
      ['Inspect plant', [1.04, 0.30], 'scan', 'Leaf variance detected.'],
      ['Repair loop', [1.14, 0.54], 'repair', 'Patch accepted.'],
      ['Join talk', [0.98, -0.18], 'talk', 'Non-human unit listening.'],
      ['Charge cycle', [1.08, 0.04], 'charge', 'Docking current stable.'],
    ],
  },
];

const DIALOGUE_BEATS = [
  { start: 0.02, end: 0.10, speaker: 'lydia', targets: ['robert'], camera: 'coffee', text: '早间陪伴模式启动，我先校准表情和动作。' },
  { start: 0.10, end: 0.18, speaker: 'robert', targets: ['lydia'], camera: 'kitchen', text: '厨房执行器上线，热源保持安全距离。' },
  { start: 0.18, end: 0.26, speaker: 'polybot', targets: ['lydia', 'robert'], camera: 'robot', text: '非人形侦察单元在线，环境扫描开始。' },
  { start: 0.28, end: 0.36, speaker: 'robert', targets: ['lydia'], camera: 'conversation', text: '我会把任务拆成可执行的关节动作。' },
  { start: 0.36, end: 0.45, speaker: 'lydia', targets: ['robert'], camera: 'conversation', text: '先照顾情绪，再安排今天的动作模板。' },
  { start: 0.46, end: 0.54, speaker: 'polybot', targets: ['lydia'], camera: 'plant', text: '植物叶片状态正常，湿度偏低。' },
  { start: 0.56, end: 0.64, speaker: 'lydia', targets: ['robert'], camera: 'sketch', text: '这个动作可以写成模板，明天直接复用。' },
  { start: 0.65, end: 0.72, speaker: 'robert', targets: ['lydia'], camera: 'desk', text: '我把舵机曲线和安全阈值一起保存。' },
  { start: 0.73, end: 0.81, speaker: 'polybot', targets: ['robert'], camera: 'repair', text: '维修循环开始，扳手扭矩百分之七十。' },
  { start: 0.82, end: 0.90, speaker: 'lydia', targets: ['robert', 'polybot'], camera: 'dance', text: '情绪反馈良好，动作幅度可以再柔一点。' },
  { start: 0.90, end: 0.98, speaker: 'robert', targets: ['lydia'], camera: 'sofa', text: '晚间复盘完成，明天计划已锁定。' },
];

const DAY_TIMELINE = [
  ['07:00', 'Wake Up', 'lydia'],
  ['08:30', 'Morning Routine', 'lydia'],
  ['09:30', 'Work / Study', 'robert'],
  ['12:30', 'Lunch Break', 'robert'],
  ['14:00', 'Project Time', 'lydia'],
  ['17:30', 'Free Time', 'polybot'],
  ['19:00', 'Dinner', 'robert'],
  ['20:00', 'Chat & Connect', 'lydia'],
  ['22:30', 'Wind Down', 'polybot'],
  ['23:30', 'Sleep', 'polybot'],
];

const scene = new THREE.Scene();
scene.background = makeBackdropTexture();
scene.fog = new THREE.Fog(0x101722, 6.0, 11.0);

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
  preserveDrawingBuffer: true,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.56;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(30, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(2.80, 1.58, -4.65);
camera.lookAt(0, 0.55, 0);

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(
  new THREE.Vector2(window.innerWidth, window.innerHeight),
  0.10,
  0.28,
  1.24,
);
composer.addPass(bloomPass);
composer.addPass(new OutputPass());

const hemi = new THREE.HemisphereLight(0xf5fbff, 0x241c18, 0.42);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffdfb8, 0.82);
sun.position.set(-3.0, 5.0, -2.6);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.left = -4;
sun.shadow.camera.right = 4;
sun.shadow.camera.top = 4;
sun.shadow.camera.bottom = -4;
scene.add(sun);
const rim = new THREE.PointLight(0x8bd6ff, 3.2, 6.0);
rim.position.set(2.3, 2.0, -1.7);
scene.add(rim);
const warmFill = new THREE.PointLight(0xffa36a, 2.4, 5.5);
warmFill.position.set(-2.1, 1.2, -1.5);
scene.add(warmFill);

buildApartment(scene);
const directorFx = createDirectorFx();
scene.add(directorFx.group);

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));
const loadedAgents = await Promise.all(AGENTS.map(loadAgent));
loadingEl.classList.add('hidden');
initHud();
window.addEventListener('resize', resizeRenderer);
animate();

async function loadAgent(agent) {
  return new Promise((resolve, reject) => {
    loader.load(
      agent.model,
      (gltf) => {
        const vrm = gltf.userData.vrm;
        VRMUtils.removeUnnecessaryVertices(gltf.scene);
        VRMUtils.combineSkeletons(gltf.scene);
        VRMUtils.rotateVRM0(vrm);
        vrm.scene.traverse((obj) => {
          obj.frustumCulled = false;
          if (obj.isMesh) {
            obj.castShadow = true;
            obj.receiveShadow = true;
            if (obj.material) {
              obj.material.envMapIntensity = 0.55;
              obj.material.needsUpdate = true;
            }
          }
        });
        const naturalBox = new THREE.Box3().setFromObject(vrm.scene);
        const naturalSize = naturalBox.getSize(new THREE.Vector3());
        const normalizedScale = (agent.targetHeight / Math.max(0.1, naturalSize.y)) * agent.scale;
        vrm.scene.scale.setScalar(normalizedScale);
        const scaledBox = new THREE.Box3().setFromObject(vrm.scene);
        vrm.scene.userData.floorOffset = -scaledBox.min.y;
        scene.add(vrm.scene);
        const aura = createAura(agent);
        scene.add(aura);
        const props = createAgentProps(agent);
        scene.add(props.group);
        const robotRig = createRobotRig(agent);
        scene.add(robotRig.group);
        resolve({ ...agent, vrm, root: vrm.scene, aura, props, robotRig, currentAction: agent.schedule[0] });
      },
      undefined,
      reject,
    );
  });
}

function animate() {
  const t = getDemoTime();
  updateScene(t);
  renderFrame();
  window.__soulforgeFrameReady = true;
  requestAnimationFrame(animate);
}

function renderFrame() {
  composer.render();
}

function getDemoTime() {
  if (window.__recordTime !== undefined) return Number(window.__recordTime);
  return performance.now() / 1000;
}

function updateScene(t) {
  const cycle = 30 * 60;
  const sim = ((t % cycle) + cycle) % cycle;
  const dayMinutes = Math.floor(7 * 60 + (sim / cycle) * 16 * 60);
  clockEl.textContent = `${String(Math.floor(dayMinutes / 60) % 24).padStart(2, '0')}:${String(dayMinutes % 60).padStart(2, '0')}`;

  const beat = beatForSim(sim, cycle);
  const framesById = new Map();
  loadedAgents.forEach((agent, index) => {
    const frame = frameForAgent(agent, sim, cycle);
    frame.agentIndex = index;
    framesById.set(agent.id, frame);
  });
  applyInteractionBeat(beat, framesById);

  loadedAgents.forEach((agent, index) => {
    const frame = framesById.get(agent.id);
    agent.currentAction = frame.action;
    const root = agent.root;
    root.position.set(frame.x, root.userData.floorOffset ?? 0, frame.z);
    root.rotation.y = frame.heading;
    if (agent.aura) {
      agent.aura.position.set(frame.x, 0.018, frame.z);
      agent.aura.material.opacity = 0.30 + 0.08 * Math.sin(sim * 2.4 + agent.phase);
      agent.aura.scale.setScalar(1 + 0.04 * Math.sin(sim * 1.6 + agent.phase));
    }
    animateVrm(agent, frame, sim);
    updateAgentProps(agent, frame, sim);
    updateRobotRig(agent, frame, sim);
    updateCard(agent, frame, index);
  });
  updateNameTags();

  const focus = beat ? loadedAgents.find((agent) => agent.id === beat.speaker) : loadedAgents[Math.floor(sim / 22) % loadedAgents.length];
  const f = framesById.get(focus.id);
  bubbleEl.textContent = beat?.text ?? f.action[3];
  bubbleEl.style.setProperty('--bubble-color', focus.color);
  bubbleEl.style.left = `${Math.min(window.innerWidth - 260, Math.max(280, window.innerWidth * 0.54 + f.x * 95 - f.z * 70))}px`;
  bubbleEl.style.top = `${Math.max(86, window.innerHeight * 0.44 - f.z * 32)}px`;
  const activeTimeline = timelineIndexForDay(dayMinutes);
  queueEl.innerHTML = DAY_TIMELINE.map((item, index) => {
    const agent = AGENTS.find((candidate) => candidate.id === item[2]);
    const role = index === activeTimeline ? 'speaking' : index < activeTimeline ? 'done' : 'pending';
    return `<div class="${role}"><span style="background:${agent?.color ?? '#fff'}"></span><time>${item[0]}</time><b>${item[1]}</b></div>`;
  }).join('');

  updateDialogue(beat, framesById, sim);
  updateDirectorFx(beat, framesById, sim);
  updateCamera(beat, framesById, sim, cycle);
}

function beatForSim(sim, cycle) {
  const progress = sim / cycle;
  return DIALOGUE_BEATS.find((beat) => progress >= beat.start && progress < beat.end) ?? null;
}

function timelineIndexForDay(dayMinutes) {
  const current = ((dayMinutes % (24 * 60)) + (24 * 60)) % (24 * 60);
  let active = 0;
  DAY_TIMELINE.forEach((item, index) => {
    const [hour, minute] = item[0].split(':').map(Number);
    const start = hour * 60 + minute;
    if (current >= start) active = index;
  });
  return active;
}

function applyInteractionBeat(beat, framesById) {
  if (!beat) return;
  const speakerFrame = framesById.get(beat.speaker);
  if (!speakerFrame) return;
  speakerFrame.speaking = true;
  speakerFrame.cinematic = true;

  beat.targets.forEach((targetId) => {
    const targetFrame = framesById.get(targetId);
    if (!targetFrame) return;
    targetFrame.listening = true;
    targetFrame.cinematic = true;
    targetFrame.heading = headingToward(targetFrame, speakerFrame);
  });

  const mainTarget = framesById.get(beat.targets[0]);
  if (mainTarget) {
    speakerFrame.heading = headingToward(speakerFrame, mainTarget);
  }
}

function headingToward(from, to) {
  return Math.atan2(to.x - from.x, to.z - from.z);
}

function frameForAgent(agent, sim, cycle) {
  const schedule = agent.schedule;
  const slice = cycle / schedule.length;
  const idx = Math.min(schedule.length - 1, Math.floor(sim / slice));
  const action = schedule[idx];
  const prev = idx === 0 ? action : schedule[idx - 1];
  const local = (sim - idx * slice) / slice;
  const move = smoothstep(Math.min(1, local / 0.34));
  const from = prev[1];
  const to = action[1];
  const settle = local > 0.42 ? 1 : 0;
  const micro = settle ? 0.004 * Math.sin(sim * 0.8 + agent.phase) : 0;
  let x = THREE.MathUtils.lerp(from[0], to[0], move) + micro;
  let z = THREE.MathUtils.lerp(from[1], to[1], move) + micro * Math.cos(agent.phase);
  const drift = activityDrift(action[2], local, sim, agent.phase);
  x += drift.x;
  z += drift.z;
  const dx = to[0] - from[0];
  const dz = to[1] - from[1];
  const moving = local < 0.34 && Math.hypot(dx, dz) > 0.1;
  const heading = moving ? Math.atan2(dx, dz) : Math.sin(sim * 0.42 + agent.phase) * 0.18;
  return { x, z, heading, action, local, moving };
}

function activityDrift(actionType, local, sim, phase) {
  const settle = smoothstep(Math.max(0, Math.min(1, (local - 0.34) / 0.24)));
  if (actionType === 'dance') {
    return {
      x: settle * 0.09 * Math.sin(sim * 3.0 + phase),
      z: settle * 0.07 * Math.cos(sim * 2.4 + phase),
    };
  }
  if (actionType === 'cook') {
    return { x: settle * 0.05 * Math.sin(sim * 1.9 + phase), z: settle * 0.025 * Math.cos(sim * 2.6) };
  }
  if (actionType === 'sketch' || actionType === 'desk') {
    return { x: settle * 0.018 * Math.sin(sim * 1.2 + phase), z: settle * 0.035 * Math.sin(sim * 0.8 + phase) };
  }
  if (actionType === 'scan' || actionType === 'repair') {
    return { x: settle * 0.035 * Math.sin(sim * 2.1 + phase), z: settle * 0.028 * Math.cos(sim * 1.7 + phase) };
  }
  if (actionType === 'talk') {
    return { x: settle * 0.025 * Math.sin(sim * 1.1 + phase), z: settle * 0.02 * Math.cos(sim * 1.4 + phase) };
  }
  return { x: 0, z: 0 };
}

function animateVrm(agent, frame, sim) {
  const vrm = agent.vrm;
  vrm.humanoid.resetNormalizedPose();
  const s = Math.sin;
  const gait = s(sim * 5.4 + agent.phase);
  const breath = s(sim * 1.8 + agent.phase) * 0.035;
  const actionType = frame.action[2];
  const speaking = frame.speaking || actionType === 'talk';
  const listening = frame.listening && !frame.speaking;
  const pose = agent.pose ?? {};
  const neutralUpperZ = pose.upperZ ?? 1.56;
  const neutralUpperX = pose.upperX ?? -0.14;
  const neutralLowerX = pose.lowerX ?? -0.28;
  const neutralShoulderZ = pose.shoulderZ ?? 0.02;

  setBone(vrm, VRMHumanBoneName.Hips, [0, 0, frame.moving ? gait * 0.045 : breath]);
  let chestX = breath;
  let chestY = s(sim * 0.9 + agent.phase) * 0.035;
  let chestZ = 0;
  let neckX = s(sim * 0.7 + agent.phase) * 0.06;
  let neckY = s(sim * 0.5 + agent.phase) * 0.14;
  let headX = s(sim * 0.61 + agent.phase) * 0.08;
  let headY = s(sim * 0.43 + agent.phase) * 0.13;
  let headZ = s(sim * 0.52 + agent.phase) * 0.045;

  let leftArmX = frame.moving ? neutralUpperX + 0.16 * gait : neutralUpperX;
  let rightArmX = frame.moving ? neutralUpperX - 0.16 * gait : neutralUpperX;
  let leftArmZ = neutralUpperZ;
  let rightArmZ = -neutralUpperZ;
  let leftLowerX = neutralLowerX;
  let rightLowerX = neutralLowerX;

  if (actionType === 'wave') {
    rightArmX = -0.44 + 0.06 * s(sim * 8.0);
    rightArmZ = -neutralUpperZ + 0.10;
    rightLowerX = -0.88 + 0.14 * s(sim * 8.0);
  }
  if (actionType === 'dance') {
    leftArmX = -0.48 + 0.18 * s(sim * 7.0);
    rightArmX = -0.48 - 0.18 * s(sim * 7.0);
    leftArmZ = neutralUpperZ - 0.18;
    rightArmZ = -neutralUpperZ + 0.18;
  }
  if (actionType === 'think') {
    rightArmX = -0.48;
    rightArmZ = -1.32;
    rightLowerX = -0.64;
  }
  if (actionType === 'talk') {
    leftArmX = neutralUpperX - 0.06 + 0.04 * s(sim * 4.6);
    rightArmX = neutralUpperX - 0.08 - 0.04 * s(sim * 4.6);
    leftArmZ = neutralUpperZ - 0.08;
    rightArmZ = -neutralUpperZ + 0.08;
    leftLowerX = neutralLowerX - 0.18 + 0.08 * s(sim * 4.6);
    rightLowerX = neutralLowerX - 0.12 - 0.08 * s(sim * 4.6);
  }
  if (actionType === 'scan') {
    leftArmX = -0.22 + 0.06 * s(sim * 3.0);
    rightArmX = -0.22 - 0.06 * s(sim * 3.0);
    leftArmZ = neutralUpperZ - 0.08;
    rightArmZ = -neutralUpperZ + 0.08;
  }
  if (actionType === 'coffee') {
    rightArmX = -0.62 + 0.05 * s(sim * 3.4);
    rightArmZ = -neutralUpperZ + 0.14;
    rightLowerX = -0.96 + 0.08 * s(sim * 3.4);
    leftArmX = neutralUpperX - 0.02;
    headX = -0.05 + 0.05 * s(sim * 0.9);
    headY = 0.10 + 0.04 * s(sim * 0.7);
  }
  if (actionType === 'cook') {
    leftArmX = -0.44 + 0.10 * s(sim * 5.5);
    rightArmX = -0.50 - 0.16 * s(sim * 5.5);
    leftArmZ = neutralUpperZ - 0.14;
    rightArmZ = -neutralUpperZ + 0.14;
    leftLowerX = -0.62 + 0.12 * s(sim * 5.5);
    rightLowerX = -0.74 - 0.20 * s(sim * 5.5);
    chestX = -0.08 + breath;
    headX = -0.08;
  }
  if (actionType === 'sketch' || actionType === 'desk') {
    leftArmX = -0.54 + 0.06 * s(sim * 4.2);
    rightArmX = -0.58 - 0.05 * s(sim * 4.7);
    leftArmZ = neutralUpperZ - 0.18;
    rightArmZ = -neutralUpperZ + 0.18;
    leftLowerX = -0.86 + 0.08 * s(sim * 4.2);
    rightLowerX = -0.92 - 0.08 * s(sim * 4.7);
    chestX = -0.12 + breath;
    headX = -0.18 + 0.03 * s(sim * 1.8);
    headY = 0.04 * s(sim * 1.1);
  }
  if (actionType === 'read') {
    leftArmX = -0.46;
    rightArmX = -0.46;
    leftArmZ = neutralUpperZ - 0.12;
    rightArmZ = -neutralUpperZ + 0.12;
    leftLowerX = -0.86;
    rightLowerX = -0.86;
    chestX = -0.10 + breath;
    headX = -0.22 + 0.02 * s(sim * 1.3);
    headY = 0.05 * s(sim * 0.8);
  }
  if (actionType === 'call') {
    rightArmX = -0.78;
    rightArmZ = -neutralUpperZ + 0.18;
    rightLowerX = -1.08 + 0.04 * s(sim * 3.2);
    leftArmX = neutralUpperX + 0.02;
    headY = -0.16 + 0.04 * s(sim * 0.9);
    headZ = -0.04;
  }
  if (actionType === 'repair') {
    leftArmX = -0.42 + 0.10 * s(sim * 9.0);
    rightArmX = -0.66 - 0.26 * s(sim * 9.0);
    leftArmZ = neutralUpperZ - 0.16;
    rightArmZ = -neutralUpperZ + 0.12;
    leftLowerX = -0.58 + 0.14 * s(sim * 8.0);
    rightLowerX = -0.95 - 0.24 * s(sim * 9.0);
    chestX = -0.10 + 0.05 * s(sim * 7.0);
    headX = -0.12 + 0.05 * s(sim * 4.0);
  }
  if (actionType === 'boot' || actionType === 'charge') {
    leftArmX = neutralUpperX;
    rightArmX = neutralUpperX;
    leftLowerX = neutralLowerX;
    rightLowerX = neutralLowerX;
    chestX = actionType === 'charge' ? 0.02 * s(sim * 0.55) : 0.03 * s(sim * 2.2);
    headX = actionType === 'charge' ? -0.03 : 0.05 * s(sim * 2.8);
    headY = actionType === 'charge' ? 0.05 * s(sim * 0.45) : 0.16 * s(sim * 3.4);
  }

  if (speaking) {
    chestY += 0.04 * s(sim * 2.8 + agent.phase);
    headX += 0.035 * s(sim * 4.2);
    headY += 0.08 * s(sim * 2.1 + agent.phase);
    leftArmX = Math.min(leftArmX, neutralUpperX - 0.10) + 0.07 * s(sim * 4.8);
    rightArmX = Math.min(rightArmX, neutralUpperX - 0.12) - 0.07 * s(sim * 4.5);
    leftArmZ = neutralUpperZ - 0.12;
    rightArmZ = -neutralUpperZ + 0.12;
    leftLowerX = Math.min(leftLowerX, neutralLowerX - 0.22) + 0.08 * s(sim * 4.8);
    rightLowerX = Math.min(rightLowerX, neutralLowerX - 0.20) - 0.08 * s(sim * 4.5);
  }

  if (listening) {
    chestX += 0.02 * s(sim * 0.9 + agent.phase);
    headX += -0.035 + 0.035 * s(sim * 2.2);
    headY += 0.05 * s(sim * 1.6 + agent.phase);
    leftArmX = neutralUpperX - 0.03;
    rightArmX = neutralUpperX - 0.03;
    leftLowerX = neutralLowerX - 0.06;
    rightLowerX = neutralLowerX - 0.06;
  }

  setBone(vrm, VRMHumanBoneName.Chest, [chestX, chestY, chestZ]);
  setBone(vrm, VRMHumanBoneName.Neck, [neckX, neckY, 0]);
  setBone(vrm, VRMHumanBoneName.Head, [headX, headY, headZ]);

  setBone(vrm, VRMHumanBoneName.LeftShoulder, [0.0, 0.0, neutralShoulderZ]);
  setBone(vrm, VRMHumanBoneName.RightShoulder, [0.0, 0.0, -neutralShoulderZ]);
  setBone(vrm, VRMHumanBoneName.LeftUpperArm, [leftArmX, 0.04, leftArmZ]);
  setBone(vrm, VRMHumanBoneName.RightUpperArm, [rightArmX, -0.04, rightArmZ]);
  setBone(vrm, VRMHumanBoneName.LeftLowerArm, [leftLowerX + (frame.moving ? 0.10 * gait : 0), 0, 0.08]);
  setBone(vrm, VRMHumanBoneName.RightLowerArm, [rightLowerX + (frame.moving ? -0.10 * gait : 0), 0, -0.08]);
  setBone(vrm, VRMHumanBoneName.LeftUpperLeg, [frame.moving ? -0.32 * gait : 0, 0, 0]);
  setBone(vrm, VRMHumanBoneName.RightUpperLeg, [frame.moving ? 0.32 * gait : 0, 0, 0]);
  setBone(vrm, VRMHumanBoneName.LeftLowerLeg, [frame.moving ? 0.22 * Math.max(0, gait) : 0, 0, 0]);
  setBone(vrm, VRMHumanBoneName.RightLowerLeg, [frame.moving ? 0.22 * Math.max(0, -gait) : 0, 0, 0]);

  if (vrm.expressionManager) {
    const happy = actionType === 'dance' || speaking || actionType === 'coffee' ? 0.45 + 0.18 * s(sim * 3.0) : 0.12;
    vrm.expressionManager.setValue('happy', happy);
    vrm.expressionManager.setValue('relaxed', actionType === 'read' || listening || actionType === 'charge' ? 0.45 : 0.12);
  }
  vrm.update(1 / 60);
}

function setBone(vrm, boneName, euler) {
  const node = vrm.humanoid.getNormalizedBoneNode(boneName);
  if (!node) return;
  node.rotation.x = euler[0];
  node.rotation.y = euler[1];
  node.rotation.z = euler[2];
}

function initHud() {
  cardsEl.innerHTML = AGENTS.map((agent, index) => `
    <div class="card" id="card-${agent.id}" style="--agent:${agent.color}; --accent:${agent.accent}">
      <img src="${agent.portrait}" alt="${agent.name}">
      <div class="card-text">
        <div class="name">${agent.name}</div>
        <div class="type">${agent.role}</div>
        <div class="activity">Loading</div>
        <div class="voice">${agent.voiceLabel}</div>
        <div class="bars">
          <label>Energy<span></span></label>
          <label>Social<span></span></label>
          <label>Fun<span></span></label>
        </div>
      </div>
    </div>
  `).join('');
  nameTagsEl.innerHTML = AGENTS.map((agent) => `
    <div class="name-tag" id="tag-${agent.id}" style="--agent:${agent.color}; --accent:${agent.accent}">
      <span></span><strong>${agent.name}</strong><small>Loading</small>
    </div>
  `).join('');
}

function updateCard(agent, frame, index) {
  const card = document.querySelector(`#card-${agent.id}`);
  if (!card) return;
  card.querySelector('.activity').textContent = frame.action[0];
  const bars = card.querySelectorAll('label span');
  const values = [
    frame.action[2] === 'charge' ? 42 + 18 * frame.local : 66 + 18 * Math.sin(frame.local * Math.PI + agent.phase),
    frame.action[2] === 'talk' || frame.action[2] === 'call' ? 88 : 54 + 20 * Math.sin(frame.local * 3 + index),
    frame.action[2] === 'dance' || frame.action[2] === 'coffee' || frame.action[2] === 'repair' ? 90 : 48 + 24 * Math.cos(frame.local * 2 + agent.phase),
  ];
  bars.forEach((bar, i) => {
    bar.style.width = `${Math.max(12, Math.min(96, values[i]))}%`;
  });
}

function updateNameTags() {
  camera.updateMatrixWorld();
  loadedAgents.forEach((agent) => {
    const tag = document.querySelector(`#tag-${agent.id}`);
    if (!tag) return;
    const activity = tag.querySelector('small');
    if (activity) activity.textContent = agent.currentAction?.[0] ?? 'Idle';
    const world = new THREE.Vector3();
    agent.root.getWorldPosition(world);
    world.y += (agent.targetHeight ?? 1.3) + 0.22;
    world.project(camera);
    const x = (world.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-world.y * 0.5 + 0.5) * window.innerHeight;
    tag.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
    tag.style.opacity = world.z < 1 ? '1' : '0';
  });
}

function updateDialogue(beat, framesById, sim) {
  const fallbackAgent = loadedAgents[Math.floor(sim / 22) % loadedAgents.length];
  const speaker = beat ? loadedAgents.find((agent) => agent.id === beat.speaker) : fallbackAgent;
  const frame = framesById.get(speaker.id);
  const line = beat?.text ?? frame.action[3];
  dialogueEl.style.setProperty('--speaker-color', speaker.color);
  dialogueEl.style.setProperty('--speaker-accent', speaker.accent);
  dialogueEl.classList.toggle('active', Boolean(beat));
  dialogueSpeakerEl.textContent = speaker.name;
  dialogueLineEl.textContent = line;
  if (dialogueMetaEl) dialogueMetaEl.textContent = `${speaker.role} · ${speaker.voiceLabel}`;
}

function createDirectorFx() {
  const group = new THREE.Group();
  group.name = 'director-fx';
  const lineGeometry = new THREE.BufferGeometry().setFromPoints(new Array(24).fill(0).map(() => new THREE.Vector3()));
  const lineMaterial = new THREE.LineBasicMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });
  const line = new THREE.Line(lineGeometry, lineMaterial);
  group.add(line);

  const focusRing = new THREE.Mesh(
    new THREE.RingGeometry(0.42, 0.50, 96),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }),
  );
  focusRing.rotation.x = -Math.PI / 2;
  focusRing.renderOrder = 3;
  group.add(focusRing);

  const targetRing = new THREE.Mesh(
    new THREE.RingGeometry(0.34, 0.40, 96),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }),
  );
  targetRing.rotation.x = -Math.PI / 2;
  targetRing.renderOrder = 3;
  group.add(targetRing);

  return { group, line, focusRing, targetRing };
}

function updateDirectorFx(beat, framesById, sim) {
  if (!beat) {
    directorFx.line.material.opacity = 0;
    directorFx.focusRing.material.opacity = 0;
    directorFx.targetRing.material.opacity = 0;
    return;
  }

  const speakerFrame = framesById.get(beat.speaker);
  const targetFrame = framesById.get(beat.targets[0]);
  const speaker = loadedAgents.find((agent) => agent.id === beat.speaker);
  const target = loadedAgents.find((agent) => agent.id === beat.targets[0]);
  if (!speakerFrame || !targetFrame || !speaker || !target) return;

  const color = new THREE.Color(speaker.accent);
  directorFx.line.material.color.copy(color);
  directorFx.line.material.opacity = 0.52 + 0.12 * Math.sin(sim * 5.0);
  const points = [];
  for (let i = 0; i < 24; i += 1) {
    const p = i / 23;
    const x = THREE.MathUtils.lerp(speakerFrame.x, targetFrame.x, p);
    const z = THREE.MathUtils.lerp(speakerFrame.z, targetFrame.z, p);
    const y = 0.10 + Math.sin(p * Math.PI) * 0.44;
    points.push(new THREE.Vector3(x, y, z));
  }
  directorFx.line.geometry.setFromPoints(points);

  directorFx.focusRing.material.color.set(speaker.color);
  directorFx.focusRing.material.opacity = 0.42 + 0.12 * Math.sin(sim * 6.2);
  directorFx.focusRing.position.set(speakerFrame.x, 0.026, speakerFrame.z);
  directorFx.focusRing.scale.setScalar(1.0 + 0.08 * Math.sin(sim * 5.4));

  directorFx.targetRing.material.color.set(target.color);
  directorFx.targetRing.material.opacity = 0.26 + 0.10 * Math.sin(sim * 4.8);
  directorFx.targetRing.position.set(targetFrame.x, 0.028, targetFrame.z);
  directorFx.targetRing.scale.setScalar(1.0 + 0.05 * Math.cos(sim * 4.4));
}

function updateCamera(beat, framesById, sim, cycle) {
  const fallbackShots = ['wide', 'kitchen', 'sketch', 'conversation', 'plant', 'repair', 'sofa'];
  const shotName = beat?.camera ?? fallbackShots[Math.floor((sim / cycle) * fallbackShots.length) % fallbackShots.length];
  const shot = cameraShot(shotName, beat, framesById, sim);
  camera.fov = shot.fov;
  camera.position.set(
    shot.position[0] + Math.sin(sim * 0.003) * shot.drift,
    shot.position[1] + Math.sin(sim * 0.0022) * shot.drift * 0.28,
    shot.position[2] + Math.cos(sim * 0.0027) * shot.drift,
  );
  camera.lookAt(shot.lookAt[0], shot.lookAt[1], shot.lookAt[2]);
  camera.updateProjectionMatrix();
}

function cameraShot(name, beat, framesById, sim) {
  const speakerFrame = beat ? framesById.get(beat.speaker) : null;
  const targetFrame = beat ? framesById.get(beat.targets[0]) : null;
  const mid = speakerFrame && targetFrame
    ? {
        x: (speakerFrame.x + targetFrame.x) / 2,
        z: (speakerFrame.z + targetFrame.z) / 2,
      }
    : { x: 0, z: -0.08 };

  const shots = {
    wide: { position: [2.92, 1.58, -4.85], lookAt: [0.02, 0.76, -0.08], fov: 31, drift: 0.14 },
    coffee: { position: [-1.88, 1.34, -3.42], lookAt: [-0.96, 0.76, -0.44], fov: 34, drift: 0.08 },
    kitchen: { position: [0.88, 1.36, -3.96], lookAt: [-0.16, 0.74, -0.58], fov: 34, drift: 0.08 },
    robot: { position: [0.20, 1.30, -4.08], lookAt: [1.02, 0.66, -0.30], fov: 33, drift: 0.07 },
    plant: { position: [0.18, 1.30, -4.10], lookAt: [1.08, 0.74, 0.26], fov: 34, drift: 0.07 },
    sketch: { position: [-1.90, 1.34, -3.04], lookAt: [-1.08, 0.78, 0.34], fov: 34, drift: 0.08 },
    desk: { position: [0.56, 1.34, -3.50], lookAt: [-0.34, 0.74, 0.40], fov: 34, drift: 0.08 },
    repair: { position: [0.36, 1.28, -4.02], lookAt: [1.12, 0.64, 0.42], fov: 33, drift: 0.07 },
    dance: { position: [0.52, 1.38, -4.08], lookAt: [-0.08, 0.82, -0.50], fov: 34, drift: 0.12 },
    sofa: { position: [0.74, 1.30, -4.02], lookAt: [0.72, 0.74, 0.18], fov: 34, drift: 0.08 },
    conversation: { position: [THREE.MathUtils.clamp(mid.x + 1.18, -1.80, 1.80), 1.34, mid.z - 3.32], lookAt: [mid.x, 0.78, mid.z], fov: 34, drift: 0.07 },
  };

  const shot = shots[name] ?? shots.wide;
  if (name === 'conversation' && speakerFrame && targetFrame) return shot;
  if (!beat || !speakerFrame) return shot;
  if (name === 'dance') {
    shot.lookAt = [speakerFrame.x * 0.45, 0.82 + 0.05 * Math.sin(sim * 3), speakerFrame.z - 0.06];
  }
  return shot;
}

function resizeRenderer() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
}

function createRobotRig(agent) {
  const group = new THREE.Group();
  group.name = `${agent.id}-robot-architecture`;
  const color = new THREE.Color(agent.color);
  const accent = new THREE.Color(agent.accent);
  const metalMat = new THREE.MeshStandardMaterial({
    color: 0xd8e0e7,
    metalness: 0.54,
    roughness: 0.28,
  });
  const darkMat = new THREE.MeshStandardMaterial({
    color: 0x18232e,
    metalness: 0.42,
    roughness: 0.34,
  });
  const jointMat = new THREE.MeshStandardMaterial({
    color: 0xcfd8dc,
    emissive: color,
    emissiveIntensity: 0.08,
    metalness: 0.58,
    roughness: 0.24,
  });
  const glowMat = new THREE.MeshBasicMaterial({
    color: accent,
    transparent: true,
    opacity: 0.82,
    depthWrite: false,
  });
  const lineMat = new THREE.LineBasicMaterial({
    color: accent,
    transparent: true,
    opacity: 0.58,
  });

  const parts = {
    torso: new THREE.Mesh(new RoundedBoxGeometry(0.34, 0.24, 0.045, 4, 0.012), metalMat),
    chestBus: new THREE.Mesh(new RoundedBoxGeometry(0.22, 0.055, 0.026, 4, 0.008), glowMat.clone()),
    spineRail: new THREE.Mesh(new RoundedBoxGeometry(0.10, 0.36, 0.055, 4, 0.012), darkMat),
    battery: new THREE.Mesh(new RoundedBoxGeometry(0.24, 0.18, 0.075, 4, 0.012), darkMat),
    headSensor: new THREE.Mesh(new RoundedBoxGeometry(0.20, 0.045, 0.045, 4, 0.008), glowMat.clone()),
    leftShoulder: makeJoint(0.032, jointMat),
    rightShoulder: makeJoint(0.032, jointMat),
    leftElbow: makeJoint(0.028, jointMat),
    rightElbow: makeJoint(0.028, jointMat),
    leftWrist: makeJoint(0.023, jointMat),
    rightWrist: makeJoint(0.023, jointMat),
    leftHip: makeJoint(0.030, jointMat),
    rightHip: makeJoint(0.030, jointMat),
    leftKnee: makeJoint(0.030, jointMat),
    rightKnee: makeJoint(0.030, jointMat),
    leftAnkle: makeJoint(0.024, jointMat),
    rightAnkle: makeJoint(0.024, jointMat),
    coreLight: new THREE.Mesh(new THREE.SphereGeometry(0.032, 20, 12), glowMat.clone()),
    leftPod: new THREE.Mesh(new RoundedBoxGeometry(0.12, 0.10, 0.08, 4, 0.012), darkMat),
    rightPod: new THREE.Mesh(new RoundedBoxGeometry(0.12, 0.10, 0.08, 4, 0.012), darkMat),
  };
  Object.values(parts).forEach((part) => {
    part.castShadow = true;
    part.receiveShadow = true;
    group.add(part);
  });

  const cables = {
    leftArm: makeCable(lineMat),
    rightArm: makeCable(lineMat),
    leftLeg: makeCable(lineMat),
    rightLeg: makeCable(lineMat),
    spine: makeCable(lineMat),
  };
  Object.values(cables).forEach((line) => group.add(line));

  return { group, parts, cables };
}

function makeJoint(radius, mat) {
  return new THREE.Mesh(new RoundedBoxGeometry(radius * 2.4, radius * 1.65, radius * 0.95, 4, radius * 0.22), mat);
}

function makeCable(mat) {
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), mat.clone());
}

function updateRobotRig(agent, frame, sim) {
  const rig = agent.robotRig;
  if (!rig) return;
  const { parts, cables } = rig;
  const bodyHeight = agent.targetHeight ?? 1.35;
  const rootY = agent.root.userData.floorOffset ?? 0;
  const compact = agent.robotForm === 'non-human';
  const base = new THREE.Vector3(frame.x, rootY, frame.z);
  const local = (x, y, z) => {
    const point = new THREE.Vector3(x, y, z);
    point.applyAxisAngle(new THREE.Vector3(0, 1, 0), frame.heading);
    return point.add(base);
  };
  const pose = (obj, x, y, z, rotation = [0, frame.heading, 0], scale = 1) => {
    obj.position.copy(local(x, y, z));
    obj.rotation.set(rotation[0], rotation[1], rotation[2]);
    obj.scale.setScalar(scale);
  };
  const armSwing = frame.moving ? Math.sin(sim * 5.4 + agent.phase) * 0.07 : Math.sin(sim * 1.6 + agent.phase) * 0.018;
  const talkSwing = frame.speaking ? Math.sin(sim * 4.8 + agent.phase) * 0.055 : 0;
  const listenDip = frame.listening ? -0.018 + Math.sin(sim * 2.2 + agent.phase) * 0.012 : 0;
  const shoulderX = compact ? 0.17 : 0.22;
  const elbowX = compact ? 0.22 : 0.30;
  const wristX = compact ? 0.20 : 0.27;
  const hipX = compact ? 0.12 : 0.14;
  const kneeX = compact ? 0.13 : 0.14;
  const ankleX = compact ? 0.16 : 0.15;

  const torsoY = bodyHeight * (compact ? 0.52 : 0.60);
  const shoulderY = bodyHeight * (compact ? 0.62 : 0.72) + listenDip;
  const elbowY = bodyHeight * (compact ? 0.46 : 0.55) + talkSwing;
  const wristY = bodyHeight * (compact ? 0.36 : 0.43) + talkSwing * 0.55;
  const hipY = bodyHeight * (compact ? 0.36 : 0.44);
  const kneeY = bodyHeight * (compact ? 0.20 : 0.25) + Math.abs(armSwing) * 0.30;
  const ankleY = bodyHeight * 0.07;

  pose(parts.torso, 0, torsoY, -0.13, [0.04, frame.heading, 0], compact ? 0.78 : 1);
  pose(parts.chestBus, 0, torsoY + bodyHeight * 0.035, -0.158, [0.04, frame.heading, 0], 1 + 0.08 * Math.sin(sim * 5.0));
  pose(parts.coreLight, 0, torsoY - bodyHeight * 0.045, -0.17, [0, frame.heading, 0], 1 + 0.16 * Math.sin(sim * 4.4 + agent.phase));
  pose(parts.spineRail, 0, torsoY, 0.14, [0.0, frame.heading, 0], compact ? 0.70 : 1);
  pose(parts.battery, 0, bodyHeight * (compact ? 0.43 : 0.55), 0.21, [0.0, frame.heading, 0], compact ? 0.78 : 1);
  pose(parts.headSensor, 0, bodyHeight * (compact ? 0.80 : 0.91), -0.10, [0.02, frame.heading, 0], compact ? 0.78 : 1);

  const leftArmOffset = -armSwing - talkSwing;
  const rightArmOffset = armSwing + talkSwing;
  const leftShoulder = local(-shoulderX, shoulderY, -0.01);
  const rightShoulder = local(shoulderX, shoulderY, -0.01);
  const leftElbow = local(-elbowX + leftArmOffset, elbowY, -0.035);
  const rightElbow = local(elbowX + rightArmOffset, elbowY, -0.035);
  const leftWrist = local(-wristX + leftArmOffset * 1.15, wristY, -0.08);
  const rightWrist = local(wristX + rightArmOffset * 1.15, wristY, -0.08);
  const leftHip = local(-hipX, hipY, 0.00);
  const rightHip = local(hipX, hipY, 0.00);
  const leftKnee = local(-kneeX - armSwing * 0.35, kneeY, -0.005);
  const rightKnee = local(kneeX + armSwing * 0.35, kneeY, -0.005);
  const leftAnkle = local(-ankleX, ankleY, -0.02);
  const rightAnkle = local(ankleX, ankleY, -0.02);

  parts.leftShoulder.position.copy(leftShoulder);
  parts.rightShoulder.position.copy(rightShoulder);
  parts.leftElbow.position.copy(leftElbow);
  parts.rightElbow.position.copy(rightElbow);
  parts.leftWrist.position.copy(leftWrist);
  parts.rightWrist.position.copy(rightWrist);
  parts.leftHip.position.copy(leftHip);
  parts.rightHip.position.copy(rightHip);
  parts.leftKnee.position.copy(leftKnee);
  parts.rightKnee.position.copy(rightKnee);
  parts.leftAnkle.position.copy(leftAnkle);
  parts.rightAnkle.position.copy(rightAnkle);
  [
    parts.leftWrist,
    parts.rightWrist,
    parts.leftHip,
    parts.rightHip,
    parts.leftAnkle,
    parts.rightAnkle,
  ].forEach((part) => {
    part.visible = compact;
  });
  [
    parts.leftShoulder,
    parts.rightShoulder,
    parts.leftElbow,
    parts.rightElbow,
    parts.leftKnee,
    parts.rightKnee,
    parts.torso,
    parts.chestBus,
    parts.spineRail,
    parts.battery,
    parts.headSensor,
    parts.coreLight,
    parts.leftPod,
    parts.rightPod,
  ].forEach((part) => {
    part.visible = true;
  });
  [
    parts.leftShoulder,
    parts.rightShoulder,
    parts.leftElbow,
    parts.rightElbow,
    parts.leftWrist,
    parts.rightWrist,
    parts.leftHip,
    parts.rightHip,
    parts.leftKnee,
    parts.rightKnee,
    parts.leftAnkle,
    parts.rightAnkle,
  ].forEach((joint) => {
    joint.rotation.set(0.05, frame.heading, 0.02);
  });
  pose(parts.leftPod, -0.24, bodyHeight * (compact ? 0.42 : 0.50), 0.03, [0, frame.heading, 0], compact ? 0.9 : 0.72);
  pose(parts.rightPod, 0.24, bodyHeight * (compact ? 0.42 : 0.50), 0.03, [0, frame.heading, 0], compact ? 0.9 : 0.72);

  setCable(cables.leftArm, compact ? [leftShoulder, leftElbow, leftWrist] : [leftShoulder, leftElbow, local(-0.20, bodyHeight * 0.50, 0.02)]);
  setCable(cables.rightArm, compact ? [rightShoulder, rightElbow, rightWrist] : [rightShoulder, rightElbow, local(0.20, bodyHeight * 0.50, 0.02)]);
  setCable(cables.leftLeg, compact ? [leftHip, leftKnee, leftAnkle] : [local(-0.10, hipY, 0.05), leftKnee]);
  setCable(cables.rightLeg, compact ? [rightHip, rightKnee, rightAnkle] : [local(0.10, hipY, 0.05), rightKnee]);
  setCable(cables.spine, [
    local(0, bodyHeight * 0.78, 0.16),
    local(0, torsoY, 0.20),
    local(0, bodyHeight * 0.34, 0.12),
  ]);

  const opacity = compact ? 0.74 : 0.62;
  Object.values(cables).forEach((line) => {
    line.material.opacity = opacity + 0.12 * Math.sin(sim * 3.2 + agent.phase);
  });
}

function setCable(line, points) {
  line.geometry.setFromPoints(points);
}

function createAgentProps(agent) {
  const group = new THREE.Group();
  group.name = `${agent.id}-props`;
  const accent = new THREE.Color(agent.accent);
  const color = new THREE.Color(agent.color);
  const darkMat = new THREE.MeshStandardMaterial({ color: 0x151c24, roughness: 0.48, metalness: 0.1 });
  const whiteMat = new THREE.MeshStandardMaterial({ color: 0xf6f1e7, roughness: 0.42 });
  const paperMat = new THREE.MeshStandardMaterial({ color: 0xf0e5d2, roughness: 0.62 });
  const accentMat = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.18,
    roughness: 0.45,
  });
  const glowMat = new THREE.MeshBasicMaterial({
    color: accent,
    transparent: true,
    opacity: 0.42,
    depthWrite: false,
    side: THREE.DoubleSide,
  });

  const cup = new THREE.Group();
  const cupBody = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.045, 0.12, 28), whiteMat);
  cup.add(cupBody);
  const cupBand = new THREE.Mesh(new THREE.TorusGeometry(0.047, 0.006, 8, 28), accentMat);
  cupBand.rotation.x = Math.PI / 2;
  cupBand.position.y = 0.03;
  cup.add(cupBand);
  const steam = [];
  for (let i = 0; i < 3; i += 1) {
    const puff = new THREE.Mesh(new THREE.TorusGeometry(0.025 + i * 0.006, 0.003, 8, 28), glowMat.clone());
    puff.position.y = 0.09 + i * 0.055;
    puff.rotation.x = Math.PI / 2;
    cup.add(puff);
    steam.push(puff);
  }
  group.add(cup);

  const tablet = new THREE.Group();
  tablet.add(new THREE.Mesh(new RoundedBoxGeometry(0.36, 0.24, 0.025, 4, 0.012), darkMat));
  const tabletScreen = new THREE.Mesh(new RoundedBoxGeometry(0.31, 0.19, 0.012, 4, 0.008), new THREE.MeshStandardMaterial({
    color: 0x17232f,
    emissive: accent,
    emissiveIntensity: 0.5,
    roughness: 0.32,
  }));
  tabletScreen.position.z = -0.018;
  tablet.add(tabletScreen);
  const pen = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.26, 12), accentMat);
  pen.rotation.z = Math.PI / 2.8;
  pen.position.set(0.19, 0.02, -0.04);
  tablet.add(pen);
  group.add(tablet);

  const book = new THREE.Group();
  const leftPage = new THREE.Mesh(new RoundedBoxGeometry(0.18, 0.23, 0.018, 3, 0.008), paperMat);
  leftPage.position.x = -0.095;
  const rightPage = leftPage.clone();
  rightPage.position.x = 0.095;
  book.add(leftPage, rightPage);
  const spine = new THREE.Mesh(new RoundedBoxGeometry(0.025, 0.25, 0.024, 3, 0.006), accentMat);
  book.add(spine);
  group.add(book);

  const phone = new THREE.Group();
  phone.add(new THREE.Mesh(new RoundedBoxGeometry(0.08, 0.15, 0.018, 4, 0.014), darkMat));
  const phoneScreen = new THREE.Mesh(new RoundedBoxGeometry(0.058, 0.11, 0.01, 4, 0.01), new THREE.MeshBasicMaterial({ color: accent }));
  phoneScreen.position.z = -0.012;
  phone.add(phoneScreen);
  group.add(phone);

  const pan = new THREE.Group();
  const panBowl = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.10, 0.045, 32), darkMat);
  const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.013, 0.013, 0.28, 12), darkMat);
  handle.rotation.z = Math.PI / 2;
  handle.position.x = 0.20;
  pan.add(panBowl, handle);
  group.add(pan);

  const wrench = new THREE.Group();
  const wrenchHandle = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.28, 14), darkMat);
  wrenchHandle.rotation.z = Math.PI / 4;
  const wrenchHead = new THREE.Mesh(new THREE.TorusGeometry(0.045, 0.010, 8, 24, Math.PI * 1.45), darkMat);
  wrenchHead.position.set(0.09, 0.09, 0);
  wrench.add(wrenchHandle, wrenchHead);
  group.add(wrench);

  const scanBeam = new THREE.Mesh(new THREE.ConeGeometry(0.30, 0.82, 48, 1, true), glowMat.clone());
  scanBeam.rotation.x = -Math.PI / 2;
  scanBeam.material.opacity = 0.24;
  group.add(scanBeam);

  const chargeRing = new THREE.Mesh(new THREE.TorusGeometry(0.34, 0.018, 12, 72), glowMat.clone());
  chargeRing.rotation.x = Math.PI / 2;
  chargeRing.material.opacity = 0.46;
  group.add(chargeRing);

  const sparks = [];
  for (let i = 0; i < 8; i += 1) {
    const spark = new THREE.Mesh(new THREE.SphereGeometry(0.018, 12, 8), new THREE.MeshBasicMaterial({ color: i % 2 ? 0xffd36d : accent }));
    sparks.push(spark);
    group.add(spark);
  }

  return {
    group,
    cup,
    steam,
    tablet,
    book,
    phone,
    pan,
    wrench,
    scanBeam,
    chargeRing,
    sparks,
  };
}

function updateAgentProps(agent, frame, sim) {
  const props = agent.props;
  if (!props) return;
  const actionType = frame.action[2];
  const rootY = agent.root.userData.floorOffset ?? 0;
  const bodyHeight = agent.targetHeight ?? 1.35;
  const base = new THREE.Vector3(frame.x, rootY, frame.z);
  const local = (x, y, z) => {
    const point = new THREE.Vector3(x, y, z);
    point.applyAxisAngle(new THREE.Vector3(0, 1, 0), frame.heading);
    return point.add(base);
  };
  const copyPose = (obj, position, rotation = [0, frame.heading, 0], scale = 1) => {
    obj.position.copy(position);
    obj.rotation.set(rotation[0], rotation[1], rotation[2]);
    obj.scale.setScalar(scale);
  };
  const all = [props.cup, props.tablet, props.book, props.phone, props.pan, props.wrench, props.scanBeam, props.chargeRing, ...props.sparks];
  all.forEach((obj) => {
    obj.visible = false;
  });

  if (actionType === 'coffee') {
    props.cup.visible = true;
    copyPose(props.cup, local(0.22, bodyHeight * 0.58 + 0.04 * Math.sin(sim * 5), -0.08), [0.10, frame.heading + 0.16, 0.04], 1);
    props.steam.forEach((puff, i) => {
      puff.material.opacity = 0.18 + 0.12 * Math.sin(sim * 2.5 + i);
      puff.position.x = 0.012 * Math.sin(sim * 2.1 + i);
    });
  }

  if (actionType === 'sketch' || actionType === 'desk') {
    props.tablet.visible = true;
    copyPose(props.tablet, local(0.02, bodyHeight * 0.54, -0.26), [-0.28, frame.heading, 0.03 * Math.sin(sim * 4)], actionType === 'desk' ? 1.12 : 1);
  }

  if (actionType === 'read') {
    props.book.visible = true;
    copyPose(props.book, local(0.03, bodyHeight * 0.53, -0.22), [-0.18, frame.heading, 0.03 * Math.sin(sim * 1.8)], 1);
  }

  if (actionType === 'call') {
    props.phone.visible = true;
    copyPose(props.phone, local(0.18, bodyHeight * 0.78, -0.08), [0.08, frame.heading + 0.22, 0.22], 1);
  }

  if (actionType === 'cook') {
    props.pan.visible = true;
    copyPose(props.pan, local(0.18, bodyHeight * 0.68, -0.22), [0.70 + 0.08 * Math.sin(sim * 5), frame.heading + 0.12, 0.08], 0.62);
    props.cup.visible = true;
    copyPose(props.cup, local(-0.16, bodyHeight * 0.50 + 0.03 * Math.sin(sim * 7), -0.20), [0.1, frame.heading - 0.1, 0], 0.70);
  }

  if (actionType === 'repair') {
    props.wrench.visible = true;
    copyPose(props.wrench, local(0.16, bodyHeight * 0.48, -0.18), [0.2 * Math.sin(sim * 8), frame.heading + 0.4, 0.8], 1.1);
    props.sparks.forEach((spark, i) => {
      spark.visible = true;
      const angle = sim * 7 + i * 0.8;
      const radius = 0.08 + (i % 3) * 0.04;
      spark.position.copy(local(
        0.06 + Math.cos(angle) * radius,
        bodyHeight * 0.46 + Math.sin(angle * 1.7) * 0.05,
        -0.22 + Math.sin(angle) * radius,
      ));
      spark.scale.setScalar(0.65 + 0.5 * Math.sin(sim * 9 + i));
    });
  }

  if (actionType === 'scan') {
    props.scanBeam.visible = true;
    copyPose(props.scanBeam, local(0, bodyHeight * 0.52, -0.48), [Math.PI / 2, frame.heading, 0], 0.80);
    props.scanBeam.material.opacity = 0.20 + 0.08 * Math.sin(sim * 5);
  }

  if (actionType === 'boot') {
    props.chargeRing.visible = true;
    copyPose(props.chargeRing, local(0, bodyHeight * 0.42 + 0.04 * Math.sin(sim * 6), 0), [Math.PI / 2, frame.heading, 0], 0.72 + 0.08 * Math.sin(sim * 8));
    props.chargeRing.material.opacity = 0.34 + 0.14 * Math.sin(sim * 8);
  }

  if (actionType === 'charge') {
    props.chargeRing.visible = true;
    copyPose(props.chargeRing, local(0, 0.16 + 0.035 * Math.sin(sim * 4), 0), [Math.PI / 2, frame.heading, 0], 1 + 0.08 * Math.sin(sim * 5));
    props.chargeRing.material.opacity = 0.34 + 0.12 * Math.sin(sim * 6);
  }
}

function buildApartment(target) {
  const floorMat = new THREE.MeshStandardMaterial({
    map: makeFloorTexture(),
    roughness: 0.52,
    metalness: 0.02,
  });
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x253244, roughness: 0.82 });
  const sideWallMat = new THREE.MeshStandardMaterial({ color: 0x172536, roughness: 0.86 });
  const trimMat = new THREE.MeshStandardMaterial({ color: 0x101820, roughness: 0.44, metalness: 0.16 });
  const woodMat = new THREE.MeshStandardMaterial({ color: 0xa8754e, roughness: 0.44 });
  const darkWoodMat = new THREE.MeshStandardMaterial({ color: 0x473426, roughness: 0.46 });
  const blackMetalMat = new THREE.MeshStandardMaterial({ color: 0x10151d, roughness: 0.38, metalness: 0.28 });
  const cabinetMat = new THREE.MeshStandardMaterial({ color: 0x1c3041, roughness: 0.56, metalness: 0.08 });
  const fabricMat = new THREE.MeshStandardMaterial({ color: 0x44616a, roughness: 0.82 });
  const pillowMat = new THREE.MeshStandardMaterial({ color: 0xd38f6d, roughness: 0.78 });
  const rugMat = new THREE.MeshStandardMaterial({ color: 0x9d4a52, roughness: 0.90 });
  const plantMat = new THREE.MeshStandardMaterial({ color: 0x2a3c35, roughness: 0.72 });
  const leafMat = new THREE.MeshStandardMaterial({ color: 0x3ecf84, roughness: 0.70 });
  const screenMat = new THREE.MeshStandardMaterial({
    map: makeScreenTexture(),
    color: 0xffffff,
    emissive: 0x2cc7ff,
    emissiveIntensity: 0.38,
    roughness: 0.28,
  });
  const warmGlowMat = new THREE.MeshStandardMaterial({
    color: 0xc88a56,
    emissive: 0xff9f4d,
    emissiveIntensity: 0.13,
    roughness: 0.28,
  });
  const tealGlowMat = new THREE.MeshStandardMaterial({
    color: 0x48e2c3,
    emissive: 0x13d7b7,
    emissiveIntensity: 0.18,
    roughness: 0.35,
  });

  addRoundedBox(target, [0, -0.045, 0], [5.35, 0.09, 3.70], floorMat, 0.035, true);
  addRoundedBox(target, [0, 1.05, 1.78], [5.35, 2.10, 0.11], wallMat, 0.018, true);
  addRoundedBox(target, [-2.67, 1.05, 0], [0.11, 2.10, 3.70], sideWallMat, 0.018, true);
  addRoundedBox(target, [2.67, 1.05, 0.22], [0.11, 2.10, 3.30], sideWallMat, 0.018, true);
  addRoundedBox(target, [0, 2.06, 0.02], [5.35, 0.08, 3.68], new THREE.MeshStandardMaterial({ color: 0x10151f, roughness: 0.74 }), 0.018, false);
  addRoundedBox(target, [0, 0.08, 1.62], [4.86, 0.12, 0.08], trimMat, 0.012, true);
  addRoundedBox(target, [-2.42, 0.08, 0], [0.08, 0.12, 3.18], trimMat, 0.012, true);
  addRoundedBox(target, [2.42, 0.08, 0.20], [0.08, 0.12, 2.90], trimMat, 0.012, true);

  addRoundedBox(target, [0.22, 0.012, -0.34], [2.18, 0.024, 1.26], rugMat, 0.045, true);
  addRoundedBox(target, [0.22, 0.028, -0.34], [1.70, 0.012, 0.92], new THREE.MeshStandardMaterial({ color: 0xd28a72, roughness: 0.88 }), 0.04, true);

  addCityWindow(target, [1.12, 1.16, 1.71], [2.30, 1.15], trimMat);
  addNeonSign(target, [-1.35, 1.15, 1.70]);
  addKitchen(target, cabinetMat, woodMat, darkWoodMat, blackMetalMat, warmGlowMat);
  addDeskStation(target, woodMat, darkWoodMat, blackMetalMat, screenMat, warmGlowMat);
  addCouchZone(target, fabricMat, pillowMat, woodMat, darkWoodMat, warmGlowMat);
  addShelfWall(target, [-1.66, 1.46, 1.64], woodMat, darkWoodMat, tealGlowMat);
  addCeilingRails(target, blackMetalMat, warmGlowMat);

  addPlant(target, [-2.05, 0.02, 1.04], plantMat, leafMat, 0.86);
  addPlant(target, [2.08, 0.02, 1.08], plantMat, leafMat, 0.76);
  addPlant(target, [1.42, 0.02, 0.28], plantMat, leafMat, 0.56);

  addHangingLamp(target, [-0.22, 1.88, -0.02]);
  addHangingLamp(target, [1.42, 1.84, 0.74]);
  addFloorLamp(target, [-1.82, 0.02, -0.36], blackMetalMat, warmGlowMat);
  addRoundedBox(target, [-0.55, 0.018, -1.40], [0.70, 0.016, 0.16], new THREE.MeshStandardMaterial({ color: 0xf06bdc, emissive: 0x42103b, emissiveIntensity: 0.45, roughness: 0.55 }), 0.012, false);
  addRoundedBox(target, [0.56, 0.018, -1.40], [0.70, 0.016, 0.16], new THREE.MeshStandardMaterial({ color: 0x48e2c3, emissive: 0x073f39, emissiveIntensity: 0.42, roughness: 0.55 }), 0.012, false);
}

function addCityWindow(target, pos, size, trimMat) {
  const city = new THREE.Mesh(
    new THREE.PlaneGeometry(size[0], size[1]),
    new THREE.MeshBasicMaterial({ map: makeCityTexture(), side: THREE.DoubleSide }),
  );
  city.position.set(pos[0], pos[1], pos[2] - 0.022);
  target.add(city);

  addRoundedBox(target, [pos[0], pos[1] + size[1] / 2 + 0.035, pos[2] - 0.045], [size[0] + 0.12, 0.055, 0.035], trimMat, 0.010, true);
  addRoundedBox(target, [pos[0], pos[1] - size[1] / 2 - 0.035, pos[2] - 0.045], [size[0] + 0.12, 0.055, 0.035], trimMat, 0.010, true);
  addRoundedBox(target, [pos[0] - size[0] / 2 - 0.035, pos[1], pos[2] - 0.045], [0.055, size[1] + 0.12, 0.035], trimMat, 0.010, true);
  addRoundedBox(target, [pos[0] + size[0] / 2 + 0.035, pos[1], pos[2] - 0.045], [0.055, size[1] + 0.12, 0.035], trimMat, 0.010, true);
  addRoundedBox(target, [pos[0], pos[1], pos[2] - 0.075], [size[0], size[1], 0.018], new THREE.MeshStandardMaterial({
    color: 0x101923,
    metalness: 0.12,
    roughness: 0.24,
    transparent: true,
    opacity: 0.36,
  }), 0.015, false);
  [-0.25, 0.25].forEach((offset) => {
    addRoundedBox(target, [pos[0] + offset * size[0], pos[1], pos[2] - 0.09], [0.025, size[1] + 0.08, 0.025], trimMat, 0.004, false);
  });
  addRoundedBox(target, [pos[0], pos[1], pos[2] - 0.092], [size[0] + 0.08, 0.026, 0.025], trimMat, 0.004, false);
}

function addNeonSign(target, pos) {
  const sign = new THREE.Mesh(
    new THREE.PlaneGeometry(0.70, 0.36),
    new THREE.MeshBasicMaterial({ map: makeNeonTexture(), transparent: true, side: THREE.DoubleSide }),
  );
  sign.position.set(pos[0], pos[1], pos[2] - 0.055);
  target.add(sign);
  const light = new THREE.PointLight(0x36d4ff, 1.8, 2.2);
  light.position.set(pos[0], pos[1], pos[2] - 0.45);
  target.add(light);
}

function addKitchen(target, cabinetMat, woodMat, darkWoodMat, metalMat, warmGlowMat) {
  addRoundedBox(target, [-0.06, 0.40, 1.37], [1.52, 0.78, 0.24], cabinetMat, 0.035, true);
  addRoundedBox(target, [-0.06, 0.82, 1.23], [1.62, 0.10, 0.50], woodMat, 0.024, true);
  addRoundedBox(target, [-0.06, 1.16, 1.66], [1.80, 0.42, 0.08], new THREE.MeshStandardMaterial({ color: 0x99816c, roughness: 0.74 }), 0.014, true);
  addRoundedBox(target, [-0.62, 1.72, 1.62], [0.78, 0.34, 0.14], cabinetMat, 0.022, true);
  addRoundedBox(target, [0.24, 1.72, 1.62], [0.78, 0.34, 0.14], cabinetMat, 0.022, true);
  addRoundedBox(target, [-0.08, 1.02, 1.54], [1.62, 0.035, 0.025], warmGlowMat, 0.008, false);

  addRoundedBox(target, [0.04, 0.54, -0.52], [1.36, 0.66, 0.58], cabinetMat, 0.045, true);
  addRoundedBox(target, [0.04, 0.90, -0.52], [1.48, 0.10, 0.68], woodMat, 0.030, true);
  addRoundedBox(target, [-0.36, 0.98, -0.55], [0.34, 0.025, 0.22], metalMat, 0.010, false);
  addRoundedBox(target, [0.30, 0.98, -0.54], [0.30, 0.035, 0.26], new THREE.MeshStandardMaterial({ color: 0xe4d3bd, roughness: 0.50 }), 0.012, true);

  const pan = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.13, 0.045, 36), metalMat);
  pan.position.set(-0.36, 1.02, -0.55);
  pan.castShadow = true;
  target.add(pan);
  const steamMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.18, depthWrite: false });
  for (let i = 0; i < 4; i += 1) {
    const puff = new THREE.Mesh(new THREE.TorusGeometry(0.035 + i * 0.010, 0.004, 8, 30), steamMat.clone());
    puff.position.set(-0.36 + i * 0.018, 1.12 + i * 0.055, -0.55);
    puff.rotation.x = Math.PI / 2;
    target.add(puff);
  }

  [-0.52, 0.42].forEach((x) => addBarStool(target, [x, 0.02, -1.02], darkWoodMat, metalMat));
}

function addDeskStation(target, woodMat, darkWoodMat, metalMat, screenMat, warmGlowMat) {
  addRoundedBox(target, [-1.44, 0.36, 0.34], [1.08, 0.12, 0.58], woodMat, 0.035, true);
  addRoundedBox(target, [-1.44, 0.19, 0.34], [0.96, 0.24, 0.46], darkWoodMat, 0.035, true);
  addRoundedBox(target, [-1.68, 0.66, 0.38], [0.46, 0.32, 0.035], screenMat, 0.016, true);
  addRoundedBox(target, [-1.26, 0.50, 0.22], [0.30, 0.04, 0.20], metalMat, 0.010, true);
  addRoundedBox(target, [-1.14, 0.45, 0.50], [0.36, 0.028, 0.16], new THREE.MeshStandardMaterial({ color: 0x1a2833, emissive: 0x1aa5ff, emissiveIntensity: 0.34, roughness: 0.35 }), 0.010, false);
  addRoundedBox(target, [-1.88, 0.56, 0.46], [0.12, 0.13, 0.12], new THREE.MeshStandardMaterial({ color: 0xf2eadc, roughness: 0.50 }), 0.020, true);
  addRoundedBox(target, [-1.58, 0.47, 0.02], [0.48, 0.045, 0.13], metalMat, 0.012, true);
  addRoundedBox(target, [-1.54, 0.50, 0.01], [0.38, 0.010, 0.10], warmGlowMat, 0.006, false);
  addRoundedBox(target, [-1.02, 0.31, 0.34], [0.34, 0.46, 0.42], new THREE.MeshStandardMaterial({ color: 0x273647, roughness: 0.72 }), 0.045, true);
}

function addCouchZone(target, fabricMat, pillowMat, woodMat, darkWoodMat, warmGlowMat) {
  addRoundedBox(target, [1.48, 0.22, 0.58], [1.08, 0.34, 0.42], fabricMat, 0.055, true);
  addRoundedBox(target, [1.48, 0.55, 0.76], [1.12, 0.50, 0.12], fabricMat, 0.045, true);
  addRoundedBox(target, [0.88, 0.34, 0.58], [0.12, 0.44, 0.42], fabricMat, 0.04, true);
  addRoundedBox(target, [2.08, 0.34, 0.58], [0.12, 0.44, 0.42], fabricMat, 0.04, true);
  addRoundedBox(target, [1.26, 0.56, 0.46], [0.28, 0.18, 0.08], pillowMat, 0.028, true);
  addRoundedBox(target, [1.66, 0.56, 0.47], [0.30, 0.18, 0.08], new THREE.MeshStandardMaterial({ color: 0xead5aa, roughness: 0.78 }), 0.028, true);

  addRoundedBox(target, [1.26, 0.20, -0.10], [0.70, 0.14, 0.34], woodMat, 0.032, true);
  addRoundedBox(target, [1.26, 0.30, -0.10], [0.58, 0.035, 0.25], darkWoodMat, 0.018, true);
  [-0.16, 0.06, 0.20].forEach((offset, index) => {
    const candle = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.030, 0.075, 20), warmGlowMat);
    candle.position.set(1.22 + offset, 0.38, -0.10 + (index - 1) * 0.06);
    candle.castShadow = true;
    target.add(candle);
    const light = new THREE.PointLight(0xffb76f, 0.22, 0.9);
    light.position.set(candle.position.x, candle.position.y + 0.10, candle.position.z);
    target.add(light);
  });
}

function addShelfWall(target, pos, woodMat, darkWoodMat, accentMat) {
  for (let row = 0; row < 3; row += 1) {
    addRoundedBox(target, [pos[0], pos[1] - row * 0.28, pos[2]], [1.12, 0.045, 0.18], woodMat, 0.012, true);
  }
  [-0.54, 0.54].forEach((x) => addRoundedBox(target, [pos[0] + x, pos[1] - 0.28, pos[2]], [0.035, 0.60, 0.16], darkWoodMat, 0.010, true));
  for (let i = 0; i < 18; i += 1) {
    const row = i % 3;
    const col = Math.floor(i / 3);
    const mat = i % 4 === 0 ? accentMat : new THREE.MeshStandardMaterial({ color: [0x233d55, 0x8d5e49, 0xd8ba76][i % 3], roughness: 0.60 });
    addRoundedBox(target, [pos[0] - 0.42 + col * 0.15, pos[1] + 0.05 - row * 0.28, pos[2] - 0.07], [0.055, 0.18 + (i % 2) * 0.04, 0.07], mat, 0.006, true);
  }
}

function addCeilingRails(target, metalMat, glowMat) {
  addRoundedBox(target, [0, 1.98, -0.14], [3.90, 0.035, 0.035], metalMat, 0.006, false);
  addRoundedBox(target, [0, 1.98, 0.58], [3.20, 0.035, 0.035], metalMat, 0.006, false);
  [-1.3, -0.45, 0.65, 1.42].forEach((x, index) => {
    addRoundedBox(target, [x, 1.88, index % 2 ? -0.14 : 0.58], [0.08, 0.08, 0.08], glowMat, 0.018, false);
  });
}

function addBarStool(target, pos, woodMat, metalMat) {
  const seat = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.17, 0.055, 36), woodMat);
  seat.position.set(pos[0], 0.52, pos[2]);
  seat.castShadow = true;
  target.add(seat);
  const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.022, 0.48, 16), metalMat);
  leg.position.set(pos[0], 0.28, pos[2]);
  leg.castShadow = true;
  target.add(leg);
  const foot = new THREE.Mesh(new THREE.TorusGeometry(0.12, 0.010, 8, 32), metalMat);
  foot.position.set(pos[0], 0.12, pos[2]);
  foot.rotation.x = Math.PI / 2;
  target.add(foot);
}

function addFloorLamp(target, pos, metalMat, glowMat) {
  addRoundedBox(target, [pos[0], 0.62, pos[2]], [0.035, 1.20, 0.035], metalMat, 0.008, false);
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.34, 0.20, 40, 1, true), glowMat);
  shade.position.set(pos[0] + 0.28, 1.24, pos[2] - 0.16);
  shade.rotation.z = 0.35;
  target.add(shade);
  const light = new THREE.PointLight(0xffc38a, 0.95, 2.2);
  light.position.set(pos[0] + 0.20, 1.10, pos[2] - 0.18);
  target.add(light);
}

function addRoundedBox(target, pos, scale, mat, radius = 0.025, shadow = false) {
  const mesh = new THREE.Mesh(new RoundedBoxGeometry(1, 1, 1, 5, radius), mat);
  mesh.position.set(pos[0], pos[1], pos[2]);
  mesh.scale.set(scale[0], scale[1], scale[2]);
  mesh.castShadow = shadow;
  mesh.receiveShadow = shadow;
  target.add(mesh);
  return mesh;
}

function addPlant(target, pos, potMat, leafMat, scale = 1) {
  const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.12 * scale, 0.15 * scale, 0.24 * scale, 32), potMat);
  pot.position.set(pos[0], 0.12 * scale, pos[2]);
  pot.castShadow = true;
  pot.receiveShadow = true;
  target.add(pot);

  for (let i = 0; i < 5; i += 1) {
    const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.15 * scale, 24, 14), leafMat);
    const angle = i * 1.35;
    leaf.scale.set(1.0, 0.36, 0.62);
    leaf.position.set(pos[0] + Math.cos(angle) * 0.10 * scale, 0.34 * scale + i * 0.018 * scale, pos[2] + Math.sin(angle) * 0.10 * scale);
    leaf.rotation.set(0.5, angle, 0.25);
    leaf.castShadow = true;
    leaf.receiveShadow = true;
    target.add(leaf);
  }
}

function addHangingLamp(target, pos) {
  const cordMat = new THREE.MeshStandardMaterial({ color: 0x273342, roughness: 0.45 });
  const glowMat = new THREE.MeshStandardMaterial({
    color: 0xc99562,
    emissive: 0xffb25b,
    emissiveIntensity: 0.14,
    roughness: 0.28,
  });
  addRoundedBox(target, [pos[0], pos[1] + 0.18, pos[2]], [0.025, 0.38, 0.025], cordMat, 0.004, false);
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.32, 0.22, 40, 1, true), glowMat);
  shade.position.set(pos[0], pos[1], pos[2]);
  shade.castShadow = false;
  shade.receiveShadow = false;
  target.add(shade);
  const light = new THREE.PointLight(0xffc48a, 0.85, 3.2);
  light.position.set(pos[0], pos[1] - 0.16, pos[2]);
  target.add(light);
}

function createAura(agent) {
  const mat = new THREE.MeshBasicMaterial({
    color: new THREE.Color(agent.color),
    transparent: true,
    opacity: 0.34,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.32, 0.44, 96), mat);
  ring.rotation.x = -Math.PI / 2;
  ring.renderOrder = 2;
  return ring;
}

function makeFloorTexture() {
  const canvasTexture = document.createElement('canvas');
  canvasTexture.width = 512;
  canvasTexture.height = 512;
  const ctx = canvasTexture.getContext('2d');
  ctx.fillStyle = '#5a4639';
  ctx.fillRect(0, 0, 512, 512);
  for (let y = 0; y < 512; y += 64) {
    for (let x = 0; x < 512; x += 128) {
      const offset = (y / 64) % 2 ? 64 : 0;
      const tone = 72 + ((x + y) % 5) * 8;
      ctx.fillStyle = `rgb(${tone + 24}, ${tone + 4}, ${tone - 10})`;
      ctx.fillRect((x + offset) % 512, y + 2, 124, 60);
    }
  }
  ctx.strokeStyle = 'rgba(20,14,10,0.45)';
  ctx.lineWidth = 1;
  for (let y = 0; y <= 512; y += 64) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(512, y);
    ctx.stroke();
  }
  ctx.strokeStyle = 'rgba(255,220,175,0.12)';
  for (let i = 0; i < 120; i += 1) {
    const x = (i * 47) % 512;
    const y = (i * 83) % 512;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 36, y + 2);
    ctx.stroke();
  }
  const texture = new THREE.CanvasTexture(canvasTexture);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(2.8, 2.2);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeCityTexture() {
  const canvasTexture = document.createElement('canvas');
  canvasTexture.width = 1024;
  canvasTexture.height = 512;
  const ctx = canvasTexture.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 512);
  gradient.addColorStop(0, '#07101e');
  gradient.addColorStop(0.42, '#102642');
  gradient.addColorStop(1, '#050810');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 1024, 512);

  for (let i = 0; i < 72; i += 1) {
    const x = (i * 139) % 1024;
    const y = (i * 83) % 260;
    ctx.fillStyle = i % 3 === 0 ? 'rgba(255,214,152,0.9)' : 'rgba(105,196,255,0.72)';
    ctx.fillRect(x, y, 2 + (i % 2), 2 + (i % 3));
  }

  for (let i = 0; i < 28; i += 1) {
    const x = i * 42 - 12;
    const w = 28 + (i % 5) * 12;
    const h = 120 + (i % 7) * 36;
    ctx.fillStyle = i % 2 ? '#0d1728' : '#101f33';
    ctx.fillRect(x, 512 - h, w, h);
    for (let yy = 512 - h + 16; yy < 500; yy += 22) {
      for (let xx = x + 8; xx < x + w - 8; xx += 14) {
        if ((xx + yy + i) % 4 === 0) continue;
        ctx.fillStyle = (xx + yy) % 3 === 0 ? 'rgba(255,188,110,0.85)' : 'rgba(84,190,255,0.62)';
        ctx.fillRect(xx, yy, 4, 6);
      }
    }
  }

  const reflection = ctx.createLinearGradient(0, 280, 0, 512);
  reflection.addColorStop(0, 'rgba(83,166,255,0.16)');
  reflection.addColorStop(1, 'rgba(83,166,255,0)');
  ctx.fillStyle = reflection;
  ctx.fillRect(0, 280, 1024, 232);

  const texture = new THREE.CanvasTexture(canvasTexture);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeNeonTexture() {
  const canvasTexture = document.createElement('canvas');
  canvasTexture.width = 512;
  canvasTexture.height = 256;
  const ctx = canvasTexture.getContext('2d');
  ctx.clearRect(0, 0, 512, 256);
  ctx.font = '76px "Trebuchet MS", Arial, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.shadowColor = '#2ed8ff';
  ctx.shadowBlur = 22;
  ctx.strokeStyle = '#2ed8ff';
  ctx.lineWidth = 3;
  ctx.strokeText('Soul', 252, 90);
  ctx.strokeText('Forge', 252, 160);
  ctx.fillStyle = 'rgba(139,226,255,0.95)';
  ctx.fillText('Soul', 252, 90);
  ctx.fillText('Forge', 252, 160);
  const texture = new THREE.CanvasTexture(canvasTexture);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeScreenTexture() {
  const canvasTexture = document.createElement('canvas');
  canvasTexture.width = 512;
  canvasTexture.height = 320;
  const ctx = canvasTexture.getContext('2d');
  ctx.fillStyle = '#101827';
  ctx.fillRect(0, 0, 512, 320);
  ctx.fillStyle = 'rgba(55,198,255,0.20)';
  ctx.fillRect(28, 26, 456, 46);
  ctx.fillStyle = 'rgba(72,226,195,0.72)';
  for (let i = 0; i < 7; i += 1) {
    const h = 34 + (i % 3) * 30;
    ctx.fillRect(48 + i * 56, 250 - h, 26, h);
  }
  ctx.strokeStyle = 'rgba(255,255,255,0.22)';
  ctx.lineWidth = 2;
  for (let i = 0; i < 5; i += 1) {
    ctx.beginPath();
    ctx.moveTo(250, 120 + i * 28);
    ctx.lineTo(456, 120 + i * 28);
    ctx.stroke();
  }
  const texture = new THREE.CanvasTexture(canvasTexture);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeBackdropTexture() {
  const canvasTexture = document.createElement('canvas');
  canvasTexture.width = 1024;
  canvasTexture.height = 1024;
  const ctx = canvasTexture.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 1024);
  gradient.addColorStop(0, '#0b111b');
  gradient.addColorStop(0.58, '#101923');
  gradient.addColorStop(1, '#070b10');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 1024, 1024);
  const glowA = ctx.createRadialGradient(260, 190, 10, 260, 190, 420);
  glowA.addColorStop(0, 'rgba(95, 218, 255, 0.28)');
  glowA.addColorStop(1, 'rgba(95, 218, 255, 0)');
  ctx.fillStyle = glowA;
  ctx.fillRect(0, 0, 1024, 1024);
  const glowB = ctx.createRadialGradient(780, 260, 10, 780, 260, 360);
  glowB.addColorStop(0, 'rgba(255, 128, 210, 0.18)');
  glowB.addColorStop(1, 'rgba(255, 128, 210, 0)');
  ctx.fillStyle = glowB;
  ctx.fillRect(0, 0, 1024, 1024);
  const texture = new THREE.CanvasTexture(canvasTexture);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function smoothstep(x) {
  const v = Math.max(0, Math.min(1, x));
  return v * v * (3 - 2 * v);
}

window.__soulforge = {
  ready: () => loadedAgents.length === AGENTS.length,
  setTime: (seconds) => {
    window.__recordTime = seconds;
    updateScene(seconds);
    renderFrame();
  },
};
