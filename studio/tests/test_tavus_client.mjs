import test from 'node:test';
import assert from 'node:assert/strict';
import { TavusVideoClient } from '../web/lib/tavus_client.js';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function harness() {
  const requests = [], handlers = {};
  const track = { kind: 'audio', enabled: true, stopped: false, stop() { this.stopped = true; } };
  const input = { getTracks: () => [track], getAudioTracks: () => [track] };
  const call = { on(name, handler) { handlers[name] = handler; },
    async join(args) { this.joined = args; }, async leave() { this.left = true; },
    async destroy() { this.destroyed = true; }, participants() { return this.roster || {}; },
    setLocalAudio(value) { this.mic = value; }, sendAppMessage(value) { this.sent = value; } };
  const video = { srcObject: null, async play() {}, pause() { this.paused = true; } };
  const session = { conversation_id: 'owned-room', conversation_url: 'https://tavus.daily.co/test', meeting_token: 'ephemeral' };
  const h = { requests, handlers, track, input, call, video, session };
  const client = new TavusVideoClient({
    daily: { createCallObject(options) { h.options = options; return call; } }, video,
    makeStream: tracks => ({ getTracks: () => tracks }),
    mediaDevices: { async getUserMedia(constraints) { h.constraints = constraints; return h.media ? h.media() : input; } },
    fetcher: async (path, options) => {
      requests.push({ path, options });
      if (h.fetch) return h.fetch(path, options);
      return { ok: true, json: async () => ({ ok: true, session }) };
    },
  });
  return { ...h, client, mutable: h };
}

test('permission rejection never creates a billable room; camera is not requested', async () => {
  const h = harness();
  h.mutable.media = () => { throw Object.assign(new Error(), { name: 'NotAllowedError' }); };
  await h.client.connect();
  assert.equal(h.requests.length, 0);
  assert.equal(h.mutable.constraints.video, false);
  assert.equal(h.client.state.phase, 'idle');
  assert.match(h.client.state.message, /许可/);
});

test('hangup during room creation reclaims the eventual exact room and stops the mic', async () => {
  const h = harness(), response = deferred();
  h.mutable.fetch = async path => path.endsWith('/end')
    ? { ok: true, json: async () => ({ ok: true }) } : response.promise;
  const connecting = h.client.connect();
  await new Promise(resolve => setImmediate(resolve));
  await h.client.disconnect();
  response.resolve({ ok: true, json: async () => ({ ok: true, session: h.session }) });
  await connecting;
  assert.equal(h.track.stopped, true);
  assert.equal(h.call.joined, undefined);
  assert.equal(h.client.session, null);
  assert.deepEqual(JSON.parse(h.requests.at(-1).options.body), {
    conversation_id: 'owned-room', client_id: h.client.clientId,
  });
});

test('late permission resolution after hangup stops its track without creating a room', async () => {
  const h = harness(), permission = deferred();
  h.mutable.media = () => permission.promise;
  const connecting = h.client.connect();
  await h.client.disconnect();
  permission.resolve(h.input);
  await connecting;
  assert.equal(h.track.stopped, true);
  assert.equal(h.requests.length, 0);
});

test('one media element binds audio/video and removes replaced or stopped tracks', async () => {
  const h = harness();
  await h.client.connect();
  assert.equal(h.mutable.options.videoSource, false);
  assert.equal(h.mutable.options.audioSource, h.track);
  const audio = { kind: 'audio' }, video = { kind: 'video' }, newVideo = { kind: 'video' };
  h.call.roster = { local: { local: true }, remote: { local: false, tracks: {
    audio: { state: 'playable', persistentTrack: audio }, video: { state: 'playable', persistentTrack: video },
  } } };
  h.handlers['participant-updated']();
  assert.deepEqual(new Set(h.video.srcObject.getTracks()), new Set([audio, video]));
  h.call.roster.remote.tracks.video.persistentTrack = newVideo;
  h.call.roster.remote.tracks.audio.state = 'off';
  h.handlers['track-stopped']();
  assert.deepEqual(h.video.srcObject.getTracks(), [newVideo]);
  await h.client.disconnect();
  h.handlers['participant-updated']();
  assert.equal(h.video.srcObject, null);
});

test('provider interrupt is sent; sending it never claims speech has stopped', async () => {
  const h = harness();
  await h.client.connect();
  h.client.interrupt();
  assert.equal(h.call.sent, undefined);
  h.handlers['app-message']({ data: { event_type: 'conversation.started_speaking',
    conversation_id: 'owned-room', properties: { role: 'pal' } } });
  h.client.interrupt();
  assert.equal(h.call.sent.event_type, 'conversation.interrupt');
  assert.equal(h.call.sent.conversation_id, 'owned-room');
  assert.equal(h.client.state.events.interrupt.requested, true);
  assert.equal(h.client.state.events.interrupt.confirmed, false);
  await h.client.disconnect();
});

test('SDK leave failure still ends room; failed cloud cleanup retains a retryable session', async () => {
  const h = harness();
  await h.client.connect();
  h.call.leave = async () => { throw new Error('transport gone'); };
  h.mutable.fetch = async () => ({ ok: false, json: async () => ({ ok: false, error: 'offline' }) });
  await h.client.disconnect();
  assert.equal(h.call.destroyed, true);
  assert.equal(h.client.state.phase, 'cleanup_pending');
  assert.equal(h.client.session.conversation_id, 'owned-room');
  const count = h.requests.length;
  await h.client.connect();
  assert.equal(h.requests.length, count);
  h.mutable.fetch = null;
  await h.client.disconnect();
  assert.equal(h.client.state.phase, 'idle');
  assert.equal(h.client.session, null);
});

test('late playback rejection cannot revive old controls after hangup', async () => {
  const h = harness(), playback = deferred();
  await h.client.connect();
  h.video.play = () => playback.promise;
  const playing = h.client.play();
  await h.client.disconnect();
  playback.reject(new Error('autoplay'));
  await playing;
  assert.equal(h.client.state.needsPlay, false);
});

test('pagehide uses keepalive cleanup and restores an idle page, never a stopped live mic', async () => {
  const h = harness();
  await h.client.connect();
  await h.client.unload();
  assert.equal(h.client.call, null);
  assert.equal(h.client.session, null);
  assert.equal(h.client.state.phase, 'idle');
  assert.equal(h.track.stopped, true);
  assert.equal(h.requests.at(-1).options.keepalive, true);
});

test('room binding rejects foreign messages and concurrent connect obtains one microphone', async () => {
  const h = harness();
  await Promise.all([h.client.connect(), h.client.connect()]);
  assert.equal(h.requests.length, 1);
  h.handlers['app-message']({ data: { event_type: 'conversation.utterance',
    conversation_id: 'foreign', properties: { role: 'pal', speech: 'wrong room' } } });
  assert.equal(h.client.events.caption, null);
  assert.equal(h.client.events.conversationId, 'owned-room');
  await h.client.disconnect();
});
