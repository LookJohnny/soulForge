import { TavusVideoClient } from './lib/tavus_client.js';

const $ = id => document.getElementById(id);
const client = new TavusVideoClient({ daily: window.Daily, video: $('face') });
let configured = false;
let lastCaption = null;
let captionTimer;
const phases = { listening: '在听你说', thinking: '正在回应…', speaking: 'Joi 正在说话',
  interrupt_requested: '已请求打断，等待 Joi 停下…' };

function render(state) {
  const connected = state.phase === 'connected';
  const active = connected || state.phase === 'connecting' || state.phase === 'ending';
  $('connect').hidden = active || state.phase === 'cleanup_pending';
  $('connect').disabled = !configured || client.connecting || client.ending;
  $('end').hidden = !active && state.phase !== 'cleanup_pending';
  $('end').disabled = client.ending;
  $('end').textContent = state.phase === 'cleanup_pending' ? '结束会话' : '挂断';
  $('mic').hidden = !connected;
  $('mic').textContent = state.muted ? '麦克风已静音' : '麦克风已开启';
  $('mic').setAttribute('aria-pressed', String(state.muted));
  $('interrupt').hidden = !connected;
  $('interrupt').disabled = !state.events.speaking.pal;
  $('interrupt').textContent = state.events.interrupt?.requested ? '再次打断' : '等一下';
  $('play').hidden = !state.needsPlay;
  $('welcome').hidden = state.videoReady;
  $('status').textContent = connected && state.videoReady
    ? (state.muted ? '麦克风已静音 · ' : '') + (phases[state.events.phase] || '已接通') : state.message;
  if (!active) { clearTimeout(captionTimer); lastCaption = null; $('caption').textContent = ''; }
  else if (state.events.caption && state.events.caption !== lastCaption) {
    lastCaption = state.events.caption;
    const { role, text } = lastCaption;
    $('caption').textContent = `${role === 'user' ? '你：' : ''}${text}`;
    clearTimeout(captionTimer);
    captionTimer = setTimeout(() => { $('caption').textContent = ''; }, 12000);
  }
  const lag = state.events.latency?.providerTurnMs;
  $('measure').textContent = `视频轨：${state.videoReady ? '已收到' : '未收到'} · 音频轨：${state.audioReady ? '已收到' : '未收到'}`
    + (Number.isFinite(lag) ? ` · 服务端轮次间隔 ${(lag / 1000).toFixed(2)} 秒` : '')
    + '。轨道或服务端事件不代表已验证口型同步；请用实际交谈确认。';
}

client.addEventListener('state', e => render(e.detail));
$('connect').addEventListener('click', () => client.connect());
$('end').addEventListener('click', () => client.disconnect());
$('mic').addEventListener('click', () => client.toggleMic());
$('interrupt').addEventListener('click', () => client.interrupt());
$('play').addEventListener('click', () => client.play());
window.addEventListener('pagehide', () => client.unload());

try {
  if (!window.Daily || !navigator.mediaDevices?.getUserMedia) throw new Error('视频组件不可用，请使用支持麦克风的浏览器打开');
  const status = await client.api('/api/joi/session');
  configured = status.configured;
  client.update({ message: configured ? '准备好了。接通后可以直接说话。' : '真人视频尚未配置，请检查本地服务。' });
} catch (error) {
  client.update({ message: error.message || '无法检查视频服务，请刷新重试' });
}
render(client.state);
