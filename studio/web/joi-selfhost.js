import { SelfhostVideoClient } from './lib/selfhost_client.js';

const $ = id => document.getElementById(id);
const client = new SelfhostVideoClient({ video: $('face') });
let sending = false;
const phases = { listening: '在听你说', transcribing: '正在辨认你说的话…', thinking: '正在回应…', generating: '正在生成真人画面…', speaking: 'Joi 正在说话' };
const metricLabels = { first_audio_ready_ms: '音频就绪 ms', first_video_ready_ms: '视频就绪 ms',
  sender_drained_ms: '发送队列清空 ms', decision_ms: '认知 ms', video_fps: '生成 FPS', queue_ms: '排队 ms' };

function render(state) {
  const connected = state.phase === 'connected';
  const active = connected || ['connecting', 'ending'].includes(state.phase);
  $('connect').hidden = active || state.phase === 'cleanup_pending';
  $('connect').disabled = !state.ready || client.connecting || client.ending;
  $('refresh').hidden = active;
  $('end').hidden = !active && state.phase !== 'cleanup_pending';
  $('end').disabled = client.ending;
  $('end').textContent = state.phase === 'cleanup_pending' ? '重试结束会话' : '挂断';
  $('mic').hidden = !connected;
  $('mic').textContent = state.muted ? '麦克风已静音' : '麦克风已开启';
  $('mic').setAttribute('aria-pressed', String(state.muted));
  $('interrupt').hidden = !connected;
  $('interrupt').disabled = state.interruptPending;
  $('play').hidden = !state.needsPlay || state.interruptPending;
  $('welcome').hidden = state.videoReady && !state.interruptPending;
  $('text-form').hidden = !connected;
  $('text').disabled = state.interruptPending;
  $('send').disabled = sending || state.interruptPending;
  $('status').textContent = state.interruptPending || !connected ? state.message
    : (state.notice || phases[state.turnPhase] || state.message) + (state.muted ? ' · 麦克风静音' : '');
  $('caption').textContent = state.caption ? `${state.caption.role === 'user' ? '你：' : ''}${state.caption.text}` : '';
  const metrics = Object.entries(state.metrics).filter(([key, value]) => key in metricLabels && typeof value === 'number')
    .map(([key, value]) => `${metricLabels[key]}: ${value.toFixed(1)}`).join(' · ');
  $('measure').textContent = `视频轨：${state.videoReady ? '已收到' : '未收到'} · 音频轨：${state.audioReady ? '已收到' : '未收到'}`
    + (metrics ? ` · 服务端观测 ${metrics}` : '') + '。服务端就绪与发送耗时不是浏览器实际播放延迟；口型同步与自然停嘴仍需实测。';
}

client.addEventListener('state', event => render(event.detail));
$('connect').addEventListener('click', () => client.connect());
$('refresh').addEventListener('click', () => client.checkHealth());
$('end').addEventListener('click', () => client.disconnect());
$('mic').addEventListener('click', () => client.toggleMic());
$('interrupt').addEventListener('click', () => client.interrupt());
$('play').addEventListener('click', () => client.play());
$('text-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (sending) return;
  const text = $('text').value;
  sending = true; render(client.state);
  try { if (await client.sendText(text) && $('text').value === text) $('text').value = ''; }
  finally { sending = false; render(client.state); }
});
window.addEventListener('pagehide', () => client.unload());
window.addEventListener('pageshow', async event => {
  if (!event.persisted) return;
  if (client.sessionId || client.creationPending) await client.disconnect('页面已恢复，请重新接通。');
  await client.checkHealth();
});

if (!window.RTCPeerConnection || !navigator.mediaDevices?.getUserMedia) {
  client.update({ ready: false, message: '当前浏览器不支持 WebRTC 麦克风，请使用现代浏览器在本机打开。' });
  $('refresh').disabled = true;
} else await client.checkHealth();
render(client.state);
