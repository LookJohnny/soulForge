/* VrmBody —— SoulForge 的浏览器端"虚拟身体"。

   把散落在 studio.js / demo/dinner.js / demo/main.js 三处的 VRM 驱动原语
   收敛成一个可复用模块：加载与归一化、注视、表情/骨骼阻尼、呼吸/眨眼/
   fidget 生命层、音频口型、VRMA 动捕片段、PAD 情绪预设。

   所有通道都走指数阻尼——没有任何姿态是瞬间到位的（Ani 式灵动）。

   已知坑（沿用 docs/sim_life_vtuber_demo.md）：
   - VRMA 动画插件与 VRM0 解析同挂一个 loader 会冲突 → 独立 loader
   - rotateVRM0 后模型 rotation.y=0 面向 -Z；相机放 +Z 即正面
   - 任意 VRM 可能缺表情通道 → setExpr 静默跳过 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName } from '@pixiv/three-vrm';
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from '@pixiv/three-vrm-animation';
import { PadMood, EXPR_CHANNELS } from './pad_expression.js';

export const damp = (cur, target, lambda, dt) => cur + (target - cur) * (1 - Math.exp(-lambda * dt));

const FIDGETS = ['glance_left', 'glance_right', 'tilt', 'weight', 'chin_up'];
const B = VRMHumanBoneName;

export class VrmBody {
  /**
   * @param {THREE.Scene} scene
   * @param {{height?:number, intensity?:number}} opts
   */
  constructor(scene, opts = {}) {
    this.scene = scene;
    this.height = opts.height ?? 1.55;
    this.vrm = null;
    this.mood = new PadMood({ intensity: opts.intensity });

    this.loader = new GLTFLoader();
    this.loader.register((p) => new VRMLoaderPlugin(p));
    this.vrmaLoader = new GLTFLoader();
    this.vrmaLoader.register((p) => new VRMAnimationLoaderPlugin(p));
    this.vrmaCache = new Map();
    this.mixer = null;
    this.vrmaAction = null;
    this.vrmaUntil = 0;

    // 注视目标（眼睛立即跟，头部阻尼慢半拍）
    this.gazeTarget = new THREE.Object3D();
    this.gazeTarget.position.set(0, 1.35, 2.5);
    scene.add(this.gazeTarget);
    this.gaze = new THREE.Vector2(0, 0);      // 归一化 -1..1

    this.speakingLevel = 0;                    // 0..1 音频包络
    this.speaking = false;
    this.head = { x: 0, y: 0, z: 0 };
    this.expr = Object.fromEntries(EXPR_CHANNELS.map((k) => [k, 0]));
    this.nextFidget = 3; this.fidget = null;
    this.nextBlink = 2.5; this.blinking = 0; this.doubleBlink = false;
    this.clock = new THREE.Clock();
    this.onLog = null;
  }

  // ── 加载 ──────────────────────────────────────────────
  async load(url) {
    this.dispose();
    const gltf = await this.loader.loadAsync(url);
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('not a VRM: ' + url);
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    VRMUtils.rotateVRM0(vrm);
    vrm.scene.traverse((o) => { o.frustumCulled = false; });
    this._normalize(vrm.scene, this.height);
    this.scene.add(vrm.scene);
    if (vrm.lookAt) vrm.lookAt.target = this.gazeTarget;
    this.vrm = vrm;
    return vrm;
  }

  _normalize(root, targetHeight) {
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    root.scale.setScalar(targetHeight / Math.max(0.1, size.y));
    const scaled = new THREE.Box3().setFromObject(root);
    root.position.y = -scaled.min.y;
    root.userData.floorY = root.position.y;
  }

  dispose() {
    if (this.vrm) { this.scene.remove(this.vrm.scene); VRMUtils.deepDispose(this.vrm.scene); }
    this.vrm = null; this.mixer = null; this.vrmaAction = null;
  }

  // ── 输入通道 ─────────────────────────────────────────
  setGaze(x, y) { this.gaze.set(x, y); }
  setPad(pad) { this.mood.onPad(pad); }
  setSpeaking(flag) { this.speaking = !!flag; this.mood.onSpeaking(flag); }
  setSpeakingLevel(level) { this.speakingLevel = Math.max(0, Math.min(1, level)); }

  /** 播放 VRMA 动捕片段：期间骨骼全权交给动画，生命层暂停。 */
  async playVRMA(url) {
    if (!this.vrm) return;
    let anim = this.vrmaCache.get(url);
    if (!anim) {
      const gltf = await this.vrmaLoader.loadAsync(url);
      anim = gltf.userData.vrmAnimations?.[0];
      if (!anim) throw new Error('no VRMA in ' + url);
      this.vrmaCache.set(url, anim);
    }
    const clip = createVRMAnimationClip(anim, this.vrm);
    this.mixer = new THREE.AnimationMixer(this.vrm.scene);
    this.vrmaAction = this.mixer.clipAction(clip);
    this.vrmaAction.setLoop(THREE.LoopOnce, 1);
    this.vrmaAction.clampWhenFinished = false;
    this.vrmaAction.play();
    this.vrmaUntil = this.clock.elapsedTime + clip.duration;
  }

  // ── 每帧 ─────────────────────────────────────────────
  update() {
    const dt = Math.min(0.1, this.clock.getDelta());
    const t = this.clock.elapsedTime;
    const vrm = this.vrm;
    this.mood.update(dt);
    if (!vrm) return;

    const vrmaLive = this.vrmaAction && t < this.vrmaUntil;
    if (vrmaLive) {
      this.mixer.update(dt);
    } else {
      if (this.vrmaAction) { this.vrmaAction = null; this.mixer = null; vrm.humanoid?.resetNormalizedPose?.(); }
      this._alive(vrm, t, dt);
    }
    this._face(vrm, t, dt);
    vrm.update(dt);
  }

  _alive(vrm, t, dt) {
    const preset = this.mood.preset;
    const pad = this.mood.pad;
    const breath = Math.sin(t * (1.6 + pad.a * 0.6)) * 0.02;

    // 注视：眼先头后；配方带目光偏移（害羞/低落向下，好奇向上）
    const gy = this.gaze.y - (preset.gaze?.y ?? 0);
    this.gazeTarget.position.set(this.gaze.x * 1.6, 1.35 - gy * 0.8, 2.2);
    const headT = {
      x: this.gaze.y * 0.18 + (preset.head?.x ?? 0),
      y: this.gaze.x * 0.32 + (preset.head?.y ?? 0),
      z: this.gaze.x * -0.05 + (preset.head?.z ?? 0),
    };

    // fidget：间隔随唤醒度缩放
    if (!this.fidget && t > this.nextFidget) {
      this.fidget = { name: FIDGETS[Math.floor(Math.random() * FIDGETS.length)], start: t, dur: 1.6 + Math.random() * 1.2 };
    }
    let fx = 0, fy = 0, fz = 0, hipY = 0, chestZ = 0;
    if (this.fidget) {
      const p = (t - this.fidget.start) / this.fidget.dur;
      if (p >= 1) { this.fidget = null; this.nextFidget = t + (5 + Math.random() * 7) * (1 - pad.a * 0.4); }
      else {
        const env = Math.sin(Math.min(1, p) * Math.PI);
        switch (this.fidget.name) {
          case 'glance_left': fy = 0.35 * env; fz = 0.06 * env; break;
          case 'glance_right': fy = -0.35 * env; fz = -0.06 * env; break;
          case 'tilt': fz = 0.14 * env; fx = 0.04 * env; break;
          case 'weight': hipY = 0.12 * env; chestZ = -0.05 * env; break;
          case 'chin_up': fx = -0.1 * env; break;
        }
      }
    }

    const talk = this.speakingLevel;
    const playful = Math.max(0, pad.p) * Math.max(0, pad.a);
    this.head.x = damp(this.head.x, headT.x + fx + talk * 0.05 * Math.sin(t * 7), 6, dt);
    this.head.y = damp(this.head.y, headT.y + fy, 5, dt);
    this.head.z = damp(this.head.z, headT.z + fz + playful * 0.06 * Math.sin(t * 1.1), 5, dt);

    // 低落/困倦时肩膀微沉，兴奋时挺胸
    const slump = Math.max(0, -pad.p) * 0.04 + Math.max(0, -pad.a) * 0.03;
    this.setBone(B.Hips, 0, hipY + Math.sin(t * 0.4) * 0.03, breath * 0.4);
    this.setBone(B.Chest, breath + 0.02 + talk * 0.02 + slump, Math.sin(t * 0.6) * 0.03 + hipY * -0.4, chestZ + playful * 0.03 * Math.sin(t * 1.1));
    this.setBone(B.Neck, this.head.x * 0.3, this.head.y * 0.35, this.head.z * 0.3);
    this.setBone(B.Head, this.head.x, this.head.y, this.head.z);
    const armLift = talk * 0.12 + playful * 0.05;
    this.setBone(B.LeftUpperArm, 0.06 + breath + armLift * Math.sin(t * 3.1), 0.04, 1.3 - armLift);
    this.setBone(B.RightUpperArm, 0.06 + breath + armLift * Math.sin(t * 3.4 + 1), -0.04, -1.3 + armLift);
    this.setBone(B.LeftLowerArm, -0.18 - talk * 0.15, 0, 0.1);
    this.setBone(B.RightLowerArm, -0.18 - talk * 0.18, 0, -0.1);
  }

  _face(vrm, t, dt) {
    const em = vrm.expressionManager;
    if (!em) return;
    const preset = this.mood.preset;

    // 眨眼：变间隔 + 偶发双眨；间隔随配方 blinkMul 缩放
    if (t > this.nextBlink) {
      this.blinking = t;
      this.doubleBlink = Math.random() < 0.25;
      this.nextBlink = t + (2.2 + Math.random() * 3.5) * (preset.blinkMul ?? 1);
    }
    let blink = 0;
    if (this.blinking) {
      const bp = t - this.blinking;
      if (bp < 0.12) blink = Math.sin((bp / 0.12) * Math.PI);
      else if (this.doubleBlink && bp < 0.3 && bp > 0.18) blink = Math.sin(((bp - 0.18) / 0.12) * Math.PI);
      else if (bp > 0.3) this.blinking = 0;
    }

    // 表情：说话时大表情让位（与舵机版一致），只保留微笑底色
    const gain = this.speaking ? 0.45 : 1;
    for (const k of EXPR_CHANNELS) {
      const target = (preset.expr?.[k] ?? 0) * gain;
      this.expr[k] = damp(this.expr[k], target, 2.5, dt);
      this.setExpr(k, this.expr[k]);
    }
    this.setExpr('blink', blink);
    this.setExpr('aa', this.speakingLevel * 0.85);
  }

  // ── 原语 ─────────────────────────────────────────────
  setBone(name, x, y, z) {
    const node = this.vrm?.humanoid?.getNormalizedBoneNode(name);
    if (node) node.rotation.set(x, y, z);
  }

  setExpr(name, value) {
    const em = this.vrm?.expressionManager;
    if (!em || em.getExpression?.(name) == null) return;
    em.setValue(name, value);
  }
}
