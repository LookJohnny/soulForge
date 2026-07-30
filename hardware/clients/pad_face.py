"""PAD → 舵机脸 自主表情引擎。

孪生关系：本文件与 packages/gateway/src/gateway/face_engine.py 内容
同步（由 gateway 版生成，改动请改 gateway 版后重新生成）。

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
import queue
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
EYE_MIN_INTERVAL = 0.35  # 眼球追踪指令最小间隔（ESP8266 HTTP 上限约 3req/s）
EYE_DEADZONE = 0.18  # 画面中心死区，人在中间时不追
TRACK_FRESH_S = 8.0  # 最近这么久内有追踪信号，随机目光游移让位
# 摄像头成像与眼球方向的镜像关系因安装而异；方向反了把此环境变量设为 1
EYE_MIRROR = os.environ.get("FACE_TRACK_MIRROR", "0") == "1"

# ── 温柔化总控 ─────────────────────────────
# FACE_INTENSITY 0~1：表情烈度总旋钮，越小越安静。影响三处：
# 全脸大表情的触发门槛、配方步骤间隔、主循环节拍
try:
    INTENSITY = max(0.0, min(1.0, float(os.environ.get("FACE_INTENSITY", "0.4"))))
except ValueError:
    INTENSITY = 0.4
CALM = 1.0 - INTENSITY  # 安静程度（阅读用）
# 说话口型风格：
#   mixed(默认)=上唇微动+小幅下颌（张嘴后立刻跟闭嘴，用时序把下颌行程截短）
#   lips=只上唇 | jaw=下颌全幅开合（大，慎用） | off=无口型
MOUTH_STYLE = os.environ.get("SF_MOUTH_STYLE", "mixed").strip().lower()


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
    # 门槛随 CALM 抬升：低烈度设置下，全脸大表情是罕见的高光时刻
    strong = 0.35 * CALM
    if p > 0.45 + strong:
        return Recipe("big_happy", [("/expr/happy", 0)])
    if a > 0.55 + strong and abs(p) < 0.35:
        return Recipe("surprised", [("/expr/surprised", 0)])
    if p < -0.35 - strong and d > 0.25:
        return Recipe("angry", [("/expr/angry", 0)])
    if p < -0.45 - strong:
        return Recipe("big_sad", [("/expr/sad", 0)])

    # ── 温和状态：原子 AU 自己拼 ──
    if a < -0.45:  # 困倦：眉回落、目光垂（不借用固件复合姿态）
        return Recipe("sleepy", [("/browCenter", 0.3), ("/moveDown", 0)])
    if p > 0.12 and d < -0.25:  # 害羞：单侧嘴角 + 目光回避
        return Recipe("shy", [("/lipRightPull", 0.4), ("/moveDown", 0)])
    if p > 0.30:  # 明快微笑：两嘴角 + 鼓颊
        return Recipe(
            "warm_smile",
            [
                ("/lipLeftPull", 0.15),
                ("/lipRightPull", 0.3),
                ("/leftCheekPush", 0.15),
                ("/rightCheekPush", 0),
            ],
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
    return Recipe("neutralish", [("/lipCenter", 0.3), ("/browCenter", 0)])


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
        self._last_eye = 0.0  # 上次眼球追踪指令时间
        self._last_center = 0.0
        self._track_seen = 0.0  # 上次收到人脸位置的时间
        # 所有 HTTP 指令经单工人队列串行发送：并发线程发送会乱序到达
        # （闭嘴可能先于之前的张嘴到达 → 嘴卡在张开），串行是唯一保序方式
        self._q: queue.Queue = queue.Queue(maxsize=8)

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
        """TTS 播放开始/结束。

        口型不在这里驱动——嘴部循环由 feed_audio 按真实排入的音频时长
        精确驱动（思考期、句间空隙自动停嘴）。这里只管状态切换和
        说完后的表情恢复。
        """
        self._speaking = bool(speaking)
        if speaking:
            return
        self._mouth_until = 0.0  # 立刻停嘴（打断/播放结束）
        # 说完话，脸回到当前情绪该有的样子（同样不能阻塞调用方）
        self._last_key = None
        threading.Thread(target=self._express, kwargs={"force": True}, daemon=True).start()
    def feed_audio(self, secs):
        """网关刚向设备排入 secs 秒真实音频——嘴部窗口精确延长这么多。

        口型只在音频真正播放的时间段动：思考期、句间空隙自动停嘴。
        """
        try:
            secs = float(secs)
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        base = max(getattr(self, "_mouth_until", 0.0), now)
        self._mouth_until = base + secs
        self._start_mouth_loop()

    def _start_mouth_loop(self):
        t = getattr(self, "_mouth_thread", None)
        if t is not None and t.is_alive():
            return

        if MOUTH_STYLE == "off":
            return
        DEVICE_LAG = 0.35  # 网络+设备缓冲：帧发出到喇叭出声的大致延迟
        if MOUTH_STYLE == "jaw":
            # 下颌全幅开合（幅度大）
            cycle = [("/mouthOpen", 0.2), ("/mouthClose", 0.68)]
            settle = ["/mouthClose"]
        elif MOUTH_STYLE == "lips":
            # 只上唇轻抬→回位，完全不碰下颌
            cycle = [("/lipUpRaise", 0.25), ("/lipCenter", 0.9)]
            settle = ["/lipCenter"]
        else:
            # mixed（默认）：双唇微张——上唇抬+下唇降同时发，视觉上嘴轻轻
            # 张开一条缝，再回位。完全不驱动下颌（时序截断法实测截不住：
            # 舵机 0.1s 走完行程 > HTTP 最小间隔，任何脉冲都接近全开）
            cycle = [
                ("/lipUpRaise", 0.0),
                ("/lipDownLower", 0.35),
                ("/lipCenter", 1.0),
            ]
            settle = ["/mouthClose", "/lipCenter"]

        def _flap():
            while True:
                now = time.monotonic()
                if now > getattr(self, "_mouth_until", 0.0) + DEVICE_LAG:
                    break
                for path, pause in cycle:
                    self._fire(path)
                    if pause:
                        time.sleep(pause)
            # 收尾：先清掉队列里可能积压的开口指令，再双发回位保险
            self._purge_queue()
            for path in settle:
                self._fire(path)
            time.sleep(0.5)
            for path in settle:
                self._fire(path)

        self._mouth_thread = threading.Thread(target=_flap, daemon=True)
        self._mouth_thread.start()

    def on_face_pos(self, dx, dy):
        """设备摄像头报告的人脸偏移（画面中心为原点，-1..1，右/下为正）。

        眼球端点是档位式触发（无连续角度），所以做限速的方向轻推：
        偏得多就朝那个方向拨一档，回到中心死区后拨回正视。
        """
        try:
            dx, dy = float(dx), float(dy)
        except (TypeError, ValueError):
            return
        if EYE_MIRROR:
            dx = -dx
        now = time.monotonic()
        self._track_seen = now
        # 说话期间嘴部循环占用 HTTP 带宽，眼球降频
        min_gap = 1.2 if self._speaking else EYE_MIN_INTERVAL
        if now - self._last_eye < min_gap:
            return

        path = None
        if abs(dx) >= abs(dy):
            if dx > EYE_DEADZONE:
                path = "/moveRight"
            elif dx < -EYE_DEADZONE:
                path = "/moveLeft"
        if path is None:
            if dy > EYE_DEADZONE:
                path = "/moveDown"
            elif dy < -EYE_DEADZONE:
                path = "/moveUp"
        if path is None and now - self._last_center > 4.0:
            path = "/moveCenter"  # 人回到画面中央：正视对方
            self._last_center = now
        if path:
            self._last_eye = now
            self._fire(path)
            # 两轴都偏得多时，第二轴稍后跟上（对角线追踪更跟手）
            second = None
            if path in ("/moveLeft", "/moveRight"):
                if dy > EYE_DEADZONE:
                    second = "/moveDown"
                elif dy < -EYE_DEADZONE:
                    second = "/moveUp"
            elif path in ("/moveUp", "/moveDown"):
                if dx > EYE_DEADZONE:
                    second = "/moveRight"
                elif dx < -EYE_DEADZONE:
                    second = "/moveLeft"
            if second:
                threading.Timer(0.15, self._fire, [second]).start()

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        threading.Thread(target=self._http_worker, daemon=True).start()

    # ── 内部 ────────────────────────────────
    def _step(self, approach=APPROACH):
        with self._lock:
            for i in range(3):
                self._cur[i] += (self._target[i] - self._cur[i]) * approach
                self._target[i] += (BASELINE[i] - self._target[i]) * DECAY

    def _tick_interval(self):
        # A 高 → 动作频密，A 低 → 迟缓；CALM 整体放缓节拍
        a = self._cur[1]
        return _clamp(2.1 - 1.2 * a + CALM, 0.9 + CALM, 3.2 + CALM)

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
                    # CALM 拉长步骤间隔：多舵机动作依次缓慢呈现，不"整脸炸开"
                    time.sleep(delay * (1.0 + CALM))
        finally:
            self._express_lock.release()

    def _micro(self):
        """微行为：眨眼与目光游移，与对话无关地持续发生。"""
        _p, a, d = self._cur
        r = random.random()
        if self._speaking:
            return  # 说话时除口型外完全安静：不眨眼不眼跳
        # 正在追踪真人时，目光归追踪管；只保留眨眼
        if time.monotonic() - self._track_seen < TRACK_FRESH_S:
            if r < 0.30:
                self._fire("/blink")
            return
        if r < 0.30:
            self._fire("/blink")
        elif r < 0.36 and d < -0.2:  # 弱势/害羞：目光向下回避（概率已减半）
            self._fire("/moveDown")
        elif r < 0.44 and a > 0.15:  # 兴奋/好奇：左右张望（概率已减半）
            self._fire(random.choice(["/moveLeft", "/moveRight"]))
            threading.Timer(random.uniform(0.8, 1.6), self._fire, ["/moveCenter"]).start()
        elif r < 0.5:
            self._fire("/moveCenter")

    def _fire(self, path):
        """入队（保序）。队满丢最旧——最新指令永远优先。"""
        if not HAS_REQUESTS or not self.host:
            return
        if time.monotonic() < self._sleep_until:
            return
        try:
            self._q.put_nowait(path)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(path)
            except Exception:
                pass

    def _purge_queue(self):
        """清空积压指令（停嘴前用：确保闭嘴后没有迟到的张嘴）。"""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def _http_worker(self):
        """唯一真正发 HTTP 的线程：严格按序、逐条、限速。"""
        while True:
            path = self._q.get()
            try:
                # Connection: close 至关重要——ESP8266 单线程服务器的 socket
                # 表只有几个位置，keep-alive 连接几分钟就把它占满挂死
                requests.get(
                    f"http://{self.host}{path}",
                    timeout=TIMEOUT,
                    headers={"Connection": "close"},
                )
                self._fails = 0
            except Exception:
                self._fails += 1
                if self._fails >= FAIL_LIMIT:
                    self._sleep_until = time.monotonic() + FAIL_BACKOFF_S
                    self._fails = 0
                    self._purge_queue()
                    print(f"[pad_face] face offline, backing off {FAIL_BACKOFF_S}s", flush=True)
            time.sleep(0.05)  # 给 ESP8266 的单线程服务器喘息

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
