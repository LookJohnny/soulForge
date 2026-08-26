/* MemoryGraph —— 记忆图（aikeya memory-graph 的无依赖移植）。
   节点 = 记忆，边 = 语义相似度 ≥ 阈值；大小 = 重要度，透明度 = 新旧，
   颜色 = 记忆层。自绘 canvas 力导向，无第三方库。 */

const LAYER_COLORS = { PROFILE: '#01B2FF', EPISODIC: '#34d399', SEMANTIC: '#e8b34b', RELATIONAL: '#f472b6' };

export class MemoryGraph {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.nodes = []; this.edges = [];
    this.hover = null;
    this.running = false;
    canvas.addEventListener('pointermove', (e) => {
      const r = canvas.getBoundingClientRect();
      const x = (e.clientX - r.left) * (canvas.width / r.width), y = (e.clientY - r.top) * (canvas.height / r.height);
      this.hover = this.nodes.find((n) => Math.hypot(n.x - x, n.y - y) < n.r + 4) ?? null;
    });
    canvas.addEventListener('pointerleave', () => { this.hover = null; });
  }

  setData({ nodes = [], edges = [] }) {
    const W = this.canvas.width, H = this.canvas.height;
    const now = Date.now();
    const idx = new Map();
    this.nodes = nodes.map((n, i) => {
      const age = n.created_at ? (now - Date.parse(n.created_at)) / 864e5 : 30;
      const node = {
        ...n,
        x: W / 2 + Math.cos(i * 2.4) * (40 + i * 3), y: H / 2 + Math.sin(i * 2.4) * (40 + i * 3), vx: 0, vy: 0,
        r: 4 + (Math.min(10, n.importance ?? 3) / 10) * 10,
        alpha: age <= 7 ? 1 : age <= 30 ? 0.8 : age <= 90 ? 0.6 : 0.4,
        color: LAYER_COLORS[n.layer] ?? '#8a8f9a',
      };
      idx.set(n.id, node); return node;
    });
    this.edges = edges.map((e) => ({ a: idx.get(e.a), b: idx.get(e.b), w: e.w })).filter((e) => e.a && e.b);
    this.start();
  }

  start() {
    if (this.running) return;
    this.running = true; this.ticks = 0;
    const loop = () => { if (!this.running) return; this.step(); this.draw(); if (++this.ticks < 400 || this.hover) requestAnimationFrame(loop); else this.running = false; };
    requestAnimationFrame(loop);
  }

  step() {
    const W = this.canvas.width, H = this.canvas.height, N = this.nodes;
    for (let i = 0; i < N.length; i++) {
      const a = N[i];
      a.vx += (W / 2 - a.x) * 0.002; a.vy += (H / 2 - a.y) * 0.002;         // 向心
      for (let j = i + 1; j < N.length; j++) {                               // 斥力
        const b = N[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy + 0.01; const f = 900 / d2;
        dx *= f; dy *= f; a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy;
      }
    }
    for (const e of this.edges) {                                            // 弹簧
      const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, d = Math.hypot(dx, dy) || 1, target = 60 - e.w * 30;
      const f = (d - target) * 0.01 * e.w; e.a.vx += dx / d * f; e.a.vy += dy / d * f; e.b.vx -= dx / d * f; e.b.vy -= dy / d * f;
    }
    for (const n of N) { n.vx *= 0.85; n.vy *= 0.85; n.x = Math.max(n.r, Math.min(W - n.r, n.x + n.vx)); n.y = Math.max(n.r, Math.min(H - n.r, n.y + n.vy)); }
  }

  draw() {
    const c = this.ctx, W = this.canvas.width, H = this.canvas.height;
    c.clearRect(0, 0, W, H);
    for (const e of this.edges) { c.strokeStyle = `rgba(138,143,154,${0.15 + e.w * 0.5})`; c.lineWidth = 0.5 + e.w * 2; c.beginPath(); c.moveTo(e.a.x, e.a.y); c.lineTo(e.b.x, e.b.y); c.stroke(); }
    for (const n of this.nodes) { c.globalAlpha = n.alpha; c.fillStyle = n.color; c.beginPath(); c.arc(n.x, n.y, n.r, 0, Math.PI * 2); c.fill(); }
    c.globalAlpha = 1;
    const h = this.hover;
    if (h) {
      c.font = '12px -apple-system, "PingFang SC", sans-serif';
      const text = `${h.layer} · ${h.content}`.slice(0, 60);
      const w = c.measureText(text).width + 12, x = Math.min(W - w - 4, h.x + 10), y = Math.max(16, h.y - 12);
      c.fillStyle = 'rgba(22,25,35,.95)'; c.fillRect(x, y - 12, w, 18);
      c.fillStyle = '#e8e6e1'; c.fillText(text, x + 6, y + 1);
    }
  }
}
