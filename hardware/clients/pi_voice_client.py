#!/usr/bin/env python3
"""Raspberry Pi thin voice client for the SoulForge gateway.

Replaces an on-device assistant stack (ASR/LLM/TTS all local) with a thin
body: microphone audio streams up to the gateway over the xiaozhi WebSocket
protocol, synthesized speech streams back down, and per-turn emotion events
drive a servo face over HTTP. The brain (ASR, personality, memory, PAD
emotion) lives entirely in SoulForge.

Protocol (xiaozhi):
  up:   {"type":"hello","device_id":...,"audio_params":{"format":"opus"}}
        {"type":"listen","state":"start"}
        binary Opus packets, 16 kHz mono, 60 ms / 960 samples per frame
  down: {"type":"tts","state":start|sentence|sentence_start|stop,...}
        {"type":"llm","emotion":...}   (emotion → servo face)
        binary Opus packets, 24 kHz mono, 60 ms

Audio I/O uses arecord/aplay subprocesses (ALSA) — no PortAudio needed,
same approach as proven on this hardware. Server-side Silero VAD detects
end-of-utterance; the client never needs to segment speech itself.

Echo control is half-duplex: uplink is muted from tts:start to tts:stop
plus a short settle window, so the mic never hears the speaker.

Wake word: local sherpa-onnx KWS (「你好维智」, see WakeGate). Idle audio
never leaves the device; a wake hit beeps and opens a conversation window
that each reply extends. Without the model the client streams always-on.

Dependencies (venv):  pip install websockets opuslib requests numpy sherpa-onnx
System:               apt install libopus0  (usually already present)

Env:
  SF_GATEWAY_URL   ws://<mac-ip>:8080/ws
  SF_DEVICE_ID     default: pi-<hostname>
  SF_MIC_DEV       arecord -D device (default: default)
  SF_SPK_DEV       aplay -D device (default: default)
  SF_FACE_HOST     ESP8266 servo face host/IP; empty disables the face
  SF_KWS_DIR       sherpa-onnx KWS model dir (SF_KWS_DISABLE=1 to skip)
  SF_KEYWORDS      keywords file (pinyin tokens, sherpa-onnx-cli text2token)
  SF_WAKE_WINDOW   conversation window seconds after wake (default 45)
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import opuslib
import websockets

try:
    import requests

    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

GATEWAY_URL = os.environ.get("SF_GATEWAY_URL", "ws://192.168.1.172:8080/ws")
DEVICE_ID = os.environ.get("SF_DEVICE_ID", f"pi-{socket.gethostname()}")
MIC_DEV = os.environ.get("SF_MIC_DEV", "default")
SPK_DEV = os.environ.get("SF_SPK_DEV", "default")
FACE_HOST = os.environ.get("SF_FACE_HOST", "")

UP_RATE = 16000  # uplink sample rate (gateway decodes 16 kHz)
DOWN_RATE = 24000  # downlink sample rate (gateway encodes 24 kHz)
FRAME_MS = 60
UP_SAMPLES = UP_RATE * FRAME_MS // 1000  # 960
SETTLE_SEC = 0.7  # echo settle after real playback drain (喇叭与麦克风耦合极强)

# SoulForge's 8 discrete emotions → ESP8266 face firmware endpoints
# (fallback path — used only when the gateway message carries no PAD)
FACE_MAP = {
    "happy": "/expr/happy",
    "sad": "/expr/sad",
    "shy": "/expr/happy",
    "angry": "/expr/angry",
    "playful": "/blink",
    "curious": "/expr/thinking",
    "worried": "/expr/sad",
    "calm": "/expr/neutral",
}

# Continuous PAD → autonomous expression engine (emotional inertia, mild-state
# AU compositions, idle micro-behaviors). Falls back to FACE_MAP when absent.
FACE_ENGINE = None
if FACE_HOST:
    try:
        from pad_face import PadFaceEngine

        FACE_ENGINE = PadFaceEngine(FACE_HOST)
        FACE_ENGINE.start()
    except Exception as _e:  # engine is optional; label path still works
        print(f"[face] pad engine unavailable, label fallback only: {_e}", flush=True)


class FaceTracker:
    """CSI 摄像头人脸追踪：持续检测人脸在画面中的位置，经网关驱动眼球。

    独占持有 Picamera2（相机不能被两处同时打开），因此也承担"最新一帧"
    的供应者角色——视觉问答的拍照直接取这里的缓存帧。
    检测失败/缺依赖只打日志，绝不影响语音主循环。
    """

    def __init__(self):
        self._latest_jpeg = ""
        self._sender = None  # callable(dict)->None，连接建立后注入
        self._lock = threading.Lock()
        self.ok = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def set_sender(self, fn):
        self._sender = fn

    def latest_jpeg_b64(self) -> str:
        with self._lock:
            return self._latest_jpeg

    def _run(self):
        try:
            import base64

            import cv2
            from picamera2 import Picamera2

            cam = Picamera2()
            cam.configure(
                cam.create_video_configuration(
                    main={"size": (640, 480), "format": "RGB888"}
                )
            )
            cam.start()
            cascade = "haarcascade_frontalface_default.xml"
            candidates = []
            if hasattr(cv2, "data"):  # pip 版 opencv
                candidates.append(cv2.data.haarcascades + cascade)
            candidates += [  # apt 版 python3-opencv (树莓派系统包)
                f"/usr/share/opencv4/haarcascades/{cascade}",
                f"/usr/local/share/opencv4/haarcascades/{cascade}",
            ]
            det = None
            for c in candidates:
                if os.path.exists(c):
                    det = cv2.CascadeClassifier(c)
                    break
            if det is None or det.empty():
                raise RuntimeError(f"no usable haarcascade in {candidates}")
            self.ok = True
            print("[track] face tracker running (640x480 @ ~2.5fps)", flush=True)
        except Exception as e:
            print(f"[track] disabled: {e}", flush=True)
            return
        # 摄像头物理安装角度（0/90/180/270，顺时针）；歪着装会让 haar 检不出脸
        rot = int(os.environ.get("SF_CAM_ROT", "0"))
        rot_code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(rot)
        last_diag = 0.0
        hits = 0
        misses = 0
        while True:
            try:
                arr = cam.capture_array()
                if rot_code is not None:
                    arr = cv2.rotate(arr, rot_code)
                okj, buf = cv2.imencode(
                    ".jpg",
                    cv2.cvtColor(arr, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 85],
                )
                if okj:
                    with self._lock:
                        self._latest_jpeg = base64.b64encode(buf).decode()
                # 全分辨率检测（640x480）：1米外的脸也有 60-80px，检出稳定
                gray = cv2.equalizeHist(cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY))
                fh, fw = gray.shape[:2]
                faces = det.detectMultiScale(gray, 1.1, 3, minSize=(48, 48))
                sender = self._sender
                if len(faces):
                    hits += 1
                    x, y, w, h = max(faces, key=lambda f: int(f[2]) * int(f[3]))
                    dx = ((x + w / 2) / fw - 0.5) * 2
                    dy = ((y + h / 2) / fh - 0.5) * 2
                    if sender:
                        sender(
                            {
                                "type": "face_pos",
                                "dx": round(float(dx), 3),
                                "dy": round(float(dy), 3),
                            }
                        )
                else:
                    misses += 1
                now = time.monotonic()
                if now - last_diag > 10:
                    last_diag = now
                    detail = f"face {w}x{h}px dx={dx:+.2f} dy={dy:+.2f}" if len(faces) else "no face"
                    print(f"[track] 10s: {hits} hit / {misses} miss, last: {detail}", flush=True)
                    hits = misses = 0
                    try:  # 诊断快照：看看摄像头此刻到底看到什么
                        cv2.imwrite("/tmp/track_latest.jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
                    except Exception:
                        pass
            except Exception as e:
                print(f"[track] frame error: {e}", flush=True)
                time.sleep(3)
            time.sleep(0.3)


TRACKER = None
if os.environ.get("SF_FACE_TRACK", "1") == "1":
    TRACKER = FaceTracker()
    TRACKER.start()


def _capture_picamera2() -> str:
    """CSI camera via Picamera2/libcamera (the camera on this Pi)."""
    import base64
    import io

    from picamera2 import Picamera2

    picam2 = Picamera2()
    try:
        picam2.configure(picam2.create_still_configuration(main={"size": (1280, 960)}))
        picam2.start()
        import time as _t

        _t.sleep(0.8)  # exposure settle
        buf = io.BytesIO()
        picam2.capture_file(buf, format="jpeg")
        data = buf.getvalue()
        print(f"[vision] picamera2 captured {len(data)} bytes", flush=True)
        return base64.b64encode(data).decode()
    finally:
        picam2.stop()
        picam2.close()


def _capture_cv2() -> str:
    """USB camera fallback via V4L2."""
    import base64

    import cv2

    cap = cv2.VideoCapture(int(os.environ.get("SF_CAM_INDEX", "0")), cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    frame = None
    for _ in range(5):  # first frames are often dark while exposure settles
        ok, frame = cap.read()
        if not ok:
            frame = None
            break
    cap.release()
    if frame is None:
        return ""
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return ""
    print(f"[vision] cv2 captured {len(jpg)} bytes", flush=True)
    return base64.b64encode(jpg.tobytes()).decode()


def capture_jpeg_b64() -> str:
    """Grab one JPEG frame; "" on any failure (client stays camera-optional).

    When the face tracker owns the camera, serve its cached latest frame —
    Picamera2 cannot be opened twice. Otherwise fall back to one-shot capture
    (CSI via Picamera2, then USB via cv2), all imports lazy.
    """
    if TRACKER and TRACKER.ok:
        data = TRACKER.latest_jpeg_b64()
        if data:
            return data
    for grab in (_capture_picamera2, _capture_cv2):
        try:
            data = grab()
            if data:
                return data
        except Exception as e:
            print(f"[vision] {grab.__name__} failed: {e}", flush=True)
    return ""


def drive_face(emotion: str):
    """Fire-and-forget HTTP GET to the servo face; failures never block audio."""
    if not FACE_HOST or not HAS_REQUESTS:
        return
    path = FACE_MAP.get((emotion or "").strip().lower())
    if not path:
        return

    def _get():
        url = f"http://{FACE_HOST}{path}"
        try:
            requests.get(url, timeout=1.5)
            print(f"[face] {emotion} -> {path}", flush=True)
        except Exception as e:
            print(f"[face] unreachable {url}: {e}", flush=True)

    threading.Thread(target=_get, daemon=True).start()


class Player:
    """Persistent aplay process; decoded 24 kHz PCM is piped to its stdin.

    ``playing_until`` tracks when the aplay buffer will actually drain — the
    gateway's tts:stop arrives well before the speaker finishes, and unmuting
    on it lets the mic hear our own tail and self-converse with the echo.
    """

    def __init__(self):
        self.proc = None
        self.decoder = opuslib.Decoder(DOWN_RATE, 1)
        self.playing_until = 0.0

    def _ensure(self):
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                [
                    "aplay",
                    "-q",
                    "-D",
                    SPK_DEV,
                    "-r",
                    str(DOWN_RATE),
                    "-f",
                    "S16_LE",
                    "-c",
                    "1",
                    "-t",
                    "raw",
                ],
                stdin=subprocess.PIPE,
            )

    def play_opus(self, packet: bytes):
        try:
            pcm = self.decoder.decode(packet, DOWN_RATE * FRAME_MS // 1000)
            self._ensure()
            self.proc.stdin.write(pcm)
            self.proc.stdin.flush()
            now = time.monotonic()
            self.playing_until = max(now, self.playing_until) + FRAME_MS / 1000
        except Exception as e:
            print(f"[play] {e}", flush=True)
            self.proc = None

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
            except Exception:
                pass


ARECORD_CMD = [
    "arecord",
    "-q",
    "-D",
    MIC_DEV,
    "-r",
    str(UP_RATE),
    "-f",
    "S16_LE",
    "-c",
    "1",
    "-t",
    "raw",
]

KWS_DIR = os.environ.get(
    "SF_KWS_DIR",
    os.path.expanduser(
        "~/soulforge/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
    ),
)
KEYWORDS_FILE = os.environ.get(
    "SF_KEYWORDS", os.path.expanduser("~/soulforge/keywords.txt")
)
WAKE_WINDOW_SEC = float(os.environ.get("SF_WAKE_WINDOW", "45"))
KEEPALIVE_SEC = 25.0  # idle: one silence frame keeps the gateway session alive


class WakeGate:
    """Local wake-word gate (sherpa-onnx KWS, 唤醒词「你好维智」).

    While idle, mic audio stays on-device: frames are only fed to the local
    spotter. A hit opens a conversation window; the receiver extends it on
    each turn so back-and-forth chat never needs re-waking. If the model is
    missing or SF_KWS_DISABLE=1, the gate stays open (always streaming).
    """

    def __init__(self):
        self.spotter = None
        self.stream = None
        self.active_until = 0.0
        if os.environ.get("SF_KWS_DISABLE") == "1":
            print("[wake] disabled by env, always streaming", flush=True)
            return
        try:
            import sherpa_onnx

            self.spotter = sherpa_onnx.KeywordSpotter(
                tokens=f"{KWS_DIR}/tokens.txt",
                encoder=f"{KWS_DIR}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
                decoder=f"{KWS_DIR}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
                joiner=f"{KWS_DIR}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
                keywords_file=KEYWORDS_FILE,
                num_threads=2,
                keywords_score=3.0,  # 实测 piper/真人语音在此组合下稳定命中
                keywords_threshold=0.15,  # 负样本(日常聊天)不误触
            )
            self.stream = self.spotter.create_stream()
            try:
                with open(KEYWORDS_FILE, encoding="utf-8") as f:
                    words = [
                        line.rsplit("@", 1)[-1].strip() for line in f if "@" in line
                    ]
            except Exception:
                words = []
            print(
                f"[wake] keyword spotter loaded ({'、'.join(words) or KEYWORDS_FILE})",
                flush=True,
            )
        except Exception as e:
            print(f"[wake] spotter unavailable, always streaming: {e}", flush=True)

    @property
    def enabled(self) -> bool:
        return self.spotter is not None

    def is_active(self) -> bool:
        return not self.enabled or time.monotonic() < self.active_until

    def extend(self):
        self.active_until = time.monotonic() + WAKE_WINDOW_SEC

    def feed(self, frame: bytes) -> bool:
        """Feed one 16 kHz S16 frame; True when the wake word just fired."""
        if not self.enabled:
            return False
        import numpy as np

        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        self.stream.accept_waveform(UP_RATE, samples)
        hit = False
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            if self.spotter.get_result(self.stream) != "":
                self.spotter.reset_stream(self.stream)
                hit = True
        return hit


def play_beep():
    """Short wake-ack beep; generated once, played fire-and-forget."""
    path = "/tmp/sf_wake_beep.wav"
    if not os.path.exists(path):
        try:
            import wave

            import numpy as np

            sr = 24000
            t = np.arange(int(sr * 0.15))
            tone = (np.sin(2 * np.pi * 880 * t / sr) * 12000).astype(np.int16)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(tone.tobytes())
        except Exception:
            return
    subprocess.Popen(["aplay", "-q", "-D", SPK_DEV, path])


async def mic_loop(ws, muted: asyncio.Event, gate: WakeGate):
    """Read raw PCM from arecord, encode 60 ms Opus frames, stream uplink.

    Wake gating: while idle, frames only feed the local keyword spotter and a
    periodic silence frame keeps the gateway session alive; audio streams up
    only inside the wake window.

    A deaf body is useless: if capture dies (device still held by a previous
    arecord after a reconnect, USB hiccup), close the WebSocket so the outer
    reconnect loop restarts the whole session with a fresh arecord.
    """
    encoder = opuslib.Encoder(UP_RATE, 1, opuslib.APPLICATION_VOIP)
    loop = asyncio.get_running_loop()
    frame_bytes = UP_SAMPLES * 2
    silence = b"\x00" * frame_bytes
    last_keepalive = time.monotonic()
    proc = None
    try:
        # The capture device can stay busy for a moment while a previous
        # arecord releases it — retry before declaring the mic dead.
        data = b""
        for attempt in range(5):
            proc = subprocess.Popen(ARECORD_CMD, stdout=subprocess.PIPE)
            data = await loop.run_in_executor(None, proc.stdout.read, frame_bytes)
            if data and len(data) == frame_bytes:
                break
            proc.terminate()
            proc.wait()
            proc = None
            print(
                f"[mic] capture not ready (attempt {attempt + 1}/5), retrying",
                flush=True,
            )
            await asyncio.sleep(1.0)
        if proc is None:
            print("[mic] giving up on capture device", flush=True)
            return

        while data and len(data) == frame_bytes:
            if muted.is_set():
                pass  # half-duplex: swallow mic while speaker is active
            elif gate.is_active():
                await ws.send(encoder.encode(data, UP_SAMPLES))
            else:
                if await loop.run_in_executor(None, gate.feed, data):
                    print("[wake] 唤醒！开启对话窗口", flush=True)
                    gate.extend()
                    play_beep()
                elif time.monotonic() - last_keepalive > KEEPALIVE_SEC:
                    await ws.send(encoder.encode(silence, UP_SAMPLES))
                    last_keepalive = time.monotonic()
            data = await loop.run_in_executor(None, proc.stdout.read, frame_bytes)
        print("[mic] capture stream ended", flush=True)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        try:
            await ws.close()
        except Exception:
            pass


async def run_once():
    print(f"[client] connecting {GATEWAY_URL} as {DEVICE_ID}", flush=True)
    async with websockets.connect(GATEWAY_URL, max_size=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "device_id": DEVICE_ID,
                    "audio_params": {"format": "opus"},
                }
            )
        )
        hello = json.loads(await ws.recv())
        print(f"[client] session {hello.get('session_id', '?')}", flush=True)

        # 人脸位置上报走当前连接；断线后 sender 失效自动静默
        if TRACKER:
            _loop = asyncio.get_running_loop()

            def _send_face_pos(payload: dict):
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps(payload)), _loop
                    )
                except Exception:
                    pass

            TRACKER.set_sender(_send_face_pos)
        await ws.send(json.dumps({"type": "listen", "state": "start"}))

        muted = asyncio.Event()
        player = Player()
        gate = WakeGate()
        mic_task = asyncio.create_task(mic_loop(ws, muted, gate))
        unmute_task = None

        def schedule_unmute():
            async def _later():
                # wait for the aplay buffer to actually drain, then settle
                while True:
                    remain = player.playing_until - time.monotonic()
                    if remain <= 0:
                        break
                    await asyncio.sleep(min(remain, 0.5))
                await asyncio.sleep(SETTLE_SEC)
                muted.clear()

            return asyncio.create_task(_later())

        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    muted.set()  # defensive: never listen while audio is arriving
                    player.play_opus(msg)
                    continue
                data = json.loads(msg)
                mtype = data.get("type")
                if mtype == "tts":
                    state = data.get("state")
                    if state == "start":
                        if unmute_task:
                            unmute_task.cancel()
                        muted.set()
                        if FACE_ENGINE:
                            FACE_ENGINE.on_speaking(True)
                    elif state == "sentence":
                        print(f"AI: {data.get('text', '')}", flush=True)
                    elif state == "stop":
                        unmute_task = schedule_unmute()
                        gate.extend()  # 每轮回复后续满对话窗口，连续聊天无需重新唤醒
                        if FACE_ENGINE:
                            FACE_ENGINE.on_speaking(False)
                elif mtype in ("llm", "emotion"):
                    # Prefer the continuous PAD snapshot; label is the fallback
                    if FACE_ENGINE and data.get("pad"):
                        FACE_ENGINE.on_pad(data["pad"])
                    else:
                        drive_face(data.get("emotion", ""))
                elif mtype == "capture":
                    # Gateway wants one camera frame for this turn
                    loop = asyncio.get_running_loop()
                    b64 = await loop.run_in_executor(None, capture_jpeg_b64)
                    await ws.send(json.dumps({"type": "vision_frame", "data": b64}))
        finally:
            if TRACKER:
                TRACKER.set_sender(None)
            mic_task.cancel()
            try:
                await mic_task  # wait for arecord to release the device
            except (asyncio.CancelledError, Exception):
                pass
            player.close()


async def main():
    # Reconnect forever with backoff — the body outlives brain restarts.
    backoff = 2
    while True:
        try:
            await run_once()
            backoff = 2
        except (OSError, websockets.WebSocketException) as e:
            print(f"[client] disconnected: {e}; retry in {backoff}s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        else:
            # Server closed us cleanly — pause so the capture device is
            # released before the next session grabs it.
            await asyncio.sleep(2)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
