import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const args = parseArgs(process.argv.slice(2));
const out = resolve(args.out ?? 'outputs/unity/soulforge_unity_replay_events.json');
const duration = Number(args.duration ?? 12);
const scale = duration / 12;

const events = [
  {
    time: 0.55 * scale,
    agentId: 'astra',
    agentName: 'Astra-F',
    actionTemplateId: 'coffee',
    dialogue: '早间陪伴模式启动，我先校准表情和动作。',
    emotion: 'warm',
    cameraShot: 'coffee',
    lookAtAgentId: 'mason',
    targetPosition: { x: -1.02, y: 0, z: -0.58 },
    voiceClipPath: 'voice/astra_000.wav',
    priority: 'PLAN',
  },
  {
    time: 1.65 * scale,
    agentId: 'mason',
    agentName: 'Mason-M',
    actionTemplateId: 'cook',
    dialogue: '厨房执行器上线，热源保持安全距离。',
    emotion: 'calm',
    cameraShot: 'kitchen',
    lookAtAgentId: 'astra',
    targetPosition: { x: -0.18, y: 0, z: -0.72 },
    voiceClipPath: 'voice/mason_001.wav',
    priority: 'PLAN',
  },
  {
    time: 2.75 * scale,
    agentId: 'hex',
    agentName: 'Hex-01',
    actionTemplateId: 'scan',
    dialogue: '非人形侦察单元在线，环境扫描开始。',
    emotion: 'robot',
    cameraShot: 'plant',
    lookAtAgentId: 'astra',
    targetPosition: { x: 1.04, y: 0, z: 0.30 },
    voiceClipPath: 'voice/hex_002.wav',
    priority: 'PLAN',
  },
  {
    time: 3.95 * scale,
    agentId: 'mason',
    agentName: 'Mason-M',
    actionTemplateId: 'talk',
    dialogue: '我会把任务拆成可执行的关节动作。',
    emotion: 'calm',
    cameraShot: 'conversation',
    lookAtAgentId: 'astra',
    targetPosition: { x: -0.32, y: 0, z: -0.24 },
    voiceClipPath: 'voice/mason_003.wav',
    priority: 'PLAN',
  },
  {
    time: 4.95 * scale,
    agentId: 'astra',
    agentName: 'Astra-F',
    actionTemplateId: 'talk',
    dialogue: '先照顾情绪，再安排今天的动作模板。',
    emotion: 'warm',
    cameraShot: 'conversation',
    lookAtAgentId: 'mason',
    targetPosition: { x: -0.98, y: 0, z: -0.18 },
    voiceClipPath: 'voice/astra_004.wav',
    priority: 'PLAN',
  },
  {
    time: 6.15 * scale,
    agentId: 'hex',
    agentName: 'Hex-01',
    actionTemplateId: 'scan',
    dialogue: '植物叶片状态正常，湿度偏低。',
    emotion: 'robot',
    cameraShot: 'plant',
    lookAtAgentId: 'astra',
    targetPosition: { x: 1.04, y: 0, z: 0.30 },
    voiceClipPath: 'voice/hex_005.wav',
    priority: 'PLAN',
  },
  {
    time: 7.25 * scale,
    agentId: 'astra',
    agentName: 'Astra-F',
    actionTemplateId: 'sketch',
    dialogue: '这个动作可以写成模板，明天直接复用。',
    emotion: 'happy',
    cameraShot: 'sketch',
    lookAtAgentId: 'mason',
    targetPosition: { x: -1.10, y: 0, z: 0.42 },
    voiceClipPath: 'voice/astra_006.wav',
    priority: 'PLAN',
  },
  {
    time: 8.25 * scale,
    agentId: 'mason',
    agentName: 'Mason-M',
    actionTemplateId: 'desk',
    dialogue: '我把舵机曲线和安全阈值一起保存。',
    emotion: 'steady',
    cameraShot: 'desk',
    lookAtAgentId: 'astra',
    targetPosition: { x: -0.36, y: 0, z: 0.52 },
    voiceClipPath: 'voice/mason_007.wav',
    priority: 'PLAN',
  },
  {
    time: 9.30 * scale,
    agentId: 'hex',
    agentName: 'Hex-01',
    actionTemplateId: 'repair',
    dialogue: '维修循环开始，扳手扭矩百分之七十。',
    emotion: 'robot',
    cameraShot: 'repair',
    lookAtAgentId: 'mason',
    targetPosition: { x: 1.14, y: 0, z: 0.54 },
    voiceClipPath: 'voice/hex_008.wav',
    priority: 'PLAN',
  },
  {
    time: 10.35 * scale,
    agentId: 'astra',
    agentName: 'Astra-F',
    actionTemplateId: 'dance',
    dialogue: '情绪反馈良好，动作幅度可以再柔一点。',
    emotion: 'happy',
    cameraShot: 'dance',
    lookAtAgentId: 'mason',
    targetPosition: { x: -0.84, y: 0, z: -0.62 },
    voiceClipPath: 'voice/astra_009.wav',
    priority: 'PLAN',
  },
  {
    time: 11.10 * scale,
    agentId: 'mason',
    agentName: 'Mason-M',
    actionTemplateId: 'call',
    dialogue: '晚间复盘完成，明天计划已锁定。',
    emotion: 'calm',
    cameraShot: 'sofa',
    lookAtAgentId: 'astra',
    targetPosition: { x: -0.24, y: 0, z: -0.64 },
    voiceClipPath: 'voice/mason_010.wav',
    priority: 'PLAN',
  },
];

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, `${JSON.stringify({ events }, null, 2)}\n`, 'utf8');
console.log(`wrote ${out}`);
console.log(`events ${events.length}`);

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith('--')) continue;
    const name = key.slice(2).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      parsed[name] = true;
    } else {
      parsed[name] = next;
      i += 1;
    }
  }
  return parsed;
}
