// Native WebRTC only: one microphone, one synchronized remote A/V element.
const isId = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const isEpoch = value => Number.isSafeInteger(value) && value >= 0;

export class SelfhostVideoClient extends EventTarget {
  constructor({ video, fetcher = (...args) => fetch(...args), mediaDevices = navigator.mediaDevices,
    createPeer = () => new RTCPeerConnection({ iceServers: [] }),
    makeStream = tracks => new MediaStream(tracks), clientId = crypto.randomUUID(),
    requestTimeout = 45000, iceTimeout = 10000, disconnectTimeout = 5000, connectTimeout = 15000 }) {
    super();
    if (!isId(clientId)) throw new Error('Invalid client identifier');
    Object.assign(this, { video, fetcher, mediaDevices, createPeer, makeStream, clientId,
      requestTimeout, iceTimeout, disconnectTimeout, connectTimeout });
    this.pc = null; this.channel = null; this.input = null; this.sessionId = null; this.creationPending = false;
    this.remote = null; this.tracks = new Map(); this.epoch = 0; this.remoteEpoch = -1;
    this.connecting = false; this.ending = false; this.pendingInterrupt = null;
    this.networkTimer = null; this.turnOperation = 0;
    this.state = { phase: 'idle', message: '正在检查 GPU 服务…', ready: false, muted: false,
      videoReady: false, audioReady: false, needsPlay: false, caption: null,
      turnPhase: 'idle', turnId: null, interruptPending: false, metrics: {}, notice: '' };
  }

  update(patch) {
    this.state = { ...this.state, ...patch };
    this.dispatchEvent(new CustomEvent('state', { detail: this.state }));
  }

  async api(path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.requestTimeout);
    try {
      const response = await this.fetcher('/api/selfhost/' + path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
        signal: controller.signal,
        ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
      });
      const data = await response.json();
      if (!response.ok || data?.error || data?.ok === false) throw new Error('Media service unavailable');
      return data;
    } finally { clearTimeout(timer); }
  }

  async checkHealth() {
    try {
      const health = await this.api('health');
      const ready = health.ready === true;
      this.update({ ready, ...(this.state.phase === 'idle' ? {
        message: ready ? 'GPU 服务已加载，连接与口型同步待实测。点击接通开始交谈。' : 'GPU 未配置或尚未就绪，请先启动自建视频服务。',
      } : {}) });
      return ready;
    } catch {
      this.update({ ready: false, ...(this.state.phase === 'idle' ? { message: 'GPU 未配置或视频服务未连接。' } : {}) });
      return false;
    }
  }

  async gatherIce(pc, epoch) {
    if (pc.iceGatheringState === 'complete') return;
    await new Promise((resolve, reject) => {
      const finish = error => { clearTimeout(timer); pc.removeEventListener('icegatheringstatechange', changed);
        pc.removeEventListener('connectionstatechange', changed); error ? reject(error) : resolve(); };
      const changed = () => {
        if (this.epoch !== epoch || pc.connectionState === 'closed') finish(new Error('Cancelled'));
        else if (pc.iceGatheringState === 'complete') finish();
      };
      const timer = setTimeout(() => finish(new Error('ICE timed out')), this.iceTimeout);
      pc.addEventListener('icegatheringstatechange', changed);
      pc.addEventListener('connectionstatechange', changed);
      changed();
    });
  }

  async connect() {
    if (this.connecting || this.ending || this.pc || this.sessionId || this.creationPending || !this.state.ready) return;
    this.connecting = true;
    const epoch = ++this.epoch;
    this.remoteEpoch = -1; this.pendingInterrupt = null;
    this.update({ phase: 'connecting', message: '等待麦克风许可…', muted: false,
      caption: null, turnId: null, turnPhase: 'idle', metrics: {}, interruptPending: false, notice: '' });
    try {
      const input = await this.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false,
      });
      if (epoch !== this.epoch) { input.getTracks().forEach(t => t.stop()); return; }
      this.input = input;
      const pc = this.createPeer(); this.pc = pc;
      const current = () => this.pc === pc && this.epoch === epoch;
      for (const track of input.getAudioTracks()) pc.addTrack(track, input);
      pc.addTransceiver('video', { direction: 'recvonly' });
      const channel = pc.createDataChannel('events', { ordered: true }); this.channel = channel;
      channel.addEventListener('message', event => { if (current()) this.receive(event.data); });
      channel.addEventListener('close', () => { if (current()) void this.disconnect('会话控制连接已断开，请重新接通'); });
      pc.addEventListener('track', event => {
        if (!current() || !['audio', 'video'].includes(event.track.kind)) return;
        this.tracks.set(event.track.kind, event.track);
        event.track.addEventListener('ended', () => {
          if (current() && this.tracks.get(event.track.kind) === event.track) {
            this.tracks.delete(event.track.kind); this.syncTracks();
          }
        });
        this.syncTracks();
      });
      pc.addEventListener('connectionstatechange', () => {
        if (!current()) return;
        clearTimeout(this.networkTimer);
        if (pc.connectionState === 'connected') {
          this.update({ phase: 'connected', message: '已接通，等待真人视频…' });
        } else if (pc.connectionState === 'disconnected') {
          this.update({ message: '媒体连接中断，正在等待恢复…' });
          this.networkTimer = setTimeout(() => { if (current()) void this.disconnect('连接未恢复，通话已结束'); }, this.disconnectTimeout);
        } else if (['failed', 'closed'].includes(pc.connectionState)) {
          void this.disconnect('媒体连接已断开，请重新接通');
        }
      });
      this.update({ message: '正在建立本地视频连接…' });
      await pc.setLocalDescription(await pc.createOffer());
      await this.gatherIce(pc, epoch);
      if (!current()) return;
      this.creationPending = true;
      const result = await this.api('sessions', { client_id: this.clientId,
        sdp: pc.localDescription.sdp, type: 'offer' });
      if (!isId(result.session_id)) throw new Error('Invalid media session');
      this.sessionId = result.session_id;
      this.creationPending = false;
      if (!current()) { await this.closeRoom(result.session_id); return; }
      if (result.type !== 'answer' || typeof result.sdp !== 'string') throw new Error('Invalid media answer');
      await pc.setRemoteDescription({ type: 'answer', sdp: result.sdp });
      if (current() && pc.connectionState === 'connected') this.update({ phase: 'connected', message: '已接通，等待真人视频…' });
      else if (current()) this.networkTimer = setTimeout(() => {
        if (current() && pc.connectionState !== 'connected') void this.disconnect('媒体连接超时，请重新接通');
      }, this.connectTimeout);
    } catch (error) {
      if (epoch === this.epoch) {
        await this.disconnect(error.name === 'NotAllowedError' ? '需要麦克风许可，允许后再试。'
          : error.name === 'NotFoundError' ? '没有找到麦克风，请连接后重试。' : '自建视频未能接通，请检查 GPU 服务。');
      } else if (this.sessionId || this.creationPending) {
        this.update({ phase: 'cleanup_pending', message: '会话回收未确认，请重试结束会话。' });
      }
    } finally { this.connecting = false; this.update({}); }
  }

  syncTracks() {
    this.remote = this.tracks.size ? this.makeStream([...this.tracks.values()]) : null;
    this.update({ videoReady: this.tracks.has('video'), audioReady: this.tracks.has('audio') });
    // Never play audio against an empty stage, even if the remote audio arrives first.
    if (!this.pendingInterrupt && this.tracks.has('video')) {
      this.video.srcObject = this.remote;
      void this.play();
    } else { this.video.pause(); this.video.srcObject = null; }
  }

  async play() {
    if (!this.pc || this.pendingInterrupt || !this.remote || !this.tracks.has('video')) return;
    const epoch = this.epoch, stream = this.video.srcObject;
    if (!stream) return;
    try { await this.video.play();
      if (epoch === this.epoch && this.video.srcObject === stream) this.update({ needsPlay: false });
    } catch {
      if (epoch === this.epoch && this.video.srcObject === stream) this.update({ needsPlay: true });
    }
  }

  receive(raw) {
    let event;
    try { if (typeof raw !== 'string' || raw.length > 16384) return; event = JSON.parse(raw); } catch { return; }
    if (!event || typeof event !== 'object' || Array.isArray(event)
        || !['caption', 'state', 'cancelled', 'error', 'metrics'].includes(event.type)) return;
    if (event.session_id !== this.sessionId || !isEpoch(event.epoch) || event.epoch < this.remoteEpoch) return;
    this.remoteEpoch = event.epoch;
    if (event.type === 'caption' && ['user', 'assistant', 'pal'].includes(event.role) && typeof event.text === 'string') {
      if (this.pendingInterrupt && event.role !== 'user') return;
      this.update({ caption: { role: event.role, text: event.text.slice(0, 4000) } });
    } else if (event.type === 'state' && ['idle', 'listening', 'transcribing', 'thinking', 'generating', 'speaking'].includes(event.phase)) {
      this.update({ turnPhase: event.phase,
        ...(['transcribing', 'thinking', 'generating', 'speaking'].includes(event.phase) ? { notice: '' } : {}),
        ...(typeof event.turn_id === 'string' ? { turnId: event.turn_id.slice(0, 128) } : {}) });
    } else if (event.type === 'cancelled') {
      const pending = this.pendingInterrupt;
      if (!pending || event.epoch <= pending.beforeEpoch) return;
      pending.cancelledEpochs.add(event.epoch);
      if (pending.cancelledEpochs.size > 8) pending.cancelledEpochs.delete(pending.cancelledEpochs.values().next().value);
      this.confirmInterrupt(pending);
    } else if (event.type === 'error') {
      this.update({ notice: '本轮音视频处理失败，请检查自建服务后重试。' });
    } else if (event.type === 'metrics') {
      const metrics = {};
      for (const key of ['first_audio_ready_ms', 'first_video_ready_ms', 'sender_drained_ms', 'decision_ms', 'video_fps', 'queue_ms']) {
        if (typeof event[key] === 'number' && Number.isFinite(event[key]) && event[key] >= 0) metrics[key] = event[key];
      }
      if (typeof event.browser_playback_verified === 'boolean') metrics.browser_playback_verified = event.browser_playback_verified;
      this.update({ metrics });
    }
  }

  async sendText(text) {
    if (!this.sessionId || this.state.phase !== 'connected' || this.pendingInterrupt || !text.trim() || text.length > 4000) return false;
    const epoch = this.epoch, sid = this.sessionId, operation = ++this.turnOperation;
    try {
      const result = await this.api(`sessions/${sid}/turn`, { client_id: this.clientId, text });
      if (epoch !== this.epoch || operation !== this.turnOperation) return false;
      if (isEpoch(result.epoch) && result.epoch < this.remoteEpoch) return true;
      this.update({ ...(typeof result.turn_id === 'string' ? { turnId: result.turn_id } : {}), notice: '', message: '已发送，正在等待回应…' });
      return true;
    } catch { if (epoch === this.epoch && operation === this.turnOperation) this.update({ notice: '这条消息未能发送，请重试。' }); return false; }
  }

  toggleMic() {
    if (!this.input || this.state.phase !== 'connected') return;
    const muted = !this.state.muted;
    this.input.getAudioTracks().forEach(track => { track.enabled = !muted; });
    this.update({ muted });
  }

  async interrupt() {
    if (!this.sessionId || this.state.phase !== 'connected' || this.pendingInterrupt) return;
    const epoch = this.epoch;
    ++this.turnOperation;
    const pending = { beforeEpoch: this.remoteEpoch, expectedEpoch: null, cancelledEpochs: new Set() };
    this.pendingInterrupt = pending;
    this.video.pause(); this.video.srcObject = null;
    this.update({ interruptPending: true, caption: null, needsPlay: false, message: '本地已暂停声音与画面，等待服务端取消确认…' });
    try {
      const result = await this.api(`sessions/${this.sessionId}/interrupt`, { client_id: this.clientId });
      if (epoch !== this.epoch || this.pendingInterrupt !== pending) return;
      if (!isEpoch(result.epoch) || result.epoch <= pending.beforeEpoch) throw new Error('Missing cancellation epoch');
      pending.expectedEpoch = result.epoch;
      this.confirmInterrupt(pending);
    }
    catch { if (epoch === this.epoch && this.pendingInterrupt) {
      this.update({ message: '取消尚未确认；播放保持暂停，可挂断后重新接通。' });
    } }
  }

  confirmInterrupt(pending) {
    // A preceding text turn can emit its own cancelled event. Resume only after
    // HTTP identifies this interrupt's exact epoch AND its event has arrived.
    if (this.pendingInterrupt !== pending || pending.expectedEpoch === null
        || !pending.cancelledEpochs.has(pending.expectedEpoch)) return;
    this.pendingInterrupt = null;
    this.update({ interruptPending: false, turnPhase: 'listening', caption: null,
      message: '服务端已确认取消，可以继续交谈。' });
    this.syncTracks();
  }

  async closeRoom(sid = this.sessionId) {
    if (!sid && !this.creationPending) return;
    await this.api(sid ? `sessions/${sid}/close` : 'sessions/close-owned', { client_id: this.clientId });
    if (this.sessionId === sid) this.sessionId = null;
    this.creationPending = false;
  }

  clearLocal() {
    ++this.epoch; ++this.turnOperation; clearTimeout(this.networkTimer);
    const pc = this.pc; this.pc = null; this.channel = null;
    this.input?.getTracks().forEach(track => track.stop()); this.input = null;
    try { pc?.close(); } catch { /* Remote cleanup remains independent. */ }
    this.video.pause(); this.video.srcObject = null;
    this.remote = null; this.tracks.clear(); this.pendingInterrupt = null;
  }

  async disconnect(message = '通话已结束') {
    if (this.ending) return;
    this.ending = true; this.clearLocal();
    this.update({ phase: 'ending', message: '正在结束会话…', caption: null,
      videoReady: false, audioReady: false, needsPlay: false, interruptPending: false });
    try { await this.closeRoom(); this.update({ phase: 'idle', message }); }
    catch { this.update({ phase: 'cleanup_pending', message: '会话回收未确认，请重试结束会话。' }); }
    finally { this.ending = false; this.update({}); }
  }

  unload() {
    const sid = this.sessionId;
    const owns = sid || this.creationPending;
    this.clearLocal();
    this.update({ phase: owns ? 'cleanup_pending' : 'idle', caption: null,
      videoReady: false, audioReady: false, needsPlay: false, interruptPending: false });
    if (owns) void this.fetcher('/api/selfhost/' + (sid ? `sessions/${sid}/close` : 'sessions/close-owned'), {
      method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_id: this.clientId }),
    }).catch(() => {});
  }
}
