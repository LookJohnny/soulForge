import test from 'node:test';
import assert from 'node:assert/strict';
import { SelfhostVideoClient } from '../web/lib/selfhost_client.js';

const CLIENT = '00000000-0000-4000-8000-000000000001';
const SESSION = '00000000-0000-4000-8000-000000000002';
const response = data => ({ ok: true, json: async () => data });
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
class Track extends EventTarget {
  constructor(kind) { super(); this.kind = kind; this.enabled = true; this.stopped = false; }
  stop() { this.stopped = true; this.dispatchEvent(new Event('ended')); }
}
class Peer extends EventTarget {
  constructor() { super(); this.iceGatheringState = 'complete'; this.connectionState = 'new'; this.channel = new EventTarget(); }
  addTrack(track) { this.input = track; }
  addTransceiver(kind, options) { this.transceiver = { kind, options }; }
  createDataChannel(label, options) { this.channelSettings = { label, options }; return this.channel; }
  async createOffer() { return { type: 'offer', sdp: 'v=0\r\nfake-offer' }; }
  async setLocalDescription(value) { this.localDescription = value; }
  async setRemoteDescription(value) { this.answer = value; if (!this.holdConnection) this.change('connected'); }
  change(value) { this.connectionState = value; this.dispatchEvent(new Event('connectionstatechange')); }
  close() { this.change('closed'); }
  track(track) { this.dispatchEvent(Object.assign(new Event('track'), { track })); }
  send(value) { this.channel.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(value) })); }
}
function harness(options = {}) {
  const track = new Track('audio'), requests = [], peers = [];
  const input = { getTracks: () => [track], getAudioTracks: () => [track] };
  const video = { srcObject: null, played: 0, paused: true,
    async play() { this.played++; this.paused = false; }, pause() { this.paused = true; } };
  const h = { track, input, video, requests, peers, mediaCount: 0 };
  const client = new SelfhostVideoClient({ video, clientId: CLIENT,
    makeStream: tracks => ({ getTracks: () => tracks }),
    createPeer: () => { const peer = new Peer(); peers.push(peer); h.peerSetup?.(peer); return peer; },
    mediaDevices: { async getUserMedia(constraints) {
      h.mediaCount++; h.constraints = constraints; return h.media ? h.media() : input;
    } },
    fetcher: async (path, args) => {
      requests.push({ path, args });
      if (h.fetch) return h.fetch(path, args);
      if (path.endsWith('/health')) return response({ ready: true });
      if (path.endsWith('/sessions')) return response({ session_id: SESSION, type: 'answer', sdp: 'v=0\r\nfake-answer' });
      if (path.endsWith('/interrupt')) return response({ ok: true, epoch: Math.max(0, h.client.remoteEpoch) + 1 });
      return response({ ok: true });
    }, ...options });
  client.update({ ready: true });
  h.client = client;
  h.event = event => peers.at(-1).send({ session_id: SESSION, epoch: 0, ...event });
  return h;
}

test('health requires explicit readiness and never opens microphone or room', async () => {
  const h = harness();
  h.fetch = async () => response({ status: 'ok', configured: true });
  assert.equal(await h.client.checkHealth(), false);
  await h.client.connect();
  assert.equal(h.mediaCount, 0);
  assert.match(h.client.state.message, /GPU 未配置/);
  assert.deepEqual(h.requests.map(r => r.path), ['/api/selfhost/health']);
});

test('permission refusal creates no remote session and never asks for camera', async () => {
  const h = harness();
  h.media = () => { throw Object.assign(new Error('sensitive browser error'), { name: 'NotAllowedError' }); };
  await h.client.connect();
  assert.equal(h.requests.length, 0);
  assert.equal(h.constraints.video, false);
  assert.equal(h.client.state.phase, 'idle');
  assert.match(h.client.state.message, /许可/);
});

test('concurrent connect uses one microphone, peer and ordered event channel', async () => {
  const h = harness(), permission = deferred();
  h.media = () => permission.promise;
  const first = h.client.connect();
  await h.client.connect();
  permission.resolve(h.input); await first;
  assert.equal(h.mediaCount, 1);
  assert.equal(h.peers.length, 1);
  assert.deepEqual(h.peers[0].channelSettings, { label: 'events', options: { ordered: true } });
  assert.deepEqual(h.peers[0].transceiver, { kind: 'video', options: { direction: 'recvonly' } });
  assert.equal(h.requests.length, 1);
  await h.client.disconnect();
});

test('hangup while permission is pending stops late tracks without making an offer', async () => {
  const h = harness(), permission = deferred(); h.media = () => permission.promise;
  const connecting = h.client.connect();
  await h.client.disconnect(); permission.resolve(h.input); await connecting;
  assert.equal(h.track.stopped, true);
  assert.equal(h.requests.length, 0);
  assert.equal(h.peers.length, 0);
});

test('hangup during create closes the eventual exact session without joining', async () => {
  const h = harness(), creation = deferred();
  h.fetch = async path => path.endsWith('/sessions') ? creation.promise : response({ ok: true });
  const connecting = h.client.connect(); await tick();
  await h.client.disconnect(); await h.client.connect();
  creation.resolve(response({ session_id: SESSION, type: 'answer', sdp: 'v=0' })); await connecting;
  assert.equal(h.peers[0].answer, undefined);
  assert.equal(h.track.stopped, true);
  assert.equal(h.client.sessionId, null);
  assert.equal(h.requests.at(-1).path, `/api/selfhost/sessions/${SESSION}/close`);
  assert.deepEqual(JSON.parse(h.requests.at(-1).args.body), { client_id: CLIENT });
  assert.equal(h.mediaCount, 1);
});

test('lost create response is reclaimed by client ownership even without a session ID', async () => {
  const h = harness();
  h.fetch = async path => {
    if (path.endsWith('/sessions')) throw new Error('response lost after remote creation');
    return response({ ok: true });
  };
  await h.client.connect();
  assert.equal(h.requests.at(-1).path, '/api/selfhost/sessions/close-owned');
  assert.deepEqual(JSON.parse(h.requests.at(-1).args.body), { client_id: CLIENT });
  assert.equal(h.client.creationPending, false);
  assert.equal(h.client.state.phase, 'idle');
  assert.equal(h.track.stopped, true);
});

test('failed unknown-session cleanup retains ownership, blocks connect and is retried on unload', async () => {
  const h = harness(); h.fetch = async () => { throw new Error('offline'); };
  await h.client.connect(); await h.client.connect();
  assert.equal(h.mediaCount, 1); assert.equal(h.client.creationPending, true);
  assert.equal(h.client.state.phase, 'cleanup_pending');
  h.client.unload(); await tick();
  assert.equal(h.requests.at(-1).path, '/api/selfhost/sessions/close-owned');
  assert.equal(h.requests.at(-1).args.keepalive, true);
  h.fetch = async () => response({ ok: true }); await h.client.disconnect();
  assert.equal(h.client.creationPending, false);
});

test('audio alone stays silent; one media element binds both tracks and excludes replacements', async () => {
  const h = harness(); await h.client.connect();
  const audio = new Track('audio'), video = new Track('video'), replacement = new Track('video');
  h.peers[0].track(audio);
  assert.equal(h.video.srcObject, null); assert.equal(h.video.played, 0);
  h.peers[0].track(video);
  assert.deepEqual(h.video.srcObject.getTracks(), [audio, video]);
  h.peers[0].track(replacement); video.stop();
  assert.deepEqual(h.video.srcObject.getTracks(), [audio, replacement]);
  replacement.stop(); assert.equal(h.video.srcObject, null);
  await h.client.disconnect();
});

test('old peers and old play promises cannot alter a replacement connection', async () => {
  const h = harness(); await h.client.connect();
  const old = h.peers[0], play = deferred(); h.video.play = () => play.promise;
  old.track(new Track('video')); await h.client.disconnect();
  h.video.play = async () => {}; await h.client.connect();
  h.peers[1].track(new Track('video')); const stream = h.video.srcObject;
  old.track(new Track('audio')); old.send({ type: 'error', session_id: SESSION, epoch: 50 });
  play.reject(new Error('late autoplay denial')); await tick();
  assert.equal(h.video.srcObject, stream);
  assert.equal(h.client.state.audioReady, false);
  assert.equal(h.client.state.needsPlay, false);
  assert.equal(h.client.state.notice, '');
  await h.client.disconnect();
});

test('interrupt immediately pauses A/V and ignores stale acknowledgements and captions', async () => {
  const h = harness(); await h.client.connect(); h.peers[0].track(new Track('video'));
  h.event({ type: 'state', phase: 'speaking', turn_id: 'turn1', epoch: 3 });
  const pending = h.client.interrupt();
  assert.equal(h.video.paused, true); assert.equal(h.video.srcObject, null);
  h.event({ type: 'caption', role: 'assistant', text: 'obsolete', epoch: 3 });
  h.event({ type: 'cancelled', turn_id: 'old', epoch: 2 });
  h.event({ type: 'cancelled', turn_id: 'turn1', epoch: 3 });
  h.event({ type: 'cancelled', turn_id: 'turn1', epoch: 4, session_id: CLIENT });
  assert.equal(h.video.srcObject, null); assert.equal(h.client.state.caption, null);
  h.event({ type: 'cancelled', turn_id: 'turn1', epoch: 4 }); await pending;
  assert.equal(h.client.state.interruptPending, false);
  assert.notEqual(h.video.srcObject, null);
  h.event({ type: 'caption', role: 'assistant', text: 'old', epoch: 3 });
  assert.equal(h.client.state.caption, null);
  assert.equal(h.requests.at(-1).path, `/api/selfhost/sessions/${SESSION}/interrupt`);
  await h.client.disconnect();
});

test('idle interrupt can recover on a newer epoch without an invented turn identity', async () => {
  const h = harness(); await h.client.connect(); h.peers[0].track(new Track('video'));
  h.event({ type: 'state', phase: 'listening', epoch: 0 });
  await h.client.interrupt(); h.event({ type: 'cancelled', turn_id: null, epoch: 1 });
  assert.equal(h.client.state.interruptPending, false);
  await h.client.disconnect();
});

test('late typed-turn response cannot replace state after interrupt', async () => {
  const h = harness(), turn = deferred(); await h.client.connect();
  h.fetch = async path => path.endsWith('/turn') ? turn.promise : response({ ok: true, epoch: 2 });
  const sending = h.client.sendText('你好'); await tick();
  h.event({ type: 'state', phase: 'thinking', turn_id: 'new-turn', epoch: 1 });
  await h.client.interrupt(); h.event({ type: 'cancelled', turn_id: 'new-turn', epoch: 2 });
  turn.resolve(response({ ok: true, turn_id: 'old-turn', epoch: 1 })); await sending;
  assert.equal(h.client.state.turnId, 'new-turn');
  const sent = h.requests.find(r => r.path.endsWith('/turn'));
  assert.deepEqual(JSON.parse(sent.args.body), { text: '你好', client_id: CLIENT });
  await h.client.disconnect();
});

test('failed close keeps ownership for retry and blocks new sessions', async () => {
  const h = harness(); await h.client.connect();
  h.fetch = async () => { throw new Error('secret URL'); };
  await h.client.disconnect(); await h.client.connect();
  assert.equal(h.client.state.phase, 'cleanup_pending'); assert.equal(h.client.sessionId, SESSION);
  assert.equal(h.mediaCount, 1); assert.equal(h.track.stopped, true);
  h.fetch = async () => response({ ok: true }); await h.client.disconnect();
  assert.equal(h.client.sessionId, null); assert.equal(h.client.state.phase, 'idle');
  assert.doesNotMatch(JSON.stringify(h.client.state), /secret/);
});

test('a delayed automatic cancellation cannot acknowledge a later user interrupt', async () => {
  const h = harness(), reply = deferred(); await h.client.connect(); h.peers[0].track(new Track('video'));
  h.event({ type: 'state', phase: 'speaking', turn_id: 'old', epoch: 3 });
  h.fetch = async path => path.endsWith('/interrupt') ? reply.promise : response({ ok: true });
  const pending = h.client.interrupt();
  // A preceding typed turn automatically cancelled epoch 3. Its event arrives
  // after the user has pressed interrupt; this must never unpause playback.
  h.event({ type: 'cancelled', epoch: 4 });
  assert.equal(h.video.srcObject, null);
  reply.resolve(response({ ok: true, epoch: 6 })); await pending;
  assert.equal(h.video.srcObject, null); assert.equal(h.client.state.interruptPending, true);
  h.event({ type: 'cancelled', epoch: 6 });
  assert.notEqual(h.video.srcObject, null); assert.equal(h.client.state.interruptPending, false);
  await h.client.disconnect();
});

test('event-before-HTTP interruption waits for exact acknowledgement without losing the event', async () => {
  const h = harness(), reply = deferred(); await h.client.connect(); h.peers[0].track(new Track('video'));
  h.event({ type: 'state', phase: 'speaking', epoch: 2 });
  h.fetch = async path => path.endsWith('/interrupt') ? reply.promise : response({ ok: true });
  const pending = h.client.interrupt();
  h.event({ type: 'cancelled', epoch: 3 });
  assert.equal(h.video.srcObject, null);
  reply.resolve(response({ ok: true, epoch: 3 })); await pending;
  assert.notEqual(h.video.srcObject, null); assert.equal(h.client.state.interruptPending, false);
  await h.client.disconnect();
});

test('network loss and failed connection setup recycle the session after bounded grace', async () => {
  for (const connectFailure of [false, true]) {
    const h = harness({ disconnectTimeout: 5, connectTimeout: 5 });
    if (connectFailure) h.peerSetup = peer => { peer.holdConnection = true; };
    await h.client.connect();
    if (!connectFailure) h.peers[0].change('disconnected');
    await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(h.client.state.phase, 'idle'); assert.equal(h.client.sessionId, null);
    assert.equal(h.track.stopped, true);
    assert.equal(h.requests.at(-1).path, `/api/selfhost/sessions/${SESSION}/close`);
  }
});

test('page exit stops the mic, detaches media and requests exact-session keepalive cleanup', async () => {
  const h = harness(); await h.client.connect(); h.peers[0].track(new Track('video'));
  h.client.unload(); await tick();
  assert.equal(h.track.stopped, true); assert.equal(h.video.srcObject, null);
  assert.equal(h.client.state.phase, 'cleanup_pending');
  assert.equal(h.client.sessionId, SESSION);
  assert.equal(h.requests.at(-1).args.keepalive, true);
  assert.deepEqual(JSON.parse(h.requests.at(-1).args.body), { client_id: CLIENT });
  await h.client.disconnect();
});

test('server errors and metrics cannot disclose credentials or internal URLs', async () => {
  const h = harness(); await h.client.connect();
  h.event({ type: 'error', message: 'secret at http://gpu/token' });
  h.event({ type: 'metrics', decision_ms: 12.5, video_fps: 20, first_audio_ready_ms: 200,
    browser_playback_verified: false, first_audio_ms: 15, token: 'secret', url: 'http://gpu' });
  assert.deepEqual(h.client.state.metrics, { decision_ms: 12.5, video_fps: 20, first_audio_ready_ms: 200, browser_playback_verified: false });
  assert.doesNotMatch(JSON.stringify(h.client.state), /secret|http:\/\//);
  h.client.toggleMic(); assert.equal(h.track.enabled, false);
  h.client.toggleMic(); assert.equal(h.track.enabled, true);
  await h.client.disconnect();
});

test('error remains visible across listening reset and clears when a new turn begins', async () => {
  const h = harness(); await h.client.connect();
  h.event({ type: 'error', message: 'provider secret' });
  h.event({ type: 'state', phase: 'listening' });
  assert.match(h.client.state.notice, /失败/);
  h.event({ type: 'state', phase: 'transcribing', epoch: 1 });
  assert.equal(h.client.state.notice, '');
  await h.client.disconnect();
});
