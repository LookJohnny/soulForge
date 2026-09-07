/* Shared, credential-free provider health indicator for every Studio surface. */

export function summarizeProviderHealth(data, reachable = true) {
  if (!reachable || !data || data.status === 'unavailable') {
    return { level: 'unknown', label: '大脑未连接' };
  }
  const providers = Array.isArray(data.providers) ? data.providers : [];
  if (data.fallback_active === true || providers.some((p) => p?.fallback_active === true)) {
    return { level: 'fallback', label: '兜底模式' };
  }
  const memory = data.memory;
  if (data.status !== 'ok' || !providers.length || providers.some((p) => p?.status !== 'ok')
      || data.ready === false || !memory || memory.ready === false
      || memory.persistent !== true || memory.last_error) {
    return { level: 'unknown', label: '大脑待确认' };
  }
  return { level: 'ok', label: '大脑正常' };
}

const safeText = (value) => value === undefined || value === null || value === '' ? '—' : String(value).slice(0, 1000);

export function mountProviderStatus(doc = document, fetcher = fetch) {
  if (doc.querySelector('soulforge-provider-status')) return;
  const host = doc.createElement('soulforge-provider-status');
  // Shadow DOM keeps this status visible when Live hides its ordinary HUD and
  // isolates it from Joi's cinematic typography or application button rules.
  const root = host.attachShadow({ mode: 'open' });
  const element = (tag, text, parent = root) => {
    const el = doc.createElement(tag);
    if (text !== undefined) el.textContent = safeText(text);
    parent.appendChild(el);
    return el;
  };
  const style = element('style');
  style.textContent = `
    :host{position:fixed;top:max(12px,env(safe-area-inset-top));right:12px;z-index:2147483647;
      display:block!important;font:12px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f5f3fa}
    *{box-sizing:border-box}button{font:inherit;color:inherit;cursor:pointer}
    .badge{display:flex;align-items:center;gap:7px;margin-left:auto;padding:7px 11px;background:rgba(15,13,23,.9);
      border:1px solid rgba(255,255,255,.2);border-radius:30px;box-shadow:0 2px 12px #0005}
    .badge:focus-visible,.close:focus-visible{outline:2px solid #e9d5ff;outline-offset:3px}
    .dot{width:7px;height:7px;flex:none;border-radius:50%;background:#e8b65c}
    .badge[data-level="ok"] .dot{background:#72dcab}
    .badge[data-level="fallback"] .dot{background:#ff6969;box-shadow:0 0 9px #ff696977}
    .panel{margin-top:9px;width:min(350px,calc(100vw - 24px));max-height:min(560px,75vh);overflow:auto;
      background:rgba(20,17,30,.98);border:1px solid #ffffff25;border-radius:14px;padding:16px;
      box-shadow:0 8px 32px #0008}.panel[hidden]{display:none}header{display:flex;align-items:center;justify-content:space-between}
    h2{font-size:14px;margin:0;font-weight:600}h3{font-size:12px;margin:14px 0 5px;color:#dccde9}
    .close{border:0;background:transparent;font-size:20px;line-height:1;padding:3px 5px}
    p{margin:6px 0;color:#bfb6cb;font-size:11px}dl{display:grid;grid-template-columns:76px minmax(0,1fr);gap:4px 10px;margin:6px 0}
    dt{color:#aaa1b7}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
    .notice{padding-top:7px;border-top:1px solid #ffffff15}
  `;
  const button = element('button');
  button.type = 'button'; button.className = 'badge'; button.dataset.level = 'unknown';
  button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-controls', 'provider-detail');
  const dot = element('span', undefined, button); dot.className = 'dot'; dot.setAttribute('aria-hidden', 'true');
  const label = element('span', '大脑待确认', button); label.setAttribute('aria-live', 'polite');
  const panel = element('section'); panel.className = 'panel'; panel.id = 'provider-detail'; panel.hidden = true;
  panel.setAttribute('role', 'region'); panel.setAttribute('aria-label', '中央大脑运行状态');
  const header = element('header', undefined, panel);
  element('h2', '中央大脑 · 运行状态', header);
  const close = element('button', '×', header); close.className = 'close'; close.type = 'button';
  close.setAttribute('aria-label', '关闭运行状态');
  const details = element('div', undefined, panel);
  element('p', '每 5 秒读取状态，不触发模型请求。绿色表示已有成功调用记录。', panel).className = 'notice';
  let stopped = false, pending = false, controller = null, timer = null;

  const row = (parent, key, value) => { element('dt', key, parent); element('dd', value, parent); };
  function render(data, reachable = true) {
    const summary = summarizeProviderHealth(data, reachable);
    button.dataset.level = summary.level;
    label.textContent = summary.label;
    button.setAttribute('aria-label', `${summary.label}，查看运行详情`);
    details.replaceChildren();
    const overall = element('dl', undefined, details);
    row(overall, '来源', 'Character Runtime');
    row(overall, '状态', summary.label);
    row(overall, '累计兜底', data?.fallback_count);
    if (!reachable || data?.status === 'unavailable') element('p', '无法读取中央大脑状态，请检查本地服务。', details);
    const providers = Array.isArray(data?.providers) ? data.providers : [];
    for (const provider of providers) {
      if (!provider || typeof provider !== 'object') continue;
      element('h3', provider.provider || '提供方', details);
      const list = element('dl', undefined, details);
      for (const [key, value] of [['模型', provider.model], ['状态', provider.status],
        ['调用次数', provider.calls], ['成功 / 失败', `${safeText(provider.successes)} / ${safeText(provider.failures)}`],
        ['连续失败', provider.consecutive_failures], ['兜底次数', provider.fallback_count],
        ['最近失败', provider.last_error], ['最近成功', provider.last_success_at]]) row(list, key, value);
    }
    element('h3', '记忆', details);
    const memory = data?.memory;
    const list = element('dl', undefined, details);
    row(list, '持久化', memory?.persistent === true ? '已启用' : memory?.persistent === false ? '未启用' : '未知');
    row(list, '就绪', memory?.ready === true ? '是' : memory?.ready === false ? '否' : memory?.status || '未知');
    row(list, '待写入', memory?.pending_writes);
    row(list, '已写入', memory?.writes_completed);
    row(list, '最近错误', memory?.last_error);
  }

  async function poll() {
    if (pending || stopped) return;
    clearTimeout(timer); pending = true; controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetcher('/health/providers', { cache: 'no-store', credentials: 'same-origin',
        headers: { Accept: 'application/json' }, signal: controller.signal });
      const data = await response.json();
      render(data, response.ok);
    } catch { render(null, false); }
    finally {
      clearTimeout(timeout); pending = false; controller = null;
      if (!stopped) timer = setTimeout(poll, 5000);
    }
  }
  function toggle(open) {
    panel.hidden = !open; button.setAttribute('aria-expanded', String(open));
    if (open) poll();
  }
  button.addEventListener('click', () => toggle(panel.hidden));
  close.addEventListener('click', () => { toggle(false); button.focus(); });
  root.addEventListener('keydown', (event) => { if (event.key === 'Escape') { toggle(false); button.focus(); } });
  doc.body.appendChild(host);
  render(null); poll();
  const visibility = () => { if (doc.visibilityState === 'visible') poll(); };
  doc.addEventListener('visibilitychange', visibility);
  const stop = () => {
    stopped = true; clearTimeout(timer); controller?.abort();
    doc.removeEventListener('visibilitychange', visibility);
  };
  doc.defaultView?.addEventListener('pagehide', stop, { once: true });
  return { stop, poll, render, host };
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => mountProviderStatus(), { once: true });
  else mountProviderStatus();
}
