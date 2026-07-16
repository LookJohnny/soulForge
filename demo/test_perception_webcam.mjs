import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const sourceUrl = new URL('./vtuber_life_web/src/perception_webcam.js', import.meta.url);
const source = await readFile(sourceUrl, 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { WebPerception } = await import(moduleUrl);

function makeStream() {
  const track = {
    stopped: false,
    stop() { this.stopped = true; },
  };
  return {
    track,
    getTracks() { return [track]; },
  };
}

class FailingSocket {
  static OPEN = 1;
  static instances = [];

  constructor() {
    this.readyState = 0;
    this.closed = false;
    FailingSocket.instances.push(this);
    queueMicrotask(() => this.onerror?.(new Error('offline')));
  }

  close() {
    this.closed = true;
    this.readyState = 3;
  }
}

class UnusedAudioContext {}

{
  const stream = makeStream();
  const perception = new WebPerception({
    serverUrl: 'ws://127.0.0.1:1',
    getUserMedia: async () => stream,
    WebSocketClass: FailingSocket,
    AudioContextClass: UnusedAudioContext,
    connectTimeoutMs: 100,
  });

  await assert.rejects(perception.start(), /connection failed/);
  assert.equal(stream.track.stopped, true, 'connection failure must release microphone');
  assert.equal(FailingSocket.instances.at(-1).closed, true, 'failed socket must close');
  assert.equal(perception.running, false);
  assert.equal(perception.stream, null);
  assert.equal(perception.socket, null);
  assert.equal(perception.audioContext, null);
}

class OpenSocket {
  static OPEN = 1;
  static instances = [];

  constructor() {
    this.readyState = 0;
    this.closed = false;
    this.sent = [];
    OpenSocket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = OpenSocket.OPEN;
      this.onopen?.();
    });
  }

  send(frame) { this.sent.push(frame); }

  close() {
    this.closed = true;
    this.readyState = 3;
  }
}

class BrokenAudioContext {
  static instances = [];

  constructor() {
    this.closed = false;
    BrokenAudioContext.instances.push(this);
  }

  createMediaStreamSource() {
    return { connect() {}, disconnect() {} };
  }

  createAnalyser() {
    throw new Error('audio graph failed');
  }

  async close() { this.closed = true; }
}

{
  const stream = makeStream();
  const perception = new WebPerception({
    serverUrl: 'ws://127.0.0.1:8765',
    getUserMedia: async () => stream,
    WebSocketClass: OpenSocket,
    AudioContextClass: BrokenAudioContext,
  });

  await assert.rejects(perception.start(), /audio graph failed/);
  assert.equal(stream.track.stopped, true, 'audio setup failure must release microphone');
  assert.equal(OpenSocket.instances.at(-1).closed, true, 'audio setup failure must close socket');
  assert.equal(BrokenAudioContext.instances.at(-1).closed, true, 'audio setup failure must close context');
  assert.equal(perception.stream, null);
  assert.equal(perception.socket, null);
  assert.equal(perception.audioContext, null);
}

class WorkingAudioContext {
  static instances = [];

  constructor() {
    this.closed = false;
    this.source = { connect() {}, disconnect() {} };
    this.analyser = {
      fftSize: 0,
      disconnect() {},
      getFloatTimeDomainData(buffer) { buffer.fill(0); },
    };
    WorkingAudioContext.instances.push(this);
  }

  createMediaStreamSource() { return this.source; }
  createAnalyser() { return this.analyser; }
  async close() { this.closed = true; }
}

{
  const stream = makeStream();
  const perception = new WebPerception({
    serverUrl: 'ws://127.0.0.1:8765',
    getUserMedia: async () => stream,
    WebSocketClass: OpenSocket,
    AudioContextClass: WorkingAudioContext,
  });

  await perception.start();
  const socket = OpenSocket.instances.at(-1);
  assert.equal(perception.running, true);
  assert.equal(socket.sent.length, 1, 'start emits structured presence once');
  const frame = JSON.parse(socket.sent[0]);
  assert.deepEqual(Object.keys(frame.payload).sort(), ['confidence', 'modality', 'perception']);
  assert.equal(JSON.stringify(frame).includes('data:'), false, 'wire frame contains no raw media');

  perception._emit({
    kind: 'sound_event',
    text: 'speech_activity',
    payload: { rms: 0.1, raw: new Uint8Array([1, 2]), inline: 'data:audio/wav;base64,AQ==' },
  });
  const activityFrame = JSON.parse(socket.sent[1]);
  assert.equal(activityFrame.payload.rms, 0.1);
  assert.equal('raw' in activityFrame.payload, false);
  assert.equal('inline' in activityFrame.payload, false);

  await perception.stop();
  assert.equal(stream.track.stopped, true);
  assert.equal(socket.closed, true);
  assert.equal(WorkingAudioContext.instances.at(-1).closed, true);
  assert.equal(perception.running, false);
}

console.log('web perception cleanup: 3 scenarios passed');
