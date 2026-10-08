/* VrmBody —— SoulForge 的浏览器端"虚拟身体"。

   把散落在 studio.js / demo/dinner.js / demo/main.js 三处的 VRM 驱动原语
   收敛成一个可复用模块，并吸收 aikeya（MIT）视觉层里值得拿的部分：
   - VRM0/1 手臂静息姿态符号翻转（VRM_POSE_CONFIG）
   - idle VRMA 轮换调度（不连续重复、1–2 循环后抖动切换、忙时推迟、crossfade）
   - talking VRMA 随说话状态 0.3s crossfade
   - 非对称眨眼曲线（闭 30% / 开 70%）
   - 多命名表情写入（aa/ee/ih/oh/ou ↔ a/i/u/e/o ↔ jawOpen）
   - 头部屏幕投影（供 DOM 气泡跟随）

   分层：
   1. 动画层：mixer 驱动 idle/talking/一次性 VRMA（有 idle 片段时）
      —— 没有 idle 片段时退回纯程序化姿态（呼吸/fidget/手臂）
   2. 生命层（叠加）：注视眼先头后、头部阻尼偏移、PAD 配方头姿 —— 以
      "加法"叠在动画层之上，不覆盖动捕数据
   3. 表情层：PAD 配方表情 ⊕ 直接表情 cue（Nous Tone 逐句读数）阻尼、眨眼、口型
      （视素在 vrm.update 之前写入）。说话时只让嘴部情绪形变让位给视素；
      模型缺的情绪通道按 expression_mixer 的映射换替身或交给头姿。

   已知坑（沿用 docs/sim_life_vtuber_demo.md）：
   - VRMA 动画插件与 VRM0 解析同挂一个 loader 会冲突 → 独立 loader
   - rotateVRM0 后模型 rotation.y=0 面向 -Z；相机放 +Z 即正面
   - 任意 VRM 可能缺表情通道 → setExpr 静默跳过 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName } from '@pixiv/three-vrm';
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from '@pixiv/three-vrm-animation';
import { PadMood, EXPR_CHANNELS } from './pad_expression.js';
import {
  ExpressionCue, planChannels, mixTargets, unshownHead, speakingGain, residualSums, regionShare,
  MOUTH_SPEAKING_GAIN, SPLIT_RESIDUAL_MAX,
} from './expression_mixer.js';
import { LipSync, VISEMES } from './lipsync.js';
import { loadAnyHumanoid, applyToonLook, removeToonLook } from './humanoid_adapter.js';

export const damp = (cur, target, lambda, dt) => cur + (target - cur) * (1 - Math.exp(-lambda * dt));

const FIDGETS = ['glance_left', 'glance_right', 'tilt', 'weight', 'chin_up'];
const B = VRMHumanBoneName;

/* 静息姿态（打破 T-pose）。VRM0 与 VRM1 的上臂 Z 轴符号相反 —— 来自 aikeya
   VrmModel.svelte 的实测结论；rotateVRM0 只翻转朝向不改骨骼轴向。 */
export const VRM_POSE_CONFIG = {
  '0': {
    leftUpperArm: { x: Math.PI * 0.05, y: 0, z: Math.PI * 0.4 },
    rightUpperArm: { x: Math.PI * 0.05, y: 0, z: -Math.PI * 0.4 },
    leftLowerArm: { x: 0, y: -Math.PI * 0.1, z: 0 },
    rightLowerArm: { x: 0, y: Math.PI * 0.1, z: 0 },
  },
  '1': {
    leftUpperArm: { x: Math.PI * 0.05, y: 0, z: -Math.PI * 0.4 },
    rightUpperArm: { x: Math.PI * 0.05, y: 0, z: Math.PI * 0.4 },
    leftLowerArm: { x: 0, y: -Math.PI * 0.1, z: 0 },
    rightLowerArm: { x: 0, y: Math.PI * 0.1, z: 0 },
  },
};

// 表情别名：VRM1 preset → VRM0 / ARKit 命名
const EXPR_ALIASES = {
  aa: ['a', 'A', 'jawOpen'], ee: ['e', 'E'], ih: ['i', 'I'], oh: ['o', 'O'], ou: ['u', 'U'],
  blink: ['Blink', 'blink_l', 'eyeBlinkLeft'],
  happy: ['joy', 'Joy', 'smile', 'Smile', 'fun', 'Fun'],
  sad: ['sorrow', 'Sorrow'], angry: ['Angry'], surprised: ['Surprised'], relaxed: ['Relaxed'],
};

export class VrmBody {
  /**
   * @param {THREE.Scene} scene
   * @param {{height?:number, intensity?:number, idleUrls?:string[], talkingUrl?:string}} opts
   */
  constructor(scene, opts = {}) {
    this.scene = scene;
    this.height = opts.height ?? 1.55;
    this.vrm = null;
    this.mood = new PadMood({ intensity: opts.intensity, baseline: opts.padBaseline });
    this.lipsync = new LipSync();

    this.loader = new GLTFLoader();
    this.loader.crossOrigin = 'anonymous';
    this.loader.register((p) => new VRMLoaderPlugin(p));
    this.vrmaLoader = new GLTFLoader();
    this.vrmaLoader.register((p) => new VRMAnimationLoaderPlugin(p));
    this.vrmaCache = new Map();          // url → VRMAnimation（模型无关，可复用）

    // 动画层
    this.mixer = null;
    this.idleUrls = opts.idleUrls ?? [];
    this.talkingUrl = opts.talkingUrl ?? null;
    this.idleAction = null; this.idleIndex = -1; this.idleTimer = 0; this.idleSwitchAt = Infinity;
    this.talkingAction = null;
    this.oneShot = null;                  // {action, until}
    this.animated = false;                // idle 片段是否已接管骨骼

    // 注视目标（眼睛立即跟，头部阻尼慢半拍）
    this.gazeTarget = new THREE.Object3D();
    this.gazeTarget.position.set(0, 1.35, 2.5);
    scene.add(this.gazeTarget);
    this.gaze = new THREE.Vector2(0, 0);
    this.origin = new THREE.Vector3(opts.x ?? 0, 0, opts.z ?? 0); // where this body stands
    this.lookPoint = null;                                        // world point overriding gaze (a partner's head)

    this.speakingLevel = 0;
    this.speaking = false;
    this.head = { x: 0, y: 0, z: 0 };
    this.expr = Object.fromEntries(EXPR_CHANNELS.map((k) => [k, 0]));
    this.cue = new ExpressionCue();             // 直接表情输入（逐句 tone 读数）
    this.exprPlan = planChannels(() => true);   // 本模型的通道映射（load 时按实际表情重算）
    this.faceRegions = {};                      // 通道 → {mouthShare, split?}（load 时分析形变）
    this.faceInfo = null;
    this.speakAmt = 0;                          // 说话程度 0..1（阻尼，避免让位跳变）
    this.cueGain = 1;
    this.nextFidget = 3; this.fidget = null;
    this.blinkTimer = 0; this.nextBlink = 2.5; this.blinkProgress = -1; this.doubleBlink = false;
    this.clock = new THREE.Clock();
    this._v3a = new THREE.Vector3(); this._v3b = new THREE.Vector3();
    this.onLog = null;
  }

  // ── 加载 ──────────────────────────────────────────────
  /**
   * 加载模型：.vrm 走 three-vrm 原生；.fbx/.glb 等经 humanoid_adapter 合成 VRM。
   * @param {string} url
   * @param {{kind?:string, toon?:boolean}} opts
   */
  async load(url, { kind, toon } = {}) {
    // 并发换装（启动时的 .soul 形象 vs 用户手动切换）：只有最后一次 load 能挂到场景上，
    // 否则两次 dispose 都先于加载完成，两个模型会叠在一起。
    const seq = (this._loadSeq = (this._loadSeq ?? 0) + 1);
    this.dispose();
    const ext = (kind && kind !== 'robot' ? kind : url.split('?')[0].split('.').pop()).toLowerCase();
    let vrm;
    let native = true;
    let clips = [], rig = null;
    if (ext === 'vrm') {
      const gltf = await this.loader.loadAsync(url);
      vrm = gltf.userData.vrm;
      if (!vrm) throw new Error('not a VRM: ' + url);
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
    } else {
      const res = await loadAnyHumanoid(url, { kind: ext });
      vrm = res.vrm; native = res.native; clips = res.animations ?? []; rig = res.rig;
    }
    if (seq !== this._loadSeq) {               // 被更新的一次 load 取代：丢弃，不挂场景
      VRMUtils.deepDispose(vrm.scene);
      return this.vrm;
    }
    if (ext !== 'vrm') {
      this.nativeClips = clips;
      this.rig = rig;
      if (native) { VRMUtils.removeUnnecessaryVertices(vrm.scene); VRMUtils.combineSkeletons(vrm.scene); }
    }
    VRMUtils.rotateVRM0(vrm);
    this.baseYaw = vrm.scene.rotation.y; // VRM0 gets π here: keep it under our walking yaw
    vrm.scene.traverse((o) => { o.frustumCulled = false; if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    this._normalize(vrm.scene, this.height);
    this.scene.add(vrm.scene);
    if (vrm.lookAt) vrm.lookAt.target = this.gazeTarget;
    this.vrm = vrm;
    this.native = native;
    this._analyzeFace();
    this.metaVersion = vrm.meta?.metaVersion === '1' ? '1' : '0';
    this._shin = null;
    this._restPose();
    this.mixer = new THREE.AnimationMixer(vrm.scene);
    this.animated = false;
    this.toon = false;
    if (toon ?? !native) this.setToon(true);
    if (this.idleUrls.length) await this._startIdle();
    if (this.talkingUrl) this._loadVrma(this.talkingUrl).catch(() => {});
    return vrm;
  }

  /** 卡通外观开关（非 VRM 模型默认开；VRM 自带 MToon）。 */
  setToon(on) {
    if (!this.vrm || this.toon === !!on) return;
    this.toon = !!on;
    if (on) applyToonLook(this.vrm.scene); else removeToonLook(this.vrm.scene);
  }

  _normalize(root, targetHeight) {
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    root.scale.setScalar(targetHeight / Math.max(0.1, size.y));
    const scaled = new THREE.Box3().setFromObject(root);
    const center = scaled.getCenter(new THREE.Vector3());
    root.position.x -= center.x; root.position.z -= center.z;
    root.position.y = -scaled.min.y;
    root.userData.floorY = root.position.y;
    root.userData.baseX = root.position.x; root.userData.baseZ = root.position.z;
    root.position.x += this.origin.x; root.position.z += this.origin.z;
  }

  /** Stand at (x, z) on the floor — several bodies share one stage. */
  place(x, z = 0) {
    this.origin.set(x, 0, z);
    const root = this.vrm?.scene;
    if (root) { root.position.x = (root.userData.baseX ?? 0) + x; root.position.z = (root.userData.baseZ ?? 0) + z; }
  }

  /** Head world position (or null before load). */
  getHeadWorld(out = new THREE.Vector3()) {
    const head = this.vrm?.humanoid?.getNormalizedBoneNode(B.Head);
    return head ? head.getWorldPosition(out) : null;
  }

  /** Walk to (x, z): turns toward the way, swings legs/arms (procedural walk cycle
   *  layered over idle), then turns back to the viewer. Poses are dropped while walking. */
  walkTo(x, z = 0, seconds = 2, offsetX = 0) {
    const from = this.origin.clone(); const to = new THREE.Vector3(x + offsetX, 0, z);
    const dist = from.distanceTo(to);
    if (dist < 0.05) return Promise.resolve();
    this.pose = null; this.lastPose = null;
    const dur = Math.max(0.8, dist / 0.7);
    this.walking = { from, to, dist, t0: performance.now(), dur, yaw: Math.atan2(to.x - from.x, to.z - from.z), phase: 0 };
    return new Promise((resolve) => { this.walking.done = resolve; });
  }
  _walkLayer(t, dt) {
    const w = this.walking; if (!w) { this.yaw = damp(this.yaw ?? 0, 0, 4, dt); if (this.vrm) this.vrm.scene.rotation.y = (this.baseYaw ?? 0) + this.yaw; return; }
    const p = Math.min(1, (performance.now() - w.t0) / (w.dur * 1000));
    const e = p < 0.15 ? p / 0.15 * 0.5 * p / 0.15 : p > 0.85 ? 1 - Math.pow((1 - p) / 0.15, 2) * 0.5 : (p - 0.075) / 0.85; // ease in/out, linear middle
    this.place(w.from.x + (w.to.x - w.from.x) * e, w.from.z + (w.to.z - w.from.z) * e);
    // face the way we go (VRM faces +Z at yaw 0), turn back to the viewer at the end
    const targetYaw = p < 0.8 ? w.yaw : 0;
    this.yaw = damp(this.yaw ?? 0, targetYaw, 4.5, dt); if (this.vrm) this.vrm.scene.rotation.y = (this.baseYaw ?? 0) + this.yaw;
    // step cycle: ~1.9 steps/s scaled by speed; amplitude fades in/out with the ease
    const speed = w.dist / w.dur; w.phase += dt * Math.PI * 2 * (1.9 * Math.min(1.4, speed / 0.7));
    const amp = Math.sin(Math.min(1, Math.min(p / 0.15, (1 - p) / 0.15)) * Math.PI / 2);
    const s1 = Math.sin(w.phase), s2 = Math.sin(w.phase + Math.PI);
    const sz = Math.sign(VRM_POSE_CONFIG[this.metaVersion].leftUpperArm.z);
    this.blendBone(B.LeftUpperLeg, -0.55 * s1, 0.04, 0, amp); this.blendBone(B.RightUpperLeg, -0.55 * s2, -0.04, 0, amp);
    this.blendBone(B.LeftLowerLeg, Math.max(0, 0.9 * s2) + 0.1, 0, 0, amp); this.blendBone(B.RightLowerLeg, Math.max(0, 0.9 * s1) + 0.1, 0, 0, amp);
    this.blendBone(B.LeftFoot, 0.15 * s1, 0, 0, amp); this.blendBone(B.RightFoot, 0.15 * s2, 0, 0, amp);
    this.blendBone(B.LeftUpperArm, 0.35 * s2 + 0.06, 0.04, sz * 1.25, amp); this.blendBone(B.RightUpperArm, 0.35 * s1 + 0.06, -0.04, -sz * 1.25, amp);
    this.addBone(B.Spine, 0.06 * amp, 0.05 * s1 * amp, 0);
    const root = this.vrm?.scene; if (root) root.position.y = (root.userData.floorY ?? 0) + Math.abs(Math.sin(w.phase)) * 0.025 * amp;
    if (p >= 1) { if (root) root.position.y = root.userData.floorY ?? 0; const done = w.done; this.walking = null; done?.(); }
  }

  /** Look at a world point (another character's head); null → back to the viewer. */
  lookAtPoint(point) { this.lookPoint = point ? point.clone() : null; }

  _restPose() {
    const cfg = VRM_POSE_CONFIG[this.metaVersion];
    for (const [bone, r] of Object.entries(cfg)) this.setBone(bone, r.x, r.y, r.z);
  }

  dispose() {
    if (this.mixer) this.mixer.stopAllAction();
    if (this.vrm) { this.scene.remove(this.vrm.scene); VRMUtils.deepDispose(this.vrm.scene); }
    this.vrm = null; this.mixer = null; this.idleAction = null; this.talkingAction = null; this.oneShot = null;
    this.animated = false;
  }

  // ── 动画层 ───────────────────────────────────────────
  async _loadVrma(url) {
    let anim = this.vrmaCache.get(url);
    if (!anim) {
      const gltf = await this.vrmaLoader.loadAsync(url);
      anim = gltf.userData.vrmAnimations?.[0];
      if (!anim) throw new Error('no VRMA in ' + url);
      this.vrmaCache.set(url, anim);
    }
    return anim;
  }

  _pickIdle() {
    const n = this.idleUrls.length;
    if (n <= 1) return 0;
    let i;
    do { i = Math.floor(Math.random() * n); } while (i === this.idleIndex);
    return i;
  }

  async _startIdle() {
    // 首次：把所有 idle 片段并行预取，之后切换零延迟（aikeya 每次重新 fetch 是 bug）
    await Promise.all(this.idleUrls.map((u) => this._loadVrma(u).catch(() => null)));
    await this._playIdle(0);
  }

  async _playIdle(fade) {
    const vrm = this.vrm;
    if (!vrm || !this.mixer) return;
    const i = this._pickIdle();
    const anim = this.vrmaCache.get(this.idleUrls[i]);
    if (!anim) return;
    this.idleIndex = i;
    const clip = createVRMAnimationClip(anim, vrm);
    const action = this.mixer.clipAction(clip);
    action.setLoop(THREE.LoopRepeat, Infinity);
    if (this.idleAction && fade > 0) {
      this.idleAction.fadeOut(fade);
      action.reset().fadeIn(fade).play();
    } else {
      action.reset().play();
    }
    this.idleAction = action;
    this.animated = true;
    // 1–2 个完整循环后切换（切点落在片段边界附近，带抖动）
    this.idleTimer = 0;
    this.idleSwitchAt = clip.duration * (1 + Math.random());
    this.onLog?.('idle → ' + this.idleUrls[i].split('/').pop());
  }

  _tickIdleCycle(dt) {
    if (!this.animated || !this.idleAction) return;
    this.idleTimer += dt;
    if (this.idleTimer < this.idleSwitchAt) return;
    if (this.speaking || this.oneShot) { this.idleSwitchAt = this.idleTimer + 2; return; } // 忙则推迟
    this._playIdle(1.2);
  }

  async _setTalking(on) {
    if (!this.animated || !this.talkingUrl || !this.vrm) return;
    if (on) {
      if (this.oneShot) return;
      if (!this.talkingAction) {
        const anim = await this._loadVrma(this.talkingUrl).catch(() => null);
        if (!anim || !this.vrm) return;
        const clip = createVRMAnimationClip(anim, this.vrm);
        this.talkingAction = this.mixer.clipAction(clip);
        this.talkingAction.setLoop(THREE.LoopRepeat, Infinity);
      }
      if (!this.speaking) return; // 加载期间已停止说话
      this.idleAction?.fadeOut(0.3);
      this.talkingAction.reset().fadeIn(0.3).play();
    } else if (this.talkingAction?.isRunning()) {
      this.talkingAction.fadeOut(0.3);
      this.idleAction?.reset().fadeIn(0.3).play();
    }
  }

  /** 一次性 VRMA（表演/情绪动作）：期间 idle/talking 让位，结束回 idle。 */
  async playVRMA(url) {
    if (!this.vrm) return;
    const anim = await this._loadVrma(url);
    if (!this.vrm) return;
    const clip = createVRMAnimationClip(anim, this.vrm);
    const action = this.mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = false;
    this.idleAction?.fadeOut(0.2);
    this.talkingAction?.fadeOut(0.2);
    action.reset().fadeIn(0.2).play();
    this.oneShot = { action, until: this.clock.elapsedTime + clip.duration };
    this.animated = true;
  }

  // ── 输入通道 ─────────────────────────────────────────
  setGaze(x, y) { this.gaze.set(x, y); }
  setPad(pad) { this.mood.onPad(pad); }
  setSpeaking(flag) {
    flag = !!flag;
    if (this.speaking === flag) return;
    this.speaking = flag;
    this.mood.onSpeaking(flag);
    this.lipsync.active = flag;
    this._setTalking(flag);
  }
  setSpeakingLevel(level) { this.speakingLevel = Math.max(0, Math.min(1, level)); }
  setAudioAnalyser(analyser) { this.lipsync.setAnalyser(analyser); }

  /**
   * 直接表情目标（绕过 PAD 配方量化）：weights 为 0..1 的 {happy,sad,angry,surprised,relaxed}
   * （Nous Tone 的 expression；其 neutral 份额显示 declared——这句台词的声明情绪——没有则显示 PAD）。
   * hold 秒内接管表情通道，过期后渐出交还 PAD；
   * 头姿/眨眼/目光仍由 PAD 驱动。仍走逐帧阻尼与说话让位，模型缺的通道按映射处理。
   */
  setExpressionTarget(weights, { hold = Infinity, meta = null, declared = null } = {}) {
    if (!weights || typeof weights !== 'object') return;
    this.cue.set(weights, { now: this.clock.elapsedTime, hold, meta, declared });
  }

  /** after 秒后结束直接表情接管（渐出，不跳变）。 */
  releaseExpressionTarget(after = 0) { this.cue.release(this.clock.elapsedTime, after); }

  /** 人格表情档（.soul expression / 问卷生成）：烈度 + PAD 基线。 */
  setMoodProfile(expression) {
    this.mood.setProfile(expression ?? {});
    // 读数 cue 的强度随人格烈度：克制的角色同样的读数表情更淡
    this.cueGain = 0.6 + 0.4 * this.mood.intensity;
  }

  /** 一次倾听式点头（叠加在生命层上）。 */
  nod() { this.nodAt = this.clock.elapsedTime; }

  /** 程序化保持姿态 seconds 秒：sit / kneel / lean_back / busy_hands（叠加层）。 */
  holdPose(name, seconds = 2) { if (this.walking) return; this.pose = { name, until: this.clock.elapsedTime + Math.max(0.3, seconds) }; }

  /** 头部在画布上的百分比坐标 {x,y}（0–100），供 DOM 气泡跟随。 */
  getHeadScreenPos(camera) {
    const head = this.vrm?.humanoid?.getNormalizedBoneNode(B.Head);
    if (!head) return null;
    head.getWorldPosition(this._v3a);
    this._v3b.set(this._v3a.x, this._v3a.y + 0.22, this._v3a.z + 0.1).project(camera);
    return { x: (this._v3b.x + 1) * 50, y: (-this._v3b.y + 1) * 50 };
  }

  // ── 每帧 ─────────────────────────────────────────────
  update() {
    const dt = Math.min(0.1, this.clock.getDelta());
    const t = this.clock.elapsedTime;
    const vrm = this.vrm;
    this.mood.update(dt);
    if (!vrm) return;

    // 1. 动画层
    if (this.oneShot && t >= this.oneShot.until) {
      this.oneShot.action.fadeOut(0.3);
      this.oneShot = null;
      (this.speaking && this.talkingAction ? this.talkingAction : this.idleAction)?.reset().fadeIn(0.3).play();
    }
    this._tickIdleCycle(dt);
    if (this.animated && this.mixer) this.mixer.update(dt);

    // 2. 生命层
    const breath = Math.sin(t * (1.6 + this.mood.pad.a * 0.6)) * 0.02;
    if (!this.animated) this._proceduralBody(vrm, t, dt, breath);
    if (!this.oneShot) this._gazeLayer(vrm, t, dt);
    this._walkLayer(t, dt);

    // 3. 表情层（口型必须在 vrm.update 之前写）
    this._face(vrm, t, dt);
    vrm.update(dt);
  }

  /** 注视 + 头部偏移 + PAD 头姿：叠加在当前骨骼旋转之上。 */
  _gazeLayer(vrm, t, dt) {
    const preset = this.mood.preset;
    const gy = this.gaze.y - (preset.gaze?.y ?? 0);
    let gx = this.gaze.x, gyy = gy;
    if (this.lookPoint) {
      // partner's head → eyes on it, head turns most of the way (bodies stay facing the viewer)
      this.gazeTarget.position.copy(this.lookPoint);
      const head = this.getHeadWorld(this._v3a) ?? this.origin;
      const dx = this.lookPoint.x - head.x, dz = this.lookPoint.z - head.z;
      gx = Math.max(-1, Math.min(1, Math.atan2(dx, Math.max(0.25, dz + 0.6)) / (Math.PI / 3)));
      gyy = Math.max(-1, Math.min(1, (head.y - this.lookPoint.y) * 1.5));
    } else {
      this.gazeTarget.position.set(this.origin.x + this.gaze.x * 1.6, 1.35 - gy * 0.8, this.origin.z + 2.2);
    }
    const headT = {
      x: gyy * 0.18 + (preset.head?.x ?? 0),
      y: gx * 0.32 * (this.lookPoint ? 2.2 : 1) + (preset.head?.y ?? 0),
      z: gx * -0.05 + (preset.head?.z ?? 0),
    };
    // 脸上显示不了的读数情绪（无该通道且无替身，如无表情的机器人模型）由头姿带出
    if (this.cue.blend > 0 && this.exprPlan.support !== 'full') {
      const h = unshownHead(this.cue.weights, this.exprPlan), b = this.cue.blend * this.cueGain;
      headT.x += b * h.x; headT.y += b * h.y; headT.z += b * h.z;
      if (!this.lookPoint) this.gazeTarget.position.y += b * h.gazeY * 0.8;
    }
    // fidget（动画层接管时只保留视线类小动作）
    let fx = 0, fy = 0, fz = 0;
    if (!this.fidget && t > this.nextFidget) {
      const pool = this.animated ? FIDGETS.slice(0, 3) : FIDGETS;
      this.fidget = { name: pool[Math.floor(Math.random() * pool.length)], start: t, dur: 1.6 + Math.random() * 1.2 };
    }
    if (this.fidget) {
      const p = (t - this.fidget.start) / this.fidget.dur;
      if (p >= 1) { this.fidget = null; this.nextFidget = t + (5 + Math.random() * 7) * (1 - this.mood.pad.a * 0.4); }
      else {
        const env = Math.sin(Math.min(1, p) * Math.PI);
        switch (this.fidget.name) {
          case 'glance_left': fy = 0.35 * env; fz = 0.06 * env; break;
          case 'glance_right': fy = -0.35 * env; fz = -0.06 * env; break;
          case 'tilt': fz = 0.14 * env; fx = 0.04 * env; break;
          case 'weight': this._fidgetHip = 0.12 * env; break;
          case 'chin_up': fx = -0.1 * env; break;
        }
      }
    }
    const talk = this.speakingLevel;
    // 倾听点头：0.09·e^{-1.6s}·max(0, sin 9s)（沿用 demo/dinner.js 的曲线）
    if (this.nodAt != null) {
      const since = t - this.nodAt;
      if (since > 1.2) this.nodAt = null;
      else fx += 0.09 * Math.exp(-since * 1.6) * Math.max(0, Math.sin(since * 9));
    }
    this.head.x = damp(this.head.x, headT.x + fx + talk * 0.05 * Math.sin(t * 7), 6, dt);
    this.head.y = damp(this.head.y, headT.y + fy, 5, dt);
    this.head.z = damp(this.head.z, headT.z + fz, 5, dt);
    this.addBone(B.Neck, this.head.x * 0.3, this.head.y * 0.35, this.head.z * 0.3);
    this.addBone(B.Head, this.head.x, this.head.y, this.head.z);
    this._poseLayer(t, dt);
  }

  /** 保持姿态叠加：不覆盖动画层，只在其上加一点身体语言。 */
  _poseLayer(t, dt) {
    if (!this.pose) { this.poseAmt = damp(this.poseAmt ?? 0, 0, 4, dt); if (this.poseAmt < 0.01) { if (this.vrm && this.lastPose && (this.lastPose === 'sit' || this.lastPose === 'kneel')) this.vrm.scene.position.y = this.vrm.scene.userData.floorY ?? this.vrm.scene.position.y; return; } }
    else if (t >= this.pose.until) this.pose = null;
    this.poseAmt = damp(this.poseAmt ?? 0, this.pose ? 1 : 0, 4, dt);
    const a = this.poseAmt, name = this.pose?.name ?? this.lastPose; if (this.pose) this.lastPose = name;
    const sz = Math.sign(VRM_POSE_CONFIG[this.metaVersion].leftUpperArm.z);
    switch (name) {
      case 'busy_hands': // 手在身前忙碌：上臂略前抬、肘前弯，手腕在腰前小幅动作（正X = 向前）
        this.addBone(B.LeftUpperArm, 0.75 * a, 0.2 * a, sz * 0.15 * a);
        this.addBone(B.RightUpperArm, 0.75 * a, -0.2 * a, -sz * 0.15 * a);
        this.addBone(B.LeftLowerArm, (1.5 + 0.15 * Math.sin(t * 5)) * a, sz * 0.4 * a, 0);
        this.addBone(B.RightLowerArm, (1.5 + 0.15 * Math.cos(t * 5)) * a, -sz * 0.4 * a, 0);
        this.addBone(B.Spine, 0.08 * a, 0, 0); this.addBone(B.Head, 0.22 * a, 0, 0); break;
      case 'lean_back': // 退后半步端详：站着时只是微微后仰+抬头看画，坐着时才真的靠回椅背
        { const seated = this.lastPose === 'sit' && this.poseAmt > 0.5 ? 1 : 0.35;
          this.addBone(B.Spine, -0.16 * a * seated, 0, 0); this.addBone(B.Chest, -0.06 * a * seated, 0, 0);
          this.addBone(B.Head, -0.14 * a, 0, 0);
          const szl = Math.sign(VRM_POSE_CONFIG[this.metaVersion].leftUpperArm.z);
          this.addBone(B.LeftUpperArm, 0.25 * a, 0.3 * a, szl * 0.1 * a); this.addBone(B.LeftLowerArm, 1.3 * a, szl * 0.6 * a, 0); // 一只手托着下巴/抱臂
          this.addBone(B.RightUpperArm, 0.2 * a, -0.2 * a, -szl * 0.1 * a); this.addBone(B.RightLowerArm, 1.1 * a, -szl * 0.3 * a, 0); }
        break;
      case 'sit': // 腿部覆盖动捕（相加会变成"马腿"），大腿水平、小腿垂直
        this.blendBone(B.LeftUpperLeg, -1.45, 0.08, 0, a); this.blendBone(B.RightUpperLeg, -1.45, -0.08, 0, a);
        this.blendBone(B.LeftLowerLeg, 1.45, 0, 0, a); this.blendBone(B.RightLowerLeg, 1.45, 0, 0, a);
        this.blendBone(B.LeftFoot, 0, 0, 0, a); this.blendBone(B.RightFoot, 0, 0, 0, a);
        this.addBone(B.Spine, -0.06 * a, 0, 0);
        if (this.vrm) this.vrm.scene.position.y = (this.vrm.scene.userData.floorY ?? 0) - this._shinLength() * a; break;
      case 'kneel': // 单膝跪：右腿跪地、左腿前弓
        this.blendBone(B.LeftUpperLeg, -1.3, 0.05, 0, a); this.blendBone(B.LeftLowerLeg, 1.3, 0, 0, a);
        this.blendBone(B.RightUpperLeg, -0.1, -0.05, 0, a); this.blendBone(B.RightLowerLeg, 2.2, 0, 0, a);
        this.addBone(B.Spine, 0.15 * a, 0, 0);
        if (this.vrm) this.vrm.scene.position.y = (this.vrm.scene.userData.floorY ?? 0) - this._shinLength() * a; break;
      default: break;
    }
  }

  /** 无 idle 片段时的纯程序化身体（呼吸/重心/手臂）。 */
  _proceduralBody(vrm, t, dt, breath) {
    const pad = this.mood.pad;
    const talk = this.speakingLevel;
    const playful = Math.max(0, pad.p) * Math.max(0, pad.a);
    const hipY = this._fidgetHip ?? 0; this._fidgetHip = 0;
    const slump = Math.max(0, -pad.p) * 0.04 + Math.max(0, -pad.a) * 0.03;
    const cfg = VRM_POSE_CONFIG[this.metaVersion];
    const sz = Math.sign(cfg.leftUpperArm.z); // VRM0 +, VRM1 -
    this.setBone(B.Hips, 0, hipY + Math.sin(t * 0.4) * 0.03, breath * 0.4);
    this.setBone(B.Chest, breath + 0.02 + talk * 0.02 + slump, Math.sin(t * 0.6) * 0.03 + hipY * -0.4, playful * 0.03 * Math.sin(t * 1.1));
    this.setBone(B.Neck, 0, 0, 0);
    this.setBone(B.Head, 0, 0, 0);
    const armLift = talk * 0.12 + playful * 0.05;
    this.setBone(B.LeftUpperArm, 0.06 + breath + armLift * Math.sin(t * 3.1), 0.04, sz * (1.3 - armLift));
    this.setBone(B.RightUpperArm, 0.06 + breath + armLift * Math.sin(t * 3.4 + 1), -0.04, -sz * (1.3 - armLift));
    this.setBone(B.LeftLowerArm, -0.18 - talk * 0.15, cfg.leftLowerArm.y, sz * 0.1);
    this.setBone(B.RightLowerArm, -0.18 - talk * 0.18, cfg.rightLowerArm.y, -sz * 0.1);
  }

  _face(vrm, t, dt) {
    const em = vrm.expressionManager;
    if (!em) return;
    const preset = this.mood.preset;
    this.cue.step(t, dt);

    // 眨眼：变间隔 + 偶发双眨；非对称曲线（闭 30% / 开 70%，aikeya）
    this.blinkTimer += dt;
    if (this.blinkProgress < 0 && this.blinkTimer >= this.nextBlink) {
      this.blinkProgress = 0; this.doubleBlink = Math.random() < 0.25;
    }
    let blink = 0;
    if (this.blinkProgress >= 0) {
      this.blinkProgress += dt * 8;
      const p = this.blinkProgress;
      blink = p < 0.3 ? p / 0.3 : Math.max(0, 1 - (p - 0.3) / 0.7);
      if (p >= 1) {
        if (this.doubleBlink) { this.doubleBlink = false; this.blinkProgress = 0; }
        else { this.blinkProgress = -1; this.blinkTimer = 0; this.nextBlink = (2 + Math.random() * 4) * (preset.blinkMul ?? 1); }
      }
    }

    // 情绪表情：PAD 配方 ⊕ 直接表情 cue → 本模型通道 → 逐帧阻尼。
    // 说话时只让嘴部让位给视素：可拆分的 VRoid 脸眉/眼满值、嘴 ×MOUTH_SPEAKING_GAIN；
    // 整块表情按其嘴部形变占比让位（未知时等同旧的整脸 ×0.45）。
    this.speakAmt = damp(this.speakAmt, this.speaking ? 1 : 0, 6, dt);
    const targets = mixTargets(preset.expr, this.cue, this.exprPlan, this.cueGain);
    const mouthGain = 1 - (1 - MOUTH_SPEAKING_GAIN) * this.speakAmt;
    for (const k of EXPR_CHANNELS) {
      this.expr[k] = damp(this.expr[k], targets[k], 2.5, dt);
      const region = this.faceRegions[k];
      if (region?.split) {
        this.setExpr(k, 0);
        const w = this.expr[k], { brw, eye, mth } = region.split.idx;
        for (const mesh of region.split.prims) {
          const inf = mesh.morphTargetInfluences;
          if (!inf) continue;
          if (brw != null) inf[brw] = w;
          if (eye != null) inf[eye] = w;
          inf[mth] = w * mouthGain;
        }
      } else {
        this.setExpr(k, this.expr[k] * speakingGain(region?.mouthShare, this.speakAmt));
      }
    }
    this.setExpr('blink', blink);

    // 口型：有分析器走五视素，否则退回 RMS→aa
    if (this.lipsync.analyser) {
      const w = this.lipsync.update(dt);
      for (const v of VISEMES) this.setExpr(v, w[v]);
      this.speakingLevel = this.lipsync.level;
    } else {
      this.setExpr('aa', this.speakingLevel * 0.85);
    }
  }

  // ── 表情能力分析（load 时一次）────────────────────────
  /** 通道映射 + 每个情绪表情的嘴部占比；VRoid 的 ALL 若严格等于 眉+眼+嘴 则按部位拆分驱动。 */
  _analyzeFace() {
    const em = this.vrm?.expressionManager;
    this.exprPlan = planChannels((k) => this.hasExpr(k));
    this.faceRegions = {};
    const split = [], mouthShare = {};
    if (em) {
      const masks = this._mouthMasks();
      const bound = this._boundMorphs(em);
      for (const k of EXPR_CHANNELS) {
        const ex = this._expression(k);
        if (!ex) continue;
        const r = this._regionsFor(ex, masks, bound);
        this.faceRegions[k] = r;
        if (r.split) split.push(k);
        if (r.mouthShare != null) mouthShare[k] = Math.round(r.mouthShare * 100) / 100;
      }
    }
    const plan = this.exprPlan;
    this.faceInfo = { support: plan.support, missing: plan.missing, fallbacks: plan.fallbacks, split, mouthShare };
    if (plan.support === 'none') {
      console.warn('[VrmBody] 模型没有情绪表情通道（只有口型/眨眼）：情绪改由头姿和目光表达');
      this.onLog?.('表情: 无情绪通道 → 头姿表达');
    } else if (plan.missing.length) {
      const how = plan.missing.map((k) => `${k}${plan.fallbacks[k] ? '→' + plan.fallbacks[k] : '→头姿'}`).join(', ');
      console.warn('[VrmBody] 模型缺少表情通道: ' + how);
      this.onLog?.('表情: 缺 ' + how);
    }
  }

  _expression(name) {
    const em = this.vrm?.expressionManager;
    if (!em) return null;
    for (const n of [name, ...(EXPR_ALIASES[name] ?? [])]) { const e = em.getExpression?.(n); if (e) return e; }
    return null;
  }

  static _morphBinds(ex) { return (ex?.binds ?? []).filter((b) => Array.isArray(b.primitives) && Number.isInteger(b.index)); }

  /** 视素（aa/ih/ou/ee/oh）实际移动的顶点 = 嘴部区域，按几何体记掩码。 */
  _mouthMasks() {
    const masks = new Map();
    for (const v of VISEMES) {
      for (const b of VrmBody._morphBinds(this._expression(v))) {
        for (const mesh of b.primitives) {
          const g = mesh.geometry, d = g?.morphAttributes?.position?.[b.index]?.array;
          if (!d) continue;
          const n = d.length / 3;
          let m = masks.get(g);
          if (!m) { m = new Uint8Array(n); masks.set(g, m); }
          for (let i = 0; i < n; i++) if (Math.abs(d[3 * i]) + Math.abs(d[3 * i + 1]) + Math.abs(d[3 * i + 2]) > 1e-5) m[i] = 1;
        }
      }
    }
    return masks;
  }

  /** 已被任何表情绑定的 (几何体, morph 序号)：拆分驱动不能去写它们。 */
  _boundMorphs(em) {
    const bound = new Set();
    for (const ex of em.expressions ?? []) {
      for (const b of VrmBody._morphBinds(ex)) for (const mesh of b.primitives) bound.add(mesh.geometry?.uuid + ':' + b.index);
    }
    return bound;
  }

  _regionsFor(ex, masks, bound) {
    const binds = VrmBody._morphBinds(ex);
    if (!binds.length) return { mouthShare: null };
    // 嘴部占比（全部图元合计的形变能量）
    let inMouth = 0, total = 0;
    for (const b of binds) {
      for (const mesh of b.primitives) {
        const d = mesh.geometry?.morphAttributes?.position?.[b.index]?.array, mask = masks.get(mesh.geometry);
        if (!d) continue;
        let e = 0;
        for (let i = 0; i < d.length; i++) e += d[i] * d[i];
        e *= b.weight * b.weight; total += e;
        if (mask) inMouth += e * regionShare(d, mask);
      }
    }
    const out = { mouthShare: total > 0 ? inMouth / total : null };
    // VRoid：单个 Fcl_ALL_X 绑定，且 BRW/EYE/MTH 部位形变之和严格还原 ALL → 按部位拆分
    if (binds.length !== 1 || Math.abs(binds[0].weight - 1) > 1e-3) return out;
    const b = binds[0], dict = b.primitives[0]?.morphTargetDictionary;
    if (!dict) return out;
    const name = Object.keys(dict).find((n) => dict[n] === b.index) ?? '';
    const m = /^(.*)Fcl_ALL_(.+)$/.exec(name);
    if (!m) return out;
    const [, pre, suf] = m, find = (...cands) => cands.map((c) => dict[pre + c]).find((i) => i != null);
    const idx = { brw: find(`Fcl_BRW_${suf}`), eye: find(`Fcl_EYE_${suf}`, `Fcl_Eye_${suf}`), mth: find(`Fcl_MTH_${suf}`) };
    if (idx.mth == null || (idx.brw == null && idx.eye == null)) return out;
    let num = 0, den = 0;
    for (const mesh of b.primitives) {
      const pos = mesh.geometry?.morphAttributes?.position, md = mesh.morphTargetDictionary;
      if (!pos || md?.[pre + 'Fcl_MTH_' + suf] !== idx.mth) return out;          // 各图元序号必须一致
      const parts = [idx.brw, idx.eye, idx.mth].filter((i) => i != null);
      if (parts.some((i) => bound.has(mesh.geometry.uuid + ':' + i))) return out; // 部位已被别的表情占用
      const [n, d] = residualSums(pos[b.index].array, parts.map((i) => pos[i].array));
      num += n; den += d;
    }
    if (den > 0 && num / den < SPLIT_RESIDUAL_MAX) out.split = { prims: b.primitives, idx, residual: num / den };
    return out;
  }

  // ── 原语 ─────────────────────────────────────────────
  setBone(name, x, y, z) {
    const node = this.vrm?.humanoid?.getNormalizedBoneNode(name);
    if (node) node.rotation.set(x, y, z);
  }

  /** 按权重 a 把骨骼从当前（动捕）旋转混合到目标旋转：姿态覆盖而非叠加。 */
  blendBone(name, x, y, z, a) {
    const node = this.vrm?.humanoid?.getNormalizedBoneNode(name);
    if (!node) return;
    node.rotation.set(node.rotation.x + (x - node.rotation.x) * a, node.rotation.y + (y - node.rotation.y) * a, node.rotation.z + (z - node.rotation.z) * a);
  }

  /** 小腿长度（世界单位）：坐下时身体要下沉的高度。 */
  _shinLength() {
    if (this._shin != null) return this._shin;
    const h = this.vrm?.humanoid; if (!h) return 0.4;
    const k = h.getNormalizedBoneNode(B.LeftLowerLeg), f = h.getNormalizedBoneNode(B.LeftFoot);
    if (!k || !f) return 0.4;
    this._shin = Math.max(0.2, Math.abs(k.getWorldPosition(this._v3a).y - f.getWorldPosition(this._v3b).y)) || 0.4;
    return this._shin;
  }

  addBone(name, x, y, z) {
    const node = this.vrm?.humanoid?.getNormalizedBoneNode(name);
    if (node) { node.rotation.x += x; node.rotation.y += y; node.rotation.z += z; }
  }

  setExpr(name, value) {
    const em = this.vrm?.expressionManager;
    if (!em) return;
    if (em.getExpression?.(name) != null) { em.setValue(name, value); return; }
    for (const alias of EXPR_ALIASES[name] ?? []) {
      if (em.getExpression?.(alias) != null) { em.setValue(alias, value); return; }
    }
  }

  hasExpr(name) {
    const em = this.vrm?.expressionManager;
    if (!em) return false;
    return em.getExpression?.(name) != null || (EXPR_ALIASES[name] ?? []).some((a) => em.getExpression?.(a) != null);
  }
}
