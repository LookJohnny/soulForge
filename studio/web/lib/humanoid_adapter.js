/* humanoid_adapter —— 把任意人形骨架（Mixamo FBX / Unity Humanoid / glTF 通用命名 /
   MMD）合成为一个**真正的** three-vrm `VRM` 实例，让 VrmBody 的一切（VRMA 动捕
   重定向、PAD 表情、五视素口型、注视、头部投影、姿态叠加）零改动复用。

   原理：`@pixiv/three-vrm` 3.x 的 VRMHumanoid / VRMExpressionManager / VRMLookAt /
   VRM 全部可手工构造；`createVRMAnimationClip` 只依赖 vrm.humanoid/meta/
   expressionManager/lookAt/scene。VRM 的"标准化骨架"重定向本来就与文件格式无关。

   坑：
   - FBXLoader 会把骨骼名里的 ':' 去掉 → "mixamorigHips"（按前缀/正则匹配，别用等号）
   - FBX 是厘米尺度且不自动换算 → 交给 VrmBody._normalize 按包围盒归一
   - Mixamo 无 morph（无表情/口型）；glTF 的 morph 名依赖 extras.targetNames
   - 必须 root.add(humanoid.normalizedHumanBonesRoot)，否则 VRMA 轨道无处绑定
   - Unity 导出常见 A-pose → 建 Humanoid 前把上臂预旋到 T-pose */

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { FBXLoader } from 'three/examples/jsm/loaders/FBXLoader.js';
import {
  VRM, VRMHumanoid, VRMExpression, VRMExpressionManager, VRMExpressionMorphTargetBind,
  VRMLookAt, VRMLookAtBoneApplier, VRMLookAtRangeMap, VRMLoaderPlugin,
} from '@pixiv/three-vrm';
import { VRMLookAtQuaternionProxy } from '@pixiv/three-vrm-animation';

export class HumanoidAdapterError extends Error {
  constructor(message, missing = []) { super(message); this.name = 'HumanoidAdapterError'; this.missing = missing; }
}

/** VRMHumanoid 的 15 个必需骨。 */
export const REQUIRED_BONES = [
  'hips', 'spine', 'head',
  'leftUpperArm', 'leftLowerArm', 'leftHand', 'rightUpperArm', 'rightLowerArm', 'rightHand',
  'leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot',
];

/* ── 骨骼名表：每个 VRM 骨对应一组"归一化后"的候选名（小写、去 _ 空格 . : ）。
   顺序即优先级。左右用 {L}/{R} 占位，展开时替换。 */
const MIXAMO = {
  hips: ['hips'], spine: ['spine'], chest: ['spine1'], upperChest: ['spine2'], neck: ['neck'], head: ['head'],
  '{S}Shoulder': ['{S}shoulder'], '{S}UpperArm': ['{S}arm'], '{S}LowerArm': ['{S}forearm'], '{S}Hand': ['{S}hand'],
  '{S}UpperLeg': ['{S}upleg'], '{S}LowerLeg': ['{S}leg'], '{S}Foot': ['{S}foot'], '{S}Toes': ['{S}toebase'], '{S}Eye': ['{S}eye'],
  '{S}ThumbMetacarpal': ['{S}handthumb1'], '{S}ThumbProximal': ['{S}handthumb2'], '{S}ThumbDistal': ['{S}handthumb3'],
  '{S}IndexProximal': ['{S}handindex1'], '{S}IndexIntermediate': ['{S}handindex2'], '{S}IndexDistal': ['{S}handindex3'],
  '{S}MiddleProximal': ['{S}handmiddle1'], '{S}MiddleIntermediate': ['{S}handmiddle2'], '{S}MiddleDistal': ['{S}handmiddle3'],
  '{S}RingProximal': ['{S}handring1'], '{S}RingIntermediate': ['{S}handring2'], '{S}RingDistal': ['{S}handring3'],
  '{S}LittleProximal': ['{S}handpinky1'], '{S}LittleIntermediate': ['{S}handpinky2'], '{S}LittleDistal': ['{S}handpinky3'],
};
// Unity Humanoid / UniVRM 导出：VRM 命名直通（LeftUpperArm …）
const UNITY = {
  hips: ['hips'], spine: ['spine'], chest: ['chest'], upperChest: ['upperchest'], neck: ['neck'], head: ['head'], jaw: ['jaw'],
  '{S}Shoulder': ['{S}shoulder'], '{S}UpperArm': ['{S}upperarm'], '{S}LowerArm': ['{S}lowerarm'], '{S}Hand': ['{S}hand'],
  '{S}UpperLeg': ['{S}upperleg'], '{S}LowerLeg': ['{S}lowerleg'], '{S}Foot': ['{S}foot'], '{S}Toes': ['{S}toes'], '{S}Eye': ['{S}eye'],
  '{S}ThumbMetacarpal': ['{S}thumbmetacarpal', '{S}thumbproximal'], '{S}ThumbProximal': ['{S}thumbproximal', '{S}thumbintermediate'], '{S}ThumbDistal': ['{S}thumbdistal'],
  '{S}IndexProximal': ['{S}indexproximal'], '{S}IndexIntermediate': ['{S}indexintermediate'], '{S}IndexDistal': ['{S}indexdistal'],
  '{S}MiddleProximal': ['{S}middleproximal'], '{S}MiddleIntermediate': ['{S}middleintermediate'], '{S}MiddleDistal': ['{S}middledistal'],
  '{S}RingProximal': ['{S}ringproximal'], '{S}RingIntermediate': ['{S}ringintermediate'], '{S}RingDistal': ['{S}ringdistal'],
  '{S}LittleProximal': ['{S}littleproximal'], '{S}LittleIntermediate': ['{S}littleintermediate'], '{S}LittleDistal': ['{S}littledistal'],
};
// 通用别名（Blender/Rigify/UE/Cesium 等），{s} 为短边 l/r 后缀写法
const GENERIC = {
  hips: ['pelvis', 'roothip', 'hip', 'torsojoint1', 'bip01pelvis'], spine: ['spine01', 'spine1', 'torsojoint2', 'bip01spine'],
  chest: ['spine02', 'spine2', 'torsojoint3', 'bip01spine1'], upperChest: ['spine03', 'spine3', 'bip01spine2'],
  neck: ['neck01', 'neck1', 'neckjoint1', 'bip01neck'], head: ['head01', 'neckjoint2', 'bip01head'],
  '{S}Shoulder': ['clavicle{s}', '{s}clavicle', 'shoulder{s}'],
  '{S}UpperArm': ['upperarm{s}', '{s}upperarm', 'arm{s}', 'armjoint{S1}1'], '{S}LowerArm': ['lowerarm{s}', '{s}lowerarm', 'forearm{s}', 'armjoint{S1}2'],
  '{S}Hand': ['hand{s}', '{s}hand', 'armjoint{S1}3'],
  '{S}UpperLeg': ['thigh{s}', '{s}thigh', 'upleg{s}', 'legjoint{S1}1'], '{S}LowerLeg': ['calf{s}', '{s}calf', 'shin{s}', 'legjoint{S1}2'],
  '{S}Foot': ['foot{s}', '{s}foot', 'legjoint{S1}3'], '{S}Toes': ['toe{s}', 'ball{s}', 'legjoint{S1}5'], '{S}Eye': ['eye{s}', '{s}eye'],
};
// MMD（PMX 日文名；A3 vendor 加载器后启用）
export const MMD = {
  hips: ['下半身', 'センター'], spine: ['上半身'], chest: ['上半身2'], neck: ['首'], head: ['頭'],
  '{S}Shoulder': ['{J}肩'], '{S}UpperArm': ['{J}腕'], '{S}LowerArm': ['{J}ひじ'], '{S}Hand': ['{J}手首'],
  '{S}UpperLeg': ['{J}足'], '{S}LowerLeg': ['{J}ひざ'], '{S}Foot': ['{J}足首'], '{S}Toes': ['{J}つま先'], '{S}Eye': ['{J}目'],
  '{S}ThumbProximal': ['{J}親指０'], '{S}ThumbDistal': ['{J}親指１'],
  '{S}IndexProximal': ['{J}人指１'], '{S}IndexIntermediate': ['{J}人指２'], '{S}IndexDistal': ['{J}人指３'],
  '{S}MiddleProximal': ['{J}中指１'], '{S}MiddleIntermediate': ['{J}中指２'], '{S}MiddleDistal': ['{J}中指３'],
  '{S}RingProximal': ['{J}薬指１'], '{S}RingIntermediate': ['{J}薬指２'], '{S}RingDistal': ['{J}薬指３'],
  '{S}LittleProximal': ['{J}小指１'], '{S}LittleIntermediate': ['{J}小指２'], '{S}LittleDistal': ['{J}小指３'],
};

export const RIG_TABLES = { mixamo: MIXAMO, unity: UNITY, generic: GENERIC, mmd: MMD };

const SIDES = [
  { S: 'left', s: 'l', S1: 'L', J: '左' },
  { S: 'right', s: 'r', S1: 'R', J: '右' },
];

/** 展开 {S}/{s}/{S1}/{J} 占位，得到 vrmBone → [候选名…]。 */
export function expandTable(table) {
  const out = {};
  for (const [key, cands] of Object.entries(table)) {
    if (!key.includes('{S}')) { out[key] = cands.map(normName); continue; }
    for (const side of SIDES) {
      const vrm = side.S + key.replace('{S}', '');
      out[vrm] = cands.map((c) => normName(c.replaceAll('{S}', side.S).replaceAll('{s}', side.s).replaceAll('{S1}', side.S1).replaceAll('{J}', side.J)));
    }
  }
  return out;
}

/** 名字归一化：去掉 mixamorig 前缀、去 _ 空格 . : 、小写。 */
export function normName(n) {
  return String(n ?? '').replace(/^mixamorig\d*:?/i, '').replace(/^skeleton/i, '').replace(/[_\s.:\-()]/g, '').toLowerCase();
}

export function detectRig(root) {
  const names = [];
  root.traverse((o) => { if (o.isBone || o.type === 'Bone') names.push(o.name); });
  const joined = names.join('|').toLowerCase();
  if (/mixamorig/.test(joined)) return 'mixamo';
  if (/センター|上半身|下半身/.test(joined)) return 'mmd';
  if (/leftupperarm|rightupperleg/.test(joined.replace(/[_\s]/g, ''))) return 'unity';
  return 'generic';
}

/** 解析骨骼：返回 {vrmName: Bone}，缺失的必需骨列在 missing。 */
export function resolveBones(root, rig) {
  const bones = new Map();
  // 同名重复（Mixamo FBX：外层层级骨 + 同名叶子蒙皮骨）时选层级节点——它带着子骨一起动
  const put = (o) => {
    const k = normName(o.name);
    const prev = bones.get(k);
    if (!prev || (o.children.length > 0 && prev.children.length === 0)) bones.set(k, o);
  };
  root.traverse((o) => { if (o.isBone || o.type === 'Bone') put(o); });
  if (bones.size === 0) root.traverse((o) => { if (o.isObject3D && o.name) put(o); });
  const order = rig === 'generic' ? ['generic', 'unity', 'mixamo'] : [rig, 'generic', 'unity', 'mixamo'];
  const tables = order.map((r) => expandTable(RIG_TABLES[r]));
  const found = {};
  const allKeys = new Set(tables.flatMap((t) => Object.keys(t)));
  for (const vrm of allKeys) {
    for (const t of tables) {
      const cands = t[vrm] ?? [];
      const hit = cands.map((c) => bones.get(c)).find(Boolean)
        ?? cands.map((c) => [...bones.entries()].find(([k]) => k.endsWith(c))?.[1]).find(Boolean);
      if (hit) { found[vrm] = hit; break; }
    }
  }
  chainFallback(found, bones);
  const missing = REQUIRED_BONES.filter((b) => !found[b]);
  return { found, missing, boneCount: bones.size };
}

/** 名字表失败时按层级兜底：同侧含 arm/leg 的骨按祖先→后代排序，依次当
   （肩）上臂/前臂/手 或 大腿/小腿/脚/脚趾。覆盖 Cesium 这类乱编号的骨架。 */
function chainFallback(found, bones) {
  const depth = (o) => { let d = 0; for (let p = o.parent; p; p = p.parent) d++; return d; };
  // 用原始名判左右：归一化名去掉了分隔符，"L" 会粘在字母上
  const sideOf = (o) => {
    const n = String(o.name ?? '');
    if (/(^|[^a-z])(l|left)([^a-z]|$)/i.test(n) || /左/.test(n)) return 'left';
    if (/(^|[^a-z])(r|right)([^a-z]|$)/i.test(n) || /右/.test(n)) return 'right';
    return null;
  };
  for (const [limb, slots] of [['arm', ['UpperArm', 'LowerArm', 'Hand']], ['leg', ['UpperLeg', 'LowerLeg', 'Foot', 'Toes']]]) {
    for (const side of ['left', 'right']) {
      if (slots.slice(0, 3).every((s) => found[side + s])) continue;
      const chain = [...bones.entries()]
        .filter(([k, o]) => k.includes(limb) && sideOf(o) === side)
        .map(([, o]) => o)
        .sort((a, b) => depth(a) - depth(b));
      if (chain.length < 3) continue;
      const start = chain.length >= 4 && limb === 'arm' ? 1 : 0; // 4+ arm bones: first is the shoulder
      if (limb === 'arm' && chain.length >= 4 && !found[side + 'Shoulder']) found[side + 'Shoulder'] = chain[0];
      slots.forEach((slot, i) => { const o = chain[start + i]; if (o && !found[side + slot]) found[side + slot] = o; });
    }
  }
}

/** 把模型转到面向 +Z（VRM1 约定）：facing = up × (左上臂→右上臂)。 */
function faceForward(root, found) {
  const l = found.leftUpperArm ?? found.leftUpperLeg, r = found.rightUpperArm ?? found.rightUpperLeg;
  if (!l || !r) return;
  const lp = l.getWorldPosition(new THREE.Vector3()), rp = r.getWorldPosition(new THREE.Vector3());
  const lr = rp.sub(lp); lr.y = 0;
  if (lr.lengthSq() < 1e-8) return;
  const facing = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), lr.normalize());
  const yaw = Math.atan2(facing.x, facing.z); // angle from +Z
  if (Math.abs(yaw) > 0.05) { root.rotation.y -= yaw; root.updateMatrixWorld(true); }
}

/** 恢复绑定姿态：three 的蒙皮公式下静息 ⇔ bone.matrixWorld = boneInverse⁻¹，即 Skeleton.pose()。 */
function resetToBindPose(root) {
  root.traverse((o) => { if (o.isSkinnedMesh && o.skeleton) o.skeleton.pose(); });
}
const depthOf = (o) => { let d = 0; for (let p = o.parent; p; p = p.parent) d++; return d; };

/** 把骨 bone 绕世界轴旋转，使 (bone→child) 世界方向对齐 target。 */
function alignSegment(bone, child, target) {
  if (!bone || !child) return;
  const a = bone.getWorldPosition(new THREE.Vector3()), b = child.getWorldPosition(new THREE.Vector3());
  const dir = b.sub(a); if (dir.lengthSq() < 1e-8) return;
  dir.normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(dir, target.clone().normalize());
  const wq = bone.getWorldQuaternion(new THREE.Quaternion());
  const newWorld = q.multiply(wq);
  const parentInv = bone.parent ? bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert() : new THREE.Quaternion();
  bone.quaternion.copy(parentInv.multiply(newWorld));
  bone.updateWorldMatrix(true, true);
}

/** T-pose 摆正：手臂水平指向 ±X，腿竖直向下。 */
function enforceTPose(found) {
  const X = new THREE.Vector3(1, 0, 0), DOWN = new THREE.Vector3(0, -1, 0);
  for (const side of ['left', 'right']) {
    const x = side === 'left' ? X : X.clone().negate();
    alignSegment(found[`${side}UpperArm`], found[`${side}LowerArm`], x);
    alignSegment(found[`${side}LowerArm`], found[`${side}Hand`], x);
    alignSegment(found[`${side}UpperLeg`], found[`${side}LowerLeg`], DOWN);
    alignSegment(found[`${side}LowerLeg`], found[`${side}Foot`], DOWN);
  }
}

/* ── 表情：VRM 通道 ← 候选 morph 名（带权重；可多 morph 组合）── */
export const EXPR_MAP = {
  aa: [['jawOpen', 1], ['A', 1], ['a', 1], ['Fcl_MTH_A', 1], ['vrc.v_aa', 1], ['MTH_A', 1], ['あ', 1]],
  ih: [['I', 1], ['i', 1], ['Fcl_MTH_I', 1], ['vrc.v_ih', 1], ['MTH_I', 1], ['い', 1]],
  ou: [['mouthPucker', 1], ['U', 1], ['u', 1], ['Fcl_MTH_U', 1], ['vrc.v_ou', 1], ['MTH_U', 1], ['う', 1]],
  ee: [['E', 1], ['e', 1], ['Fcl_MTH_E', 1], ['vrc.v_e', 1], ['MTH_E', 1], ['え', 1]],
  oh: [['mouthFunnel', 1], ['O', 1], ['o', 1], ['Fcl_MTH_O', 1], ['vrc.v_oh', 1], ['MTH_O', 1], ['お', 1]],
  blink: [['eyeBlinkLeft', 1], ['eyeBlinkRight', 1], ['Blink', 1], ['blink', 1], ['Fcl_EYE_Close', 1], ['EYE_Close', 1], ['まばたき', 1]],
  blinkLeft: [['eyeBlinkLeft', 1], ['Blink_L', 1], ['Fcl_EYE_Close_L', 1], ['ウィンク', 1]],
  blinkRight: [['eyeBlinkRight', 1], ['Blink_R', 1], ['Fcl_EYE_Close_R', 1], ['ウィンク右', 1]],
  happy: [['mouthSmileLeft', 1], ['mouthSmileRight', 1], ['cheekSquintLeft', 0.5], ['cheekSquintRight', 0.5], ['Joy', 1], ['joy', 1], ['Fun', 1], ['Fcl_ALL_Joy', 1], ['smile', 1], ['笑い', 1]],
  sad: [['mouthFrownLeft', 1], ['mouthFrownRight', 1], ['browInnerUp', 0.6], ['Sorrow', 1], ['sorrow', 1], ['Fcl_ALL_Sorrow', 1], ['困る', 1]],
  angry: [['browDownLeft', 1], ['browDownRight', 1], ['noseSneerLeft', 0.3], ['Angry', 1], ['angry', 1], ['Fcl_ALL_Angry', 1], ['怒り', 1]],
  surprised: [['jawOpen', 0.4], ['browInnerUp', 1], ['eyeWideLeft', 1], ['eyeWideRight', 1], ['Surprised', 1], ['surprised', 1], ['Fcl_ALL_Surprised', 1], ['びっくり', 1]],
  relaxed: [['eyeSquintLeft', 0.3], ['eyeSquintRight', 0.3], ['mouthSmileLeft', 0.2], ['mouthSmileRight', 0.2], ['Relaxed', 1], ['relaxed', 1], ['Fcl_ALL_Fun', 1], ['にこり', 1]],
};

/** 从所有带 morph 的 mesh 上构建表情管理器。返回 {manager, expressions, bound:[names]}。 */
export function buildExpressions(root) {
  const manager = new VRMExpressionManager();
  const meshes = [];
  root.traverse((o) => { if (o.isMesh && o.morphTargetInfluences?.length) { if (!o.morphTargetDictionary) o.updateMorphTargets?.(); meshes.push(o); } });
  const bound = [];
  for (const [name, cands] of Object.entries(EXPR_MAP)) {
    const expr = new VRMExpression(name);
    let binds = 0;
    for (const mesh of meshes) {
      const dict = mesh.morphTargetDictionary ?? {};
      const lower = Object.fromEntries(Object.keys(dict).map((k) => [k.toLowerCase(), k]));
      // 只要命中同一“来源系”的候选就绑定；ARKit/VRoid/MMD 互斥不会同时存在
      for (const [cand, weight] of cands) {
        const key = dict[cand] != null ? cand : lower[cand.toLowerCase()];
        if (key == null) continue;
        expr.addBind(new VRMExpressionMorphTargetBind({ primitives: [mesh], index: dict[key], weight }));
        binds++;
      }
    }
    if (binds) { manager.registerExpression(expr); root.add(expr); bound.push(name); }
  }
  return { manager, bound, morphMeshes: meshes.length };
}

/** 合成 VRM。 */
export function buildVRM(root, { rig = 'generic', metaVersion = '1', faceFront = null } = {}) {
  // 1. 骨骼回到绑定姿态：FBX 常把骨骼存成动画第一帧（跳舞姿势），拿它当静息会让四肢散架。
  root.updateMatrixWorld(true);
  resetToBindPose(root);
  root.updateMatrixWorld(true); // VRMHumanoid 从 matrixWorld 捕获静息姿态——必须先刷新
  const { found, missing, boneCount } = resolveBones(root, rig);
  if (missing.length) throw new HumanoidAdapterError(`不是可识别的人形骨架（缺 ${missing.join(', ')}；共 ${boneCount} 根骨）`, missing);
  // 2. 朝向：VRM1 约定面向 +Z；用左右上臂连线求面朝方向，绕 Y 转正
  faceForward(root, found);
  // 3. 静息必须是 T-pose（VRMA 重定向的前提）：A-pose / 行走站姿一律摆正
  enforceTPose(found);
  root.updateMatrixWorld(true);
  const humanBones = Object.fromEntries(Object.entries(found).map(([k, node]) => [k, { node }]));
  const humanoid = new VRMHumanoid(humanBones);
  root.add(humanoid.normalizedHumanBonesRoot);

  const { manager, bound, morphMeshes } = buildExpressions(root);
  const rm = () => new VRMLookAtRangeMap(90, 10);
  const lookAt = new VRMLookAt(humanoid, new VRMLookAtBoneApplier(humanoid, rm(), rm(), rm(), rm()));
  if (faceFront) lookAt.faceFront.copy(faceFront);
  const proxy = new VRMLookAtQuaternionProxy(lookAt); proxy.name = 'VRMLookAtQuaternionProxy'; root.add(proxy);

  const vrm = new VRM({ scene: root, meta: { metaVersion, name: root.name || 'humanoid' }, humanoid, expressionManager: manager, lookAt });
  vrm.userData = { ...(vrm.userData ?? {}), adapter: { rig, bones: Object.keys(found).length, expressions: bound, morphMeshes } };
  return vrm;
}

/* ── 卡通外观：MeshToon + 反向外壳描边（VRM 已有 MToon，默认不用）── */
let _gradient = null;
function toonGradient() {
  if (_gradient) return _gradient;
  const data = new Uint8Array([90, 90, 90, 255, 160, 160, 160, 255, 255, 255, 255, 255]);
  const tex = new THREE.DataTexture(data, 3, 1, THREE.RGBAFormat);
  tex.minFilter = tex.magFilter = THREE.NearestFilter; tex.needsUpdate = true;
  return (_gradient = tex);
}

export function applyToonLook(root, { outline = true, outlineWidth = 0.015 } = {}) {
  const outlines = [];
  root.traverse((o) => {
    if (!o.isMesh || o.userData.__outline) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    const toon = mats.map((m) => {
      if (!m || m.isMeshToonMaterial || /MToon/i.test(m.type ?? '')) return m;
      const t = new THREE.MeshToonMaterial({ color: m.color ?? new THREE.Color(0xffffff), map: m.map ?? null, gradientMap: toonGradient(), transparent: !!m.transparent, opacity: m.opacity ?? 1, side: m.side ?? THREE.FrontSide, skinning: true });
      t.name = (m.name || 'mat') + '_toon'; t.userData.__orig = m; return t;
    });
    o.material = Array.isArray(o.material) ? toon : toon[0];
    if (outline) {
      const shell = o.isSkinnedMesh ? new THREE.SkinnedMesh(o.geometry, null) : new THREE.Mesh(o.geometry);
      shell.material = new THREE.MeshBasicMaterial({ color: 0x101010, side: THREE.BackSide, depthWrite: false });
      shell.material.onBeforeCompile = (s) => { s.vertexShader = s.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>\n transformed += normalize(objectNormal) * ${outlineWidth.toFixed(4)};`); };
      if (o.isSkinnedMesh) { shell.bind(o.skeleton, o.bindMatrix); }
      shell.userData.__outline = true; shell.frustumCulled = false; shell.renderOrder = -1;
      o.add(shell); outlines.push(shell);
    }
  });
  return outlines;
}

export function removeToonLook(root) {
  root.traverse((o) => {
    if (!o.isMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    const back = mats.map((m) => m?.userData?.__orig ?? m);
    o.material = Array.isArray(o.material) ? back : back[0];
    for (const c of [...o.children]) if (c.userData.__outline) o.remove(c);
  });
}

/* ── 加载入口 ── */
const fbxLoader = new FBXLoader();
const gltfLoader = new GLTFLoader();
gltfLoader.register((p) => new VRMLoaderPlugin(p));

/**
 * 加载任意人形模型 → VRM。返回 {vrm, rig, animations, native:boolean}。
 * native=true 表示文件本身就是 VRM（原路返回，交给 VrmBody 走 VRMUtils 优化）。
 */
export async function loadAnyHumanoid(url, { kind } = {}) {
  const ext = (kind ?? url.split('?')[0].split('.').pop()).toLowerCase();
  if (ext === 'fbx') {
    const root = await fbxLoader.loadAsync(url);
    const rig = detectRig(root);
    const group = root.isGroup ? root : new THREE.Group().add(root);
    group.name = decodeURIComponent(url.split('/').pop());
    const vrm = buildVRM(group, { rig, metaVersion: '1' });
    return { vrm, rig, animations: root.animations ?? [], native: false };
  }
  if (ext === 'glb' || ext === 'gltf') {
    const gltf = await gltfLoader.loadAsync(url);
    if (gltf.userData.vrm) return { vrm: gltf.userData.vrm, rig: 'vrm', animations: gltf.animations ?? [], native: true };
    const root = gltf.scene;
    const rig = detectRig(root);
    const vrm = buildVRM(root, { rig, metaVersion: '1' });
    return { vrm, rig, animations: gltf.animations ?? [], native: false };
  }
  if (ext === 'pmx') throw new HumanoidAdapterError('MMD (PMX) 加载器尚未接入（计划 A3）');
  const gltf = await gltfLoader.loadAsync(url);
  if (!gltf.userData.vrm) throw new HumanoidAdapterError('不是 VRM 文件');
  return { vrm: gltf.userData.vrm, rig: 'vrm', animations: [], native: true };
}
