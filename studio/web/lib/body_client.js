/* BodyClient —— 浏览器作为 Protocol 0.2 的 `backend:"web"` 身体接入
   engine Runtime Server 的 /body 端点。

   ↑ hello(manifest) → ↓ welcome / plan_state / tick / action
   ↑ observation(accepted → done|failed|interrupted) / event(user_utterance …)

   每条 action 先回 accepted，动画执行完回 done；新 action 到来时若上一条
   interruptible，则先回 interrupted。对话（speak）默认交给 gateway 语音链路
   （features.speech=false → 服务端不下发 dialogue）。 */

import { STEP_TO_WEB, perform, translate } from './action_map.js';

export class BodyClient extends EventTarget {
  constructor({ url, bodyId = 'web-vrm', agentIds = [], speech = false } = {}) {
    super();
    this.url = url ?? `ws://${location.hostname}:8765/body`;
    this.bodyId = bodyId;
    this.agentIds = agentIds;
    this.speech = speech;
    this.ws = null;
    this.welcome = null;
    this.planState = {};
    this.current = null; // {command_id, agent_id, interruptible, cancel}
    this.queue = [];
    this.body = null;
    this.env = {};
  }

  attach(body, env = {}) { this.body = body; this.env = env; return this; }

  manifest() {
    return {
      body_id: this.bodyId, backend: 'web',
      supported_steps: Object.keys(STEP_TO_WEB).sort(), supported_templates: [],
      features: { speech: this.speech, gaze: true, nav: false, props: false }, step_substitutions: {},
    };
  }

  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', protocol: '0.2', body_id: this.bodyId, backend: 'web', agent_ids: this.agentIds, manifest: this.manifest() }));
      ws.onerror = (e) => { this._emit('error', e); reject(e); };
      ws.onclose = () => { this.ws = null; this._emit('close'); };
      ws.onmessage = (ev) => {
        let msg; try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === 'welcome') { this.welcome = msg; this._emit('welcome', msg); resolve(msg); return; }
        if (msg.type === 'plan_state') { this.planState[msg.agent_id] = msg; this._emit('plan_state', msg); return; }
        if (msg.type === 'tick') { this._emit('tick', msg); return; }
        if (msg.type === 'action') { this._onAction(msg); return; }
        this._emit('message', msg);
      };
      this.ws = ws;
    });
  }

  close() { this.ws?.close(); }

  send(obj) { if (this.ws?.readyState === 1) this.ws.send(JSON.stringify(obj)); }

  observe(cmd, status, extra = {}) {
    this.send({ type: 'observation', command_id: cmd.command_id, agent_id: cmd.agent_id, status, body_id: this.bodyId, ...extra });
  }

  /** 用户说话 → 引擎事件（standalone 模式；经 gateway 时由 CharacterBridge 转）。 */
  sendUtterance(text, agentId = this.agentIds[0]) {
    this.send({ type: 'event', kind: 'user_utterance', source: 'user', text, target_agent: agentId, payload: {} });
  }

  async _onAction(cmd) {
    if (this.agentIds.length && !this.agentIds.includes(cmd.agent_id)) return;
    const prim = translate(cmd);
    this._emit('action', { cmd, prim });
    if (this.current) {
      if (this.current.interruptible) { this.current.cancel(); this.observe(this.current, 'interrupted'); }
      else { this.queue.push(cmd); return; }
    }
    await this._run(cmd, prim);
  }

  async _run(cmd, prim) {
    let cancelled = false;
    this.current = { ...cmd, cancel: () => { cancelled = true; } };
    this.observe(cmd, 'accepted', { detail: `web:${prim.kind}`, payload: { mapped: prim.mapped, primitive: prim.kind } });
    try {
      if (this.body) await perform(this.body, prim, this.env);
      if (!cancelled) this.observe(cmd, 'done');
    } catch (e) {
      if (!cancelled) this.observe(cmd, 'failed', { detail: String(e?.message ?? e), error_code: 'E_WEB_ANIM' });
    } finally {
      if (this.current?.command_id === cmd.command_id) this.current = null;
      const next = this.queue.shift();
      if (next) this._run(next, translate(next));
    }
  }

  _emit(name, detail) { this.dispatchEvent(new CustomEvent(name, { detail })); }
}
