import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../web/lib/tavus_events.js', import.meta.url), 'utf8');
const { createTavusEventState: fresh, normalizeTavusEvent: normalize,
  reduceTavusEvent: reduce, requestTavusInterrupt: interrupt } = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const frame = (kind, role, extra = {}, properties = {}) => ({
  message_type: 'conversation', event_type: `conversation.${kind}`,
  conversation_id: 'call-a', turn_idx: 1, ...extra, properties: { role, ...properties },
});
const caption = (speech, extra = {}, properties = {}) => frame('utterance.streaming', 'pal',
  { inference_id: 'pal-one', ...extra }, { speech, content_index: 0, final: false, ...properties });

test('normalizes Daily wrappers, formal roles, and legacy event names', () => {
  const event = frame('started_speaking', 'replica', { seq: 0, timestamp: 100.2 });
  assert.equal(normalize({ action: 'app-message', data: event }).role, 'pal');
  assert.equal(normalize({ data: JSON.stringify(event) }).timestamp, 100.2);
  const legacy = normalize({ event_type: 'conversation.user.stopped_speaking' });
  assert.equal(legacy.role, 'user');
  assert.equal(legacy.kind, 'stopped_speaking');
  assert.equal(normalize(frame('started_speaking', 'pal')).kind, 'started_speaking');
});

test('invalid or unrelated events cannot pretend the provider is speaking', () => {
  const state = fresh();
  for (const event of [null, [], 2, {}, { data: 'not-json' },
    frame('started_speaking', 'admin'), frame('interrupt', 'pal'),
    { ...frame('started_speaking', 'pal'), message_type: 'control' },
    frame('utterance', 'pal', {}, { speech: { text: 'bad' } })]) {
    assert.equal(normalize(event), null);
    assert.equal(reduce(state, event), state);
  }
});

test('duplicate PAL / replica events, including legacy names, are idempotent', () => {
  const original = frame('started_speaking', 'pal', { inference_id: 'p1', timestamp: 100, seq: 10 });
  const state = reduce(fresh(), original);
  assert.equal(reduce(state, { ...original, seq: 11, properties: { role: 'replica' } }), state);
  assert.equal(reduce(state, { ...original, event_type: 'conversation.replica.started_speaking', properties: {} }), state);
  assert.equal(state.speaking.pal, true);
});

test('captions replace accumulated text and preserve literal text safely', () => {
  let state = reduce(fresh(), caption('你', { seq: 1 }));
  state = reduce(state, caption('你好 <img onerror=x>', { seq: 2 }, { content_index: 1 }));
  assert.equal(state.caption.text, '你好 <img onerror=x>');
  assert.equal(state.caption.source, 'provider-utterance-streaming');
  assert.equal(state.speaking.pal, false, 'captions are not playback confirmation');
  const duplicate = caption(state.caption.text, { seq: 3 }, { role: 'replica', content_index: 1 });
  assert.equal(reduce(state, duplicate), state);
  assert.ok(!source.includes('innerHTML'));
});

test('final spoken snapshot cannot be replaced by a legacy unspoken tail', () => {
  let state = reduce(fresh(), frame('utterance', 'pal', { inference_id: 'pal-one', seq: 1 }, { speech: '你好，完整的长回答' }));
  state = reduce(state, caption('你好', { seq: 2 }, { final: true, is_interrupted: true }));
  assert.equal(state.caption.text, '你好');
  assert.equal(state.caption.interrupted, true);
  assert.equal(state.interrupt.confirmed, false, 'a caption is not stopped-speaking confirmation');
  const lateFull = frame('utterance', 'replica', { inference_id: 'pal-one', seq: 3 }, { speech: '你好，完整的长回答' });
  assert.equal(reduce(state, lateFull), state);
  assert.equal(reduce(state, caption('你好，完整', { seq: 4 }, { content_index: 3 })), state);
});

test('content_index and sequence reject reordered snapshots without a turn index', () => {
  let state = reduce(fresh(), caption('一二三', { turn_idx: undefined, seq: 5 }, { content_index: 3 }));
  assert.equal(reduce(state, caption('一', { turn_idx: undefined, seq: 6 }, { content_index: 1 })), state);
  assert.equal(reduce(state, caption('一二', { turn_idx: undefined, seq: 4 }, { content_index: 4 })), state);
});

test('old turns and foreign conversations cannot overwrite a new turn', () => {
  let state = reduce(fresh('call-a'), caption('第二轮', { turn_idx: 2, seq: 10, inference_id: 'p2' }));
  assert.equal(reduce(state, caption('旧第一轮', { turn_idx: 1, seq: 11 })), state);
  assert.equal(reduce(state, frame('started_speaking', 'pal', { turn_idx: 1, seq: 12 })), state);
  assert.equal(reduce(state, caption('别的会话', { conversation_id: 'call-b', turn_idx: 3, seq: 30 })), state);
  assert.equal(state.caption.text, '第二轮');
});

test('interrupt request leaves observed speech active until the provider stops', () => {
  const playing = reduce(fresh(), frame('started_speaking', 'pal', { seq: 1, inference_id: 'p1' }));
  const requested = interrupt(playing);
  assert.equal(requested.phase, 'interrupt_requested');
  assert.equal(requested.speaking.pal, true);
  assert.deepEqual(requested.interrupt, { requested: true, confirmed: false, providerStopped: false });
  const stopped = reduce(requested, frame('stopped_speaking', 'replica', { seq: 2, inference_id: 'p1' }, { interrupted: true }));
  assert.equal(stopped.speaking.pal, false);
  assert.deepEqual(stopped.interrupt, { requested: false, confirmed: true, providerStopped: true });
  assert.equal(stopped.phase, 'listening');
  const naturalStop = reduce(requested, frame('stopped_speaking', 'pal', { seq: 2, inference_id: 'p1' }, { interrupted: false }));
  assert.equal(naturalStop.interrupt.confirmed, false, 'natural stop does not prove interrupt succeeded');
});

test('barge-in can stop the active older PAL span without erasing the new user turn', () => {
  let state = reduce(fresh(), frame('started_speaking', 'pal', { seq: 1, inference_id: 'p1' }));
  state = interrupt(state);
  state = reduce(state, frame('started_speaking', 'user', { turn_idx: 2, seq: 2, inference_id: 'u2' }));
  state = reduce(state, frame('utterance.streaming', 'user', { turn_idx: 2, seq: 3, inference_id: 'u2' }, { speech: '等等', content_index: 0 }));
  state = reduce(state, frame('stopped_speaking', 'pal', { turn_idx: 1, seq: 4, inference_id: 'p1' }, { interrupted: true }));
  assert.equal(state.speaking.pal, false);
  assert.equal(state.speaking.user, true);
  assert.equal(state.caption.text, '等等');
  assert.equal(state.turnIndex, 2);
  assert.equal(state.phase, 'listening');
});

test('late stopped-speaking event cannot stop a different active inference', () => {
  const state = reduce(fresh(), frame('started_speaking', 'pal', { seq: 5, inference_id: 'p2' }));
  assert.equal(reduce(state, frame('stopped_speaking', 'pal', { seq: 6, inference_id: 'p1' }, { interrupted: true })), state);
});

test('provider turn latency uses event seconds, never browser arrival or first audio', () => {
  let state = reduce(fresh(), frame('stopped_speaking', 'user', { timestamp: 100.125, seq: 1 }));
  assert.equal(state.phase, 'thinking');
  state = reduce(state, frame('started_speaking', 'pal', { timestamp: 101.875, seq: 2, inference_id: 'p1' }));
  assert.deepEqual(state.latency, { providerTurnMs: 1750, source: 'provider-speaking-events', isFirstAudio: false, turnIndex: 1 });
  const duplicate = frame('started_speaking', 'replica', { timestamp: 101.875, seq: 3, inference_id: 'p1' });
  assert.equal(reduce(state, duplicate), state);
});

test('out-of-order speaking events still use provider timestamps without a new pending reply', () => {
  let state = reduce(fresh(), frame('started_speaking', 'pal', { timestamp: 102, seq: 2, inference_id: 'p1' }));
  state = reduce(state, frame('stopped_speaking', 'user', { timestamp: 100, seq: 1 }));
  assert.equal(state.latency.providerTurnMs, 2000);
  assert.equal(state._pendingUserStop, null);
  state = reduce(state, frame('stopped_speaking', 'pal', { timestamp: 105, seq: 3, inference_id: 'p1' }));
  assert.equal(state.phase, 'listening');
});

test('missing, invalid, negative, or mismatched-turn times produce unknown latency', () => {
  for (const [stopTime, startTime, turn] of [[undefined, 101, 1], [100, undefined, 1],
    ['100', 101, 1], [100, Infinity, 1], [102, 101, 1], [100, 101, 2]]) {
    const state = reduce(fresh(), frame('stopped_speaking', 'user', { timestamp: stopTime, seq: 1 }));
    const next = reduce(state, frame('started_speaking', 'pal', { timestamp: startTime, turn_idx: turn, seq: 2 }));
    assert.equal(next.latency, null);
  }
});

test('channel clocks do not drop a speaking transition merely because a caption arrived first', () => {
  const state = reduce(fresh(), caption('你好', { timestamp: 101, seq: 4 }));
  const next = reduce(state, frame('started_speaking', 'pal', { timestamp: 100, seq: 3, inference_id: 'pal-one' }));
  assert.equal(next.speaking.pal, true);
  assert.equal(next.lastSequence, 4);
  assert.equal(next.caption.text, '你好');
});

test('events missing sequence metadata do not erase the existing sequence guard', () => {
  let state = reduce(fresh(), caption('第一段', { seq: 10 }, { content_index: 0 }));
  state = reduce(state, caption('第一段第二段', {}, { content_index: 1 }));
  assert.equal(reduce(state, caption('迟到的片段', { seq: 9 }, { content_index: 2 })), state);
});

test('reducers preserve their input and keep duplicate metadata bounded', () => {
  const state = fresh();
  const original = JSON.stringify(state);
  reduce(state, caption('hello', { seq: 1 }));
  interrupt(state);
  assert.equal(JSON.stringify(state), original);
  let many = state;
  for (let i = 0; i < 200; i++) many = reduce(many, caption(String(i), { seq: i, turn_idx: i, inference_id: `p${i}` }));
  assert.equal(many._seen.length, 128);
  assert.equal(Object.keys(many._captions).length, 1);
});
