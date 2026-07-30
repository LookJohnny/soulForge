# -*- coding: utf-8 -*-
"""PAD → 舵机脸 自主表情引擎。

把 SoulForge 的三维连续情绪 (P 愉悦 / A 唤醒 / D 掌控) 实时映射到
ESP8266 仿生脸的 35 个 HTTP 端点上，让脸成为内在情绪状态的持续外显，
而不是"每次回复贴一张罐头表情"。

设计要点（对应"自主意识感"的三个来源）：

1. **情绪惯性**：网关每轮对话推来一个 PAD 快照作为目标值，脸不瞬跳，
   而是每个 tick 向目标靠近一步（指数逼近），之后目标再缓慢向基线衰减
   ——聊完开心的话题，笑意是慢慢淡下去的。
2. **配方分层**：情绪强烈时用固件内置的复合表情（happy/sad/angry/
   surprised，编排最成熟）；情绪温和时用原子 AU 端点自己拼
   （微笑=两嘴角轻拉不鼓腮；害羞=单侧嘴角+目光下移），避免"要么没
   表情要么表情拉满"的电视机感。
3. **微行为节律**：眨眼、目光游移按泊松式随机发生，节奏随 A 缩放
   （兴奋时动作频密、困倦时迟缓目光下垂），D 低时目光回避。
   这些小动作与对话无关地持续发生——"它自己在活着"。

安全纪律（与 pi_voice_client 一致）：全部 fire-and-forget，脸掉线只
损失日志；连续失败进入退避，绝不阻塞语音主循环。说话期间大表情让位
给固件的 speaking 口型动画，只保留眨眼。

独立自测（不需要网关，脸在线即可看到效果）：
  SF_FACE_HOST=192.168.1.x python3 pad_face.py          # 演示一段情绪轨迹
  SF_FACE_HOST=192.168.1.x python3 pad_face.py 0.6 0.3 0.2   # 指定一个 PAD
"""

import os
import random
import threading
import time

try:
    import requests

    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

TIMEOUT = 1.5
BASELINE = (0.10, 0.00, 0.05)  # 静息心情：微微偏正的平静
APPROACH = 0.35  # 每 tick 向目标 PAD 靠近的比例（情绪惯性）
DECAY = 0.06  # 每 tick 目标向基线回落的比例（心情淡去）
FAIL_BACKOFF_S = 60  # 连续失败后休眠，等脸重新上线
FAIL_LIMIT = 5


def _clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


class Recipe:
    """一个表情配方：命中条件 + 端点序列（可带内嵌停顿）。"""

    def __init__(self, key, steps):
        self.key = key  # 去重用：同配方连续命中不重发
        self.steps = steps  # [(path, delay_after_s), ...]


def select_recipe(p, a, d):
    """PAD → 配方。顺序即优先级：先判强烈象限，再判温和组合。"""
    m = max(abs(p), abs(a), abs(d))

    # ── 强烈象限：交给固件的成熟编排 ──
    if p > 0.45:
        return Recipe("big_happy", [("/expr/happy", 0)])
    if a > 0.55 and abs(p) < 0.35:
        return Recipe("surprised", [("/expr/surprised", 0)])
    if p < -0.35 and d > 0.25:
        return Recipe("angry", [("/expr/angry", 0)])
    if p < -0.45:
        return Recipe("big_sad", [("/expr/sad", 0)])

    # ── 温和状态：原子 AU 自己拼 ──
    if a < -0.45:  # 困倦：眼帘沉、目光垂
        return Recipe("sleepy", [("/expr/neutral", 0.3), ("/moveDown", 0)])
    if p > 0.12 and d < -0.25:  # 害羞：单侧嘴角 + 目光回避
        return Recipe("shy", [("/lipRightPull", 0.4), ("/moveDown", 0)])
    if p > 0.30:  # 明快微笑：两嘴角 + 鼓颊
        return Recipe(
            "warm_smile",
            [("/lipLeftPull", 0.15), ("/lipRightPull", 0.3), ("/leftCheekPush", 0.15), ("/rightCheekPush", 0)],
        )
    if p > 0.15:  # 浅笑：只动嘴角
        return Recipe("soft_smile", [("/lipLeftPull", 0.15), ("/lipRightPull", 0)])
    if a > 0.25 and abs(p) <= 0.15:  # 好奇/思考：挑一侧眉 + 目光上抬
        return Recipe("curious", [("/browLeftUp", 0.5), ("/moveUp", 0)])
    if p < -0.15 and d >= 0:  # 不快但克制：眉压低
        return Recipe("stern", [("/lipCenter", 0.2), ("/browDown", 0)])
    if p < -0.15:  # 低落：嘴角回位 + 目光垂
        return Recipe("down", [("/lipCenter", 0.2), ("/moveDown", 0)])
    if m < 0.15:  # 静息
        return Recipe("rest", [("/lipCenter", 0.2), ("/browCenter", 0.2), ("/cheekCenter", 0)])
    return Recipe("neutralish", [("/expr/neutral", 0)])


class PadFaceEngine:
    """后台线程：维护情绪状态，按节律驱动脸。"""

    def __init__(self, host):
        self.host = host
        self._cur = list(BASELINE)
        self._target = list(BASELINE)
        self._lock = threading.Lock()
        self._express_lock = threading.Lock()  # 配方步骤不可交错
        self._speaking = False
        self._last_key = None
        self._fails = 0
        self._sleep_until = 0.0
        self._thread = None

    # ── 外部事件 ─────────────────────────────
    def on_pad(self, pad):
        """网关推来新的 PAD 快照（每轮回复一次）。"""
        try:
            p, a, d = float(pad.get("p", 0)), float(pad.get("a", 0)), float(pad.get("d", 0))
        except (TypeError, ValueError, AttributeError):
            return
        with self._lock:
            self._target = [_clamp(p), _clamp(a), _clamp(d)]

        # 对话反应要即时：不等下个 tick，先迈一大步并立刻表现。
        # 配方步骤间有 sleep，必须放线程里——调用方可能是 asyncio 事件循环。
        def _react():
            self._step(approach=0.7)
            self._express(force=True)

        threading.Thread(target=_react, daemon=True).start()

    def on_speaking(self, speaking):
        """TTS 播放开始/结束：说话期间口型让给固件 speaking 动画。"""
        self._speaking = bool(speaking)
        if speaking:
            self._fire("/expr/speaking")
        else:
            # 说完话，脸回到当前情绪该有的样子（同样不能阻塞调用方）
            self._last_key = None
            threading.Thread(target=self._express, kwargs={"force": True}, daemon=True).start()

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ── 内部 ────────────────────────────────
    def _step(self, approach=APPROACH):
        with self._lock:
            for i in range(3):
                self._cur[i] += (self._target[i] - self._cur[i]) * approach
                self._target[i] += (BASELINE[i] - self._target[i]) * DECAY

    def _tick_interval(self):
        # A 高 → 动作频密（0.9s），A 低 → 迟缓（3.2s）
        a = self._cur[1]
        return _clamp(2.1 - 1.2 * a, 0.9, 3.2)

    def _express(self, force=False):
        if self._speaking:
            return
        if not self._express_lock.acquire(blocking=False):
            return  # 另一个配方正在演出，跳过这拍
        try:
            p, a, d = self._cur
            recipe = select_recipe(p, a, d)
            if not force and recipe.key == self._last_key:
                return
            self._last_key = recipe.key
            print(f"[pad_face] P={p:+.2f} A={a:+.2f} D={d:+.2f} -> {recipe.key}", flush=True)
            for path, delay in recipe.steps:
                self._fire(path)
                if delay:
                    time.sleep(delay)
        finally:
            self._express_lock.release()

    def _micro(self):
        """微行为：眨眼与目光游移，与对话无关地持续发生。"""
        p, a, d = self._cur
        r = random.random()
        if self._speaking:
            if r < 0.25:
                self._fire("/blink")
            return
        if r < 0.30:
            self._fire("/blink")
        elif r < 0.42 and d < -0.2:  # 弱势/害羞：目光向下回避
            self._fire("/moveDown")
        elif r < 0.55 and a > 0.15:  # 兴奋/好奇：左右张望
            self._fire(random.choice(["/moveLeft", "/moveRight"]))
            threading.Timer(random.uniform(0.6, 1.4), self._fire, ["/moveCenter"]).start()
        elif r < 0.62:
            self._fire("/moveCenter")

    def _fire(self, path):
        if not HAS_REQUESTS or not self.host:
            return
        if time.monotonic() < self._sleep_until:
            return

        def _get():
            try:
                requests.get(f"http://{self.host}{path}", timeout=TIMEOUT)
                self._fails = 0
            except Exception:
                self._fails += 1
                if self._fails >= FAIL_LIMIT:
                    self._sleep_until = time.monotonic() + FAIL_BACKOFF_S
                    self._fails = 0
                    print(f"[pad_face] face offline, backing off {FAIL_BACKOFF_S}s", flush=True)

        threading.Thread(target=_get, daemon=True).start()

    def _run(self):
        while True:
            try:
                self._step()
                self._express()
                self._micro()
            except Exception as e:  # 任何异常只损失一个 tick
                print(f"[pad_face] tick error: {e}", flush=True)
            time.sleep(self._tick_interval())


if __name__ == "__main__":
    import sys

    host = os.environ.get("SF_FACE_HOST", "")
    eng = PadFaceEngine(host)
    eng.start()
    if len(sys.argv) == 4:
        eng.on_pad({"p": float(sys.argv[1]), "a": float(sys.argv[2]), "d": float(sys.argv[3])})
        time.sleep(15)
    else:
        # 演示轨迹：开心 → 好奇 → 害羞 → 低落 → 回归平静
        for pad in [
            {"p": 0.7, "a": 0.4, "d": 0.3},
            {"p": 0.1, "a": 0.4, "d": 0.1},
            {"p": 0.3, "a": 0.1, "d": -0.5},
            {"p": -0.4, "a": -0.2, "d": -0.2},
        ]:
            print(f"\n=== 注入 PAD {pad} ===", flush=True)
            eng.on_pad(pad)
            time.sleep(12)
        print("\n=== 自然衰减回基线 ===", flush=True)
        time.sleep(20)
