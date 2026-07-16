// Web perception adapter: OPT-IN getUserMedia -> wire Events to the Runtime
// Server's /control endpoint. Nothing starts without an explicit user click,
// and stop() fully releases the devices. Frames/audio never leave the browser:
// only structured events (levels, presence) go on the wire in this v0.
//
// Usage:
//   import { WebPerception } from './perception_webcam.js';
//   const wp = new WebPerception({ serverUrl: 'ws://127.0.0.1:8765', agentId: 'kai' });
//   startButton.onclick = () => wp.start();   // browser permission prompt here
//   stopButton.onclick = () => wp.stop();

export class WebPerception {
  constructor({
    serverUrl,
    agentId = 'kai',
    speechLevel = 0.06,
    connectTimeoutMs = 5000,
    getUserMedia = (constraints) => globalThis.navigator.mediaDevices.getUserMedia(constraints),
    WebSocketClass = globalThis.WebSocket,
    AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext,
    setTimer = globalThis.setTimeout.bind(globalThis),
    clearTimer = globalThis.clearTimeout.bind(globalThis),
  }) {
    this.serverUrl = serverUrl;
    this.agentId = agentId;
    this.speechLevel = speechLevel;
    this.connectTimeoutMs = connectTimeoutMs;
    this.getUserMedia = getUserMedia;
    this.WebSocketClass = WebSocketClass;
    this.AudioContextClass = AudioContextClass;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.socket = null;
    this.stream = null;
    this.audioContext = null;
    this.source = null;
    this.analyser = null;
    this.running = false;
    this._speaking = false;
    this._tickTimer = null;
    this._starting = null;
    this._generation = 0;
  }

  async start() {
    if (this.running) return;
    if (this._starting) return this._starting;

    const generation = ++this._generation;
    this._starting = this._start(generation);
    try {
      await this._starting;
    } finally {
      this._starting = null;
    }
  }

  async _start(generation) {
    let acquiredStream = null;
    try {
      if (!this.serverUrl) throw new Error('A perception serverUrl is required');
      if (!this.WebSocketClass) throw new Error('WebSocket is unavailable in this browser');
      if (!this.AudioContextClass) throw new Error('Web Audio is unavailable in this browser');

      // Explicit permission prompt — _start is reached only from start(), which
      // the page wires to a user click. There is deliberately no auto-start.
      acquiredStream = await this.getUserMedia({ audio: true, video: false });
      if (generation !== this._generation) {
        this._stopTracks(acquiredStream);
        return;
      }
      this.stream = acquiredStream;

      this.socket = new this.WebSocketClass(
        `${this.serverUrl.replace(/\/$/, '')}/control`,
      );
      await this._waitForSocketOpen(this.socket);
      if (generation !== this._generation) return;

      this.audioContext = new this.AudioContextClass();
      this.source = this.audioContext.createMediaStreamSource(this.stream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 512;
      this.source.connect(this.analyser);
      const buffer = new Float32Array(this.analyser.fftSize);

      this.running = true;
      this._emit({ kind: 'user_presence', text: 'web user enabled microphone perception' });

      const tick = () => {
        if (!this.running || generation !== this._generation) return;
        this.analyser.getFloatTimeDomainData(buffer);
        let rms = 0;
        for (const value of buffer) rms += value * value;
        rms = Math.sqrt(rms / buffer.length);
        const speaking = rms > this.speechLevel;
        if (speaking && !this._speaking) {
          // Level-based voice activity only; raw samples are never serialized.
          this._emit({
            kind: 'sound_event',
            text: 'speech_activity',
            payload: { rms: Number(rms.toFixed(4)) },
          });
        }
        this._speaking = speaking;
        this._tickTimer = this.setTimer(tick, 150);
      };
      tick();
    } catch (error) {
      await this._cleanup();
      throw error instanceof Error ? error : new Error('Unable to start web perception');
    }
  }

  _waitForSocketOpen(socket) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (callback, value) => {
        if (settled) return;
        settled = true;
        this.clearTimer(timeout);
        socket.onopen = null;
        socket.onerror = null;
        socket.onclose = null;
        callback(value);
      };
      const timeout = this.setTimer(() => {
        finish(reject, new Error('Perception WebSocket connection timed out'));
      }, this.connectTimeoutMs);
      socket.onopen = () => finish(resolve);
      socket.onerror = () => finish(reject, new Error('Perception WebSocket connection failed'));
      socket.onclose = () => finish(reject, new Error('Perception WebSocket closed before opening'));
    });
  }

  _emit({ kind, text, payload = {} }) {
    if (this.socket?.readyState !== this.WebSocketClass.OPEN) return;
    // Only scalar structured metadata is allowed on the wire. This excludes
    // Blob, ArrayBuffer, MediaStream and nested media/data-URI containers.
    const structuredPayload = Object.fromEntries(
      Object.entries(payload).filter(([, value]) => (
        typeof value === 'number' || typeof value === 'boolean'
        || (typeof value === 'string' && value.length <= 256 && !value.startsWith('data:'))
      )),
    );
    this.socket.send(JSON.stringify({
      type: 'event', kind, source: 'web-mic', text,
      target_agent: this.agentId,
      payload: {
        perception: true,
        modality: 'audio',
        confidence: 0.9,
        ...structuredPayload,
      },
    }));
  }

  async stop() {
    ++this._generation;
    await this._cleanup();
  }

  async _cleanup() {
    this.running = false;
    this._speaking = false;
    if (this._tickTimer !== null) this.clearTimer(this._tickTimer);
    this._tickTimer = null;

    const stream = this.stream;
    const source = this.source;
    const analyser = this.analyser;
    const audioContext = this.audioContext;
    const socket = this.socket;
    this.stream = null;
    this.source = null;
    this.analyser = null;
    this.audioContext = null;
    this.socket = null;

    this._stopTracks(stream);
    try { source?.disconnect(); } catch { /* already disconnected */ }
    try { analyser?.disconnect(); } catch { /* already disconnected */ }
    if (socket) {
      socket.onopen = null;
      socket.onerror = null;
      socket.onclose = null;
      try { socket.close(); } catch { /* already closed */ }
    }
    if (audioContext) {
      try { await audioContext.close(); } catch { /* already closed */ }
    }
  }

  _stopTracks(stream) {
    stream?.getTracks().forEach((track) => {
      try { track.stop(); } catch { /* already stopped */ }
    });
  }
}
