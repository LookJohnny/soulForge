import { createTavusEventState, reduceTavusEvent, requestTavusInterrupt } from './tavus_events.js';

// The hosted face owns ASR, speech and video. No GatewayClient/second microphone.
export class TavusVideoClient extends EventTarget {
  constructor({ daily, video, fetcher = (...args) => fetch(...args), mediaDevices = navigator.mediaDevices,
    makeStream = tracks => new MediaStream(tracks), clientId = crypto.randomUUID() }) {
    super();
    Object.assign(this, { daily, video, fetcher, mediaDevices, makeStream, clientId });
    this.call = null;
    this.session = null;
    this.input = null;
    this.connecting = false;
    this.ending = false;
    this.epoch = 0;
    this.events = createTavusEventState();
    this.state = { phase: 'idle', message: '还未接通', muted: false, videoReady: false,
      audioReady: false, needsPlay: false, events: this.events };
  }

  update(patch) {
    this.state = { ...this.state, ...patch };
    this.dispatchEvent(new CustomEvent('state', { detail: this.state }));
  }

  async api(path, body) {
    const response = await this.fetcher(path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || '视频服务暂时无法连接');
    return data;
  }

  async connect() {
    if (this.connecting || this.ending || this.call || this.session) return;
    this.connecting = true;
    const epoch = ++this.epoch;
    this.events = createTavusEventState();
    this.update({ phase: 'connecting', message: '等待麦克风许可…', muted: false,
      videoReady: false, audioReady: false, events: this.events, needsPlay: false });
    try {
      // Ask before creating the paid room. Camera is never requested.
      const input = await this.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false,
      });
      if (epoch !== this.epoch) { input.getTracks().forEach(t => t.stop()); return; }
      this.input = input;
      this.update({ message: '正在接通 Joi…' });
      const result = await this.api('/api/joi/session', { client_id: this.clientId });
      if (epoch !== this.epoch) {
        // A user can hang up while creation is in flight. Reclaim that exact room.
        this.session = result.session;
        await this.endRoom();
        return;
      }
      this.session = result.session;
      this.events = createTavusEventState(this.session.conversation_id);
      this.update({ events: this.events });
      const call = this.daily.createCallObject({ videoSource: false, startVideoOff: true,
        audioSource: input.getAudioTracks()[0], startAudioOff: false });
      this.call = call;
      const current = () => this.call === call && epoch === this.epoch;
      for (const name of ['participant-joined', 'participant-updated', 'track-started', 'track-stopped']) {
        call.on(name, () => { if (current()) this.syncTracks(); });
      }
      call.on('participant-left', event => {
        if (!current()) return;
        this.syncTracks();
        if (!event.participant?.local) void this.disconnect('Joi 已离开，通话已结束');
      });
      call.on('left-meeting', () => { if (current()) void this.disconnect('通话已结束'); });
      call.on('error', () => { if (current()) void this.disconnect('视频连接中断，请重新接通'); });
      call.on('camera-error', () => { if (current()) void this.disconnect('麦克风不可用，请检查浏览器权限'); });
      call.on('app-message', event => {
        if (!current()) return;
        this.events = reduceTavusEvent(this.events, event);
        this.update({ events: this.events });
      });
      await call.join({ url: this.session.conversation_url, token: this.session.meeting_token,
        userName: '你', startVideoOff: true });
      if (!current()) return;
      this.update({ phase: 'connected', message: '等待真人画面…' });
      this.syncTracks();
    } catch (error) {
      if (epoch === this.epoch) {
        const message = error.name === 'NotAllowedError' ? '需要麦克风许可才能交谈，请允许后重试'
          : error.name === 'NotFoundError' ? '没有找到麦克风，请连接后重试'
          : error.name === 'NotReadableError' ? '麦克风被占用，请关闭占用它的应用后重试'
          : error.message || '未能接通，请检查视频服务状态后重试';
        await this.disconnect(message);
      } else if (this.session) {
        this.update({ phase: 'cleanup_pending', message: '通话回收尚未确认，请点「结束会话」重试' });
      }
    } finally {
      this.connecting = false;
      this.update({});
    }
  }

  syncTracks() {
    if (!this.call) return;
    const remote = Object.values(this.call.participants()).find(p => !p.local);
    const tracks = ['video', 'audio'].map(kind => remote?.tracks?.[kind])
      .filter(t => t?.state === 'playable').map(t => t.persistentTrack || t.track).filter(Boolean);
    const previous = this.video.srcObject?.getTracks() || [];
    if (tracks.length !== previous.length || tracks.some(t => !previous.includes(t))) {
      // One media element keeps the provider's A/V timestamps together.
      this.video.srcObject = tracks.length ? this.makeStream(tracks) : null;
      if (tracks.length) void this.play();
    }
    this.update({ videoReady: tracks.some(t => t.kind === 'video'),
      audioReady: tracks.some(t => t.kind === 'audio') });
  }

  async play() {
    const epoch = this.epoch, stream = this.video.srcObject;
    const current = () => epoch === this.epoch && stream === this.video.srcObject;
    try { await this.video.play(); if (current()) this.update({ needsPlay: false }); }
    catch { if (current()) this.update({ needsPlay: true }); }
  }

  toggleMic() {
    if (!this.call || this.state.phase !== 'connected') return;
    const muted = !this.state.muted;
    this.call.setLocalAudio(!muted);
    this.input?.getAudioTracks().forEach(track => { track.enabled = !muted; });
    this.update({ muted });
  }

  interrupt() {
    if (!this.call || this.state.phase !== 'connected' || !this.session || !this.events.speaking.pal) return;
    try {
      this.call.sendAppMessage({ message_type: 'conversation', event_type: 'conversation.interrupt',
        conversation_id: this.session.conversation_id }, '*');
      this.events = requestTavusInterrupt(this.events);
      this.update({ events: this.events });
    } catch { this.update({ message: '打断未发送成功，请再试一次' }); }
  }

  async endRoom(keepalive = false) {
    if (!this.session) return;
    const session = this.session;
    const response = await this.fetcher('/api/joi/session/end', { method: 'POST',
      credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, keepalive,
      body: JSON.stringify({ conversation_id: session.conversation_id, client_id: this.clientId }) });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error('会话回收未确认');
    if (this.session === session) this.session = null;
  }

  async disconnect(message = '通话已结束', keepalive = false) {
    if (this.ending) return;
    this.ending = true;
    ++this.epoch;
    this.update({ phase: 'ending', message: '正在结束通话…' });
    const call = this.call;
    this.call = null;
    this.input?.getTracks().forEach(track => track.stop());
    this.input = null;
    this.video.pause();
    this.video.srcObject = null;
    // End the billable room even when the media SDK fails to leave.
    const results = await Promise.allSettled([
      (async () => { if (call) { try { await call.leave(); } finally { await call.destroy(); } } })(),
      this.endRoom(keepalive),
    ]);
    const pending = results[1].status === 'rejected';
    this.ending = false;
    this.update({ phase: pending ? 'cleanup_pending' : 'idle',
      message: pending ? '会话回收尚未确认，请点「结束会话」重试（最长 5 分钟自动结束）' : message,
      videoReady: false, audioReady: false, needsPlay: false });
  }

  unload() {
    // Also clear local call state, so restoring a BFCache page cannot present a
    // stopped mic and an ended room as connected. Cloud TTL is the backstop.
    return this.disconnect('通话已结束，可以重新接通', true);
  }
}
