/* GatewayClient —— 浏览器以 web_audio 设备身份接入 SoulForge gateway。

   与小智 ESP32 走同一条 /ws：文本或 Opus 麦克风上行，服务端 VAD 断句 →
   ASR → 记忆/PAD/LLM → TTS → 24kHz 60ms 裸 Opus 帧下行。

   线协议（packages/gateway/src/gateway/protocols/web_audio.py）：
   ↑ {"type":"web_hello","session_name"} / {"type":"text","content"} /
     {"type":"listen","state":"start|stop"} / {"type":"abort"} / 二进制 Opus 帧
   ↓ {"type":"web_hello",...}
     {"type":"text","content","state":"start|sentence|sentence_start|stop"}
     {"type":"control","payload":{"type":"emotion","pad":{p,a,d},...}}
     {"type":"control","payload":{"type":"tts","state":"stop"}}
     二进制 Opus 帧（24kHz, 60ms）

   下行音频：web_audio 会话默认每句一整段 MP3（decodeAudioData）；小智式裸 Opus 帧
   则用 WebCodecs（与采样率无关，统一按 48kHz 解）。按魔数自动分流。 */

export class GatewayClient extends EventTarget {
  constructor({ url, sessionName = 'vrm' } = {}) {
    super();
    this.url = url ?? `ws://${location.hostname}:8080/ws`;
    this.sessionName = sessionName;
    this.ws = null;
    this.deviceId = null;

    this.audioCtx = null;
    this.analyser = null;
    this.decoder = null;
    this.playHead = 0;
    this.sources = new Set();
    this.speaking = false;

    this.mic = null; // {stream, track, processor, encoder, reader}
  }

  // ── 连接 ─────────────────────────────────────────────
  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      ws.binaryType = 'arraybuffer';
      ws.onopen = () => ws.send(JSON.stringify({ type: 'web_hello', session_name: this.sessionName }));
      ws.onerror = (e) => { this._emit('error', e); reject(e); };
      ws.onclose = () => { this._emit('close'); this.ws = null; };
      ws.onmessage = (ev) => {
        if (ev.data instanceof ArrayBuffer) { this._onAudio(ev.data); return; }
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === 'web_hello') {
          this.deviceId = msg.device_id;
          this._emit('open', msg);
          resolve(msg);
          return;
        }
        this._onJson(msg);
      };
      this.ws = ws;
    });
  }

  close() { this.stopMic(); this._stopPlayback(); this.ws?.close(); }

  sendText(content) {
    this.ws?.send(JSON.stringify({ type: 'text', content }));
  }

  abort() {
    this.ws?.send(JSON.stringify({ type: 'abort' }));
    this._stopPlayback();
  }

  // ── 下行 ─────────────────────────────────────────────
  _onJson(msg) {
    if (msg.type === 'text') {
      const state = msg.state || '';
      if (state === 'start') this._setSpeaking(true);
      else if (state === 'sentence') this._emit('sentence', { text: msg.content });
      else if (state === 'stop') this._drainThenStop();
      else if (!state && msg.content) this._emit('sentence', { text: msg.content });
      return;
    }
    if (msg.type === 'control') {
      const p = msg.payload ?? {};
      if (p.type === 'emotion') this._emit('emotion', p);
      else if (p.type === 'tts' && p.state === 'stop') this._drainThenStop();
      else if (p.type === 'reaction') this._emit('reaction', p);
      // 通用分发：relationship / event / memory … 由页面按 `control:<type>` 订阅
      if (p.type) this._emit('control:' + p.type, p);
      this._emit('control', p);
    }
  }

  /** 发送任意 JSON 控制消息（event_choice / set_app_mode …）。 */
  send(obj) {
    if (this.ws?.readyState === 1) this.ws.send(JSON.stringify(obj));
  }

  async ensureAudio() {
    if (this.audioCtx) { if (this.audioCtx.state === 'suspended') await this.audioCtx.resume(); return; }
    this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.connect(this.audioCtx.destination);
    // 整段 MP3/WAV 不需要 WebCodecs；裸 Opus（小智同款分支）才需要
    this._makeDecoder();
  }

  /** 二进制帧分流：MP3/WAV 整段（web_audio 默认）走 decodeAudioData，裸 Opus 帧走 WebCodecs。 */
  _onAudio(buf) {
    if (!this.audioCtx) return;
    if (!this.speaking) this._setSpeaking(true);
    const u8 = new Uint8Array(buf, 0, Math.min(4, buf.byteLength));
    const isMp3 = (u8[0] === 0xff && (u8[1] & 0xe0) === 0xe0) || (u8[0] === 0x49 && u8[1] === 0x44 && u8[2] === 0x33); // frame sync / 'ID3'
    const isWav = u8[0] === 0x52 && u8[1] === 0x49 && u8[2] === 0x46 && u8[3] === 0x46; // 'RIFF'
    if (isMp3 || isWav) { this._decodeClip(buf); return; }
    if (!this.decoder || this.decoder.state !== 'configured') this._makeDecoder();
    if (!this.decoder) return;
    try {
      this.decoder.decode(new EncodedAudioChunk({ type: 'key', timestamp: this._ts, data: buf }));
      this._ts += 60000;
    } catch (e) { this._emit('error', e); this._makeDecoder(); }
  }

  _makeDecoder() {
    if (!('AudioDecoder' in window)) { this.decoder = null; return; }
    try { this.decoder?.close(); } catch { /* already closed */ }
    this.decoder = new AudioDecoder({
      output: (frame) => this._playFrame(frame),
      error: (e) => { this._emit('error', new Error('Opus 解码失败: ' + (e?.message ?? e))); this._makeDecoder(); },
    });
    this.decoder.configure({ codec: 'opus', sampleRate: 48000, numberOfChannels: 1 });
    this._ts = 0;
  }

  /** 整段 MP3/WAV：顺序排队播放，保持句间连续。 */
  _decodeClip(buf) {
    const seq = (this._clipChain ??= Promise.resolve());
    this._clipChain = seq.then(async () => {
      let audio;
      try { audio = await this.audioCtx.decodeAudioData(buf.slice(0)); }
      catch (e) { this._emit('error', new Error('音频解码失败: ' + (e?.message ?? e))); return; }
      this._schedule(audio);
    });
  }

  _schedule(buffer) {
    const ctx = this.audioCtx;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.analyser);
    const now = ctx.currentTime;
    if (this.playHead < now + 0.02) this.playHead = now + 0.08;
    src.start(this.playHead);
    this.playHead += buffer.duration;
    this.sources.add(src);
    src.onended = () => {
      this.sources.delete(src);
      if (this._stopPending && this.sources.size === 0) { this._stopPending = false; this._setSpeaking(false); }
    };
  }

  _playFrame(frame) {
    const n = frame.numberOfFrames;
    const pcm = new Float32Array(n);
    frame.copyTo(pcm, { planeIndex: 0, format: 'f32-planar' });
    const buffer = this.audioCtx.createBuffer(1, n, frame.sampleRate);
    buffer.copyToChannel(pcm, 0);
    frame.close();
    this._schedule(buffer);
  }

  _drainThenStop() {
    const finish = () => { if (this.sources.size === 0) this._setSpeaking(false); else this._stopPending = true; };
    if (this._clipChain) this._clipChain.then(finish); else finish();
  }

  _stopPlayback() {
    for (const s of this.sources) { try { s.stop(); } catch { /* already ended */ } }
    this.sources.clear();
    this.playHead = 0;
    this._stopPending = false;
    this._setSpeaking(false);
  }

  _setSpeaking(flag) {
    if (this.speaking === flag) return;
    this.speaking = flag;
    this._emit('speaking', { speaking: flag });
  }

  /** 当前播放音频的 RMS 包络 0..1（供口型）。 */
  level() {
    if (!this.analyser || !this.speaking) return 0;
    const buf = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) { const c = (v - 128) / 128; sum += c * c; }
    return Math.min(1, Math.sqrt(sum / buf.length) * 5);
  }

  // ── 上行麦克风（WebCodecs Opus）──────────────────────
  async startMic() {
    if (this.mic) return;
    if (!('AudioEncoder' in window) || !('MediaStreamTrackProcessor' in window)) {
      throw new Error('浏览器不支持 WebCodecs 麦克风编码（需 Chrome/Edge）');
    }
    let stream;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error('no mediaDevices'), { name: 'NotSupportedError' });
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (first) {
        // 约束不满足（部分设备/虚拟麦）时退回最宽松的请求
        if (first?.name === 'OverconstrainedError' || first?.name === 'NotFoundError') stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        else throw first;
      }
    } catch (err) {
      // DOMException → 可读中文（aikeya groq-stt 的错误映射）
      const messages = {
        NotAllowedError: '麦克风权限被拒绝：点地址栏左侧 🔒/ⓘ 允许麦克风，并检查 系统设置→隐私→麦克风 里 Chrome 已勾选',
        NotFoundError: '没有找到麦克风：系统设置→声音→输入 里确认有设备，Chrome 设置→隐私→麦克风 选中它',
        NotSupportedError: '当前页面不支持麦克风（需要 https 或 localhost/127.0.0.1）',
        NotReadableError: '麦克风被其他应用占用',
        OverconstrainedError: '麦克风不满足采样要求',
      };
      throw new Error(messages[err?.name] || `无法访问麦克风: ${err?.message ?? err}`);
    }
    const track = stream.getAudioTracks()[0];
    // 麦克风拔出/系统收回 → 自动停止并通知
    track.onended = () => { if (this.mic) { this.stopMic(); this._emit('error', new Error('麦克风已断开')); } };
    const sampleRate = track.getSettings().sampleRate || 48000;
    const cfg = { codec: 'opus', sampleRate, numberOfChannels: 1, bitrate: 24000, opus: { frameDuration: 60000 } };
    const sup = await AudioEncoder.isConfigSupported(cfg);
    if (!sup.supported) throw new Error('Opus 编码配置不受支持: ' + JSON.stringify(cfg));

    const encoder = new AudioEncoder({
      output: (chunk) => {
        if (this.ws?.readyState !== 1) return;
        const data = new Uint8Array(chunk.byteLength);
        chunk.copyTo(data);
        this.ws.send(data);
      },
      error: (e) => this._emit('error', e),
    });
    encoder.configure(cfg);

    const processor = new MediaStreamTrackProcessor({ track });
    const reader = processor.readable.getReader();
    this.mic = { stream, track, encoder, reader, sampleRate };
    this.ws?.send(JSON.stringify({ type: 'listen', state: 'start' }));
    this._emit('mic', { on: true });

    (async () => {
      while (this.mic) {
        const { value, done } = await reader.read();
        if (done || !value) break;
        // 单声道保证：多声道 AudioData 直接喂会被拒，这里只取首通道
        if (value.numberOfChannels === 1) encoder.encode(value);
        else {
          const n = value.numberOfFrames;
          const mono = new Float32Array(n);
          value.copyTo(mono, { planeIndex: 0, format: 'f32-planar' });
          encoder.encode(new AudioData({ format: 'f32-planar', sampleRate: value.sampleRate, numberOfFrames: n, numberOfChannels: 1, timestamp: value.timestamp, data: mono }));
        }
        value.close();
      }
    })();
  }

  stopMic() {
    const m = this.mic;
    if (!m) return;
    this.mic = null;
    try { m.reader.cancel(); } catch { /* noop */ }
    try { m.encoder.close(); } catch { /* noop */ }
    m.track.stop();
    this.ws?.send(JSON.stringify({ type: 'listen', state: 'stop' }));
    this._emit('mic', { on: false });
  }

  _emit(name, detail) { this.dispatchEvent(new CustomEvent(name, { detail })); }
}
