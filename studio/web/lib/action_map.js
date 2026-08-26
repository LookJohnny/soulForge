/* action_map —— Protocol 0.2 micro-step → web 原语。
   与 engine/embodiment/web_adapter.py 的 STEP_TO_WEB 逐键一致
   （tests/test_web_embodiment.py 钉死）。改表两边同步。 */

export const STEP_TO_WEB = {
  idle_breathing: { kind: 'idle' },
  idle: { kind: 'idle' },
  wait: { kind: 'idle' },
  wait_for_response: { kind: 'gaze', target: 'user' },
  resume_activity: { kind: 'idle' },
  look_at_user: { kind: 'gaze', target: 'user' },
  look_at_target: { kind: 'gaze', target: 'user' },
  look_around: { kind: 'clip', clip: 'LookAround' },
  listening_nod: { kind: 'gaze', target: 'user', nod: true },
  micro_nod: { kind: 'gaze', target: 'user', nod: true },
  speak_line: { kind: 'speak' },
  chatting: { kind: 'gaze', target: 'user' },
  invite_user: { kind: 'clip', clip: 'Goodbye' },
  report: { kind: 'gaze', target: 'user', nod: true },
  plate_up: { kind: 'pose', pose: 'busy_hands' },
  wave: { kind: 'clip', clip: 'Goodbye' },
  greet: { kind: 'clip', clip: 'Goodbye' },
  celebrate: { kind: 'clip', clip: 'Clapping' },
  clap: { kind: 'clip', clip: 'Clapping' },
  jump: { kind: 'clip', clip: 'Jump' },
  think: { kind: 'clip', clip: 'Thinking' },
  stretch: { kind: 'clip', clip: 'Relax' },
  rest: { kind: 'clip', clip: 'Relax' },
  sleepy: { kind: 'clip', clip: 'Sleepy' },
  surprised: { kind: 'clip', clip: 'Surprised' },
  sad: { kind: 'clip', clip: 'Sad' },
  angry: { kind: 'clip', clip: 'Angry' },
  blush: { kind: 'clip', clip: 'Blush' },
  stir_pan: { kind: 'pose', pose: 'busy_hands' },
  prep_ingredients: { kind: 'pose', pose: 'busy_hands' },
  draw_stroke: { kind: 'pose', pose: 'busy_hands' },
  take_note: { kind: 'pose', pose: 'busy_hands' },
  read_page: { kind: 'gaze', target: 'down' },
  study: { kind: 'gaze', target: 'down' },
  lean_back_review: { kind: 'pose', pose: 'lean_back' },
  sit_desk: { kind: 'pose', pose: 'sit' },
  sit_sofa: { kind: 'pose', pose: 'sit' },
  kneel_inspect: { kind: 'pose', pose: 'kneel' },
  scan_leaves: { kind: 'gaze', target: 'around' },
  probe_soil: { kind: 'gaze', target: 'down' },
  water_plant: { kind: 'pose', pose: 'busy_hands' },
  wipe_surface: { kind: 'pose', pose: 'busy_hands' },
  pick_item: { kind: 'pose', pose: 'busy_hands' },
  place_item: { kind: 'pose', pose: 'busy_hands' },
  pack_tools: { kind: 'pose', pose: 'busy_hands' },
  test_part: { kind: 'pose', pose: 'busy_hands' },
  turn_wrench: { kind: 'pose', pose: 'busy_hands' },
  adjust_pose: { kind: 'idle' },
  cleaning: { kind: 'pose', pose: 'busy_hands' },
  walk_to_kitchen: { kind: 'gaze', target: 'away' },
  walk_to_plants: { kind: 'gaze', target: 'away' },
  walk_to_sofa: { kind: 'gaze', target: 'away' },
  walk_to_zone: { kind: 'gaze', target: 'away' },
  approach_user: { kind: 'gaze', target: 'user' },
  safe_stop: { kind: 'idle' },
  hold_safe_breakpoint: { kind: 'idle' },
};

export const PERFORMANCE_TO_CLIP = {
  wave: 'Goodbye', stretch: 'Relax', clap: 'Clapping', jump: 'Jump', think: 'Thinking',
  look_around: 'LookAround', bow: 'Goodbye', dance: 'Jump', spin: 'Jump',
};

/** ActionCommand → 原语（与 Python translate() 同语义）。 */
export function translate(cmd) {
  const perf = cmd.params?.performance;
  let prim;
  if (perf && PERFORMANCE_TO_CLIP[perf]) prim = { kind: 'clip', clip: PERFORMANCE_TO_CLIP[perf] };
  else prim = { ...(STEP_TO_WEB[cmd.name] ?? { kind: 'gaze', target: 'user' }) };
  if (cmd.gaze_target && (prim.kind === 'idle' || prim.kind === 'pose')) prim.gaze = cmd.gaze_target === 'user' ? 'user' : 'around';
  return {
    ...prim,
    command_id: cmd.command_id, agent_id: cmd.agent_id, step: cmd.name,
    duration_s: Number(cmd.duration_s ?? 2), interruptible: cmd.interruptible !== false,
    dialogue: cmd.dialogue ?? null, mapped: cmd.name in STEP_TO_WEB || !!perf,
  };
}

const GAZE = { user: [0, 0], away: [0.9, -0.1], down: [0, 0.7], around: [-0.6, -0.2] };

/**
 * 把原语作用到 VrmBody。返回 Promise，在原语"完成"时 resolve（供 observation done）。
 * @param {import('./vrm_body.js').VrmBody} body
 * @param {object} prim
 * @param {{animations?: {name:string,url:string}[], speak?: (text:string)=>Promise<void>}} env
 */
export async function perform(body, prim, env = {}) {
  const ms = Math.max(300, (prim.duration_s ?? 2) * 1000);
  const sleep = (t) => new Promise((r) => setTimeout(r, t));
  switch (prim.kind) {
    case 'clip': {
      const asset = (env.animations ?? []).find((a) => a.url.toLowerCase().includes(`vrma_${prim.clip}`.toLowerCase()));
      if (asset) { await body.playVRMA(asset.url); await sleep(Math.min(ms, 8000)); }
      else { body.setGaze(0, 0); await sleep(ms); }
      return;
    }
    case 'gaze': {
      const [x, y] = GAZE[prim.target] ?? GAZE.user;
      body.setGaze(x, y);
      if (prim.nod) body.nod?.();
      await sleep(ms);
      if (prim.target !== 'user') body.setGaze(0, 0);
      return;
    }
    case 'pose': {
      body.holdPose?.(prim.pose, prim.duration_s ?? 2);
      if (prim.gaze) { const [x, y] = GAZE[prim.gaze] ?? GAZE.user; body.setGaze(x, y); }
      await sleep(ms);
      return;
    }
    case 'speak':
      if (prim.dialogue && env.speak) await env.speak(prim.dialogue);
      return;
    default:
      await sleep(Math.min(ms, 500));
  }
}
