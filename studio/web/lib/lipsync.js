/* LipSync —— 播放音频的 FFT 频段能量 → 五视素权重。

   移植自 aikeya src/lib/services/lipsync/analyzer.ts（MIT），修了两处：
   - 平滑改为帧率无关：rate = 1 - exp(-k·dt)
   - 由调用方保证在 vrm.update() 之前写入表情

   这是能量法不是音素法：嘴型随音频节奏开合，不是真正的口型对位。
   若要更高质量，应由 ai-core 侧产出视素时间轴。 */

export const VISEMES = ['aa', 'ee', 'ih', 'oh', 'ou'];

export class LipSync {
  constructor({ attack = 18, release = 9, threshold = 0.05 } = {}) {
    this.attack = attack;      // 1/s
    this.release = release;    // 1/s
    this.threshold = threshold;
    this.analyser = null;
    this.data = null;
    this.weights = { aa: 0, ee: 0, ih: 0, oh: 0, ou: 0 };
    this.active = true;        // 播放状态门控（无声时直接归零，避免底噪抖动）
  }

  setAnalyser(analyser) {
    this.analyser = analyser;
    this.data = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;
    this.wave = analyser ? new Uint8Array(analyser.fftSize) : null;
  }

  /** 每帧调用，返回平滑后的视素权重。 */
  update(dt) {
    if (!this.analyser || !this.data || !this.active) return this._toward(null, dt);
    // 音量门用时域 RMS（频域均值对窄带信号会漏判），频段分布用频域
    this.analyser.getByteTimeDomainData(this.wave);
    let sq = 0;
    for (let i = 0; i < this.wave.length; i++) { const c = (this.wave[i] - 128) / 128; sq += c * c; }
    const volume = Math.min(1, Math.sqrt(sq / this.wave.length) * 2.5);
    if (volume < this.threshold) return this._toward(null, dt);
    this.analyser.getByteFrequencyData(this.data);
    const d = this.data;

    const len = d.length;
    const lowEnd = Math.floor(len * 0.1);
    const lowMidEnd = Math.floor(len * 0.25);
    const midEnd = Math.floor(len * 0.5);
    const highEnd = Math.floor(len * 0.75);
    const avg = (a, b) => { if (b <= a) return 0; let s = 0; for (let i = a; i < b; i++) s += d[i]; return s / (b - a) / 255; };
    const low = avg(0, lowEnd), lowMid = avg(lowEnd, lowMidEnd), mid = avg(lowMidEnd, midEnd), high = avg(midEnd, highEnd);
    const scale = Math.min(volume * 2, 1);
    return this._toward({
      aa: Math.min(low * 1.5 * scale, 0.8),
      oh: Math.min(lowMid * 1.3 * scale, 0.7),
      ee: Math.min(mid * 1.2 * scale, 0.6),
      ih: Math.min(high * 1.0 * scale, 0.5),
      ou: Math.min((low + lowMid) * 0.5 * scale, 0.6),
    }, dt);
  }

  /** 口型开合总量 0..1（供头部点动等副作用）。 */
  get level() { const w = this.weights; return Math.min(1, Math.max(w.aa, w.oh, w.ee, w.ih, w.ou) * 1.25); }

  reset() { for (const k of VISEMES) this.weights[k] = 0; }

  _toward(target, dt) {
    const k = target ? this.attack : this.release;
    const r = 1 - Math.exp(-k * dt);
    for (const v of VISEMES) {
      const t = target ? target[v] : 0;
      this.weights[v] += (t - this.weights[v]) * r;
    }
    return this.weights;
  }
}
