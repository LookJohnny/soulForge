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

Dependencies (venv):  pip install websockets opuslib requests
System:               apt install libopus0  (usually already present)

Env:
  SF_GATEWAY_URL   ws://<mac-ip>:8080/ws
  SF_DEVICE_ID     default: pi-<hostname>
  SF_MIC_DEV       arecord -D device (default: default)
  SF_SPK_DEV       aplay -D device (default: default)
  SF_FACE_HOST     ESP8266 servo face host/IP; empty disables the face
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading

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
SETTLE_SEC = 0.45  # echo settle after playback stops

# SoulForge's 8 discrete emotions → ESP8266 face firmware endpoints
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

    Tries the CSI camera (Picamera2) first, then a USB camera (cv2). Both
    imports are lazy so camera-less devices run this client unchanged.
    """
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
    """Persistent aplay process; decoded 24 kHz PCM is piped to its stdin."""

    def __init__(self):
        self.proc = None
        self.decoder = opuslib.Decoder(DOWN_RATE, 1)

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
    "arecord", "-q", "-D", MIC_DEV, "-r", str(UP_RATE),
    "-f", "S16_LE", "-c", "1", "-t", "raw",
]


async def mic_loop(ws, muted: asyncio.Event):
    """Read raw PCM from arecord, encode 60 ms Opus frames, stream uplink.

    A deaf body is useless: if capture dies (device still held by a previous
    arecord after a reconnect, USB hiccup), close the WebSocket so the outer
    reconnect loop restarts the whole session with a fresh arecord.
    """
    encoder = opuslib.Encoder(UP_RATE, 1, opuslib.APPLICATION_VOIP)
    loop = asyncio.get_running_loop()
    frame_bytes = UP_SAMPLES * 2
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
            print(f"[mic] capture not ready (attempt {attempt + 1}/5), retrying", flush=True)
            await asyncio.sleep(1.0)
        if proc is None:
            print("[mic] giving up on capture device", flush=True)
            return

        while data and len(data) == frame_bytes:
            if not muted.is_set():  # half-duplex: swallow mic while speaker is active
                await ws.send(encoder.encode(data, UP_SAMPLES))
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
        await ws.send(json.dumps({"type": "listen", "state": "start"}))

        muted = asyncio.Event()
        player = Player()
        mic_task = asyncio.create_task(mic_loop(ws, muted))
        unmute_task = None

        def schedule_unmute():
            async def _later():
                await asyncio.sleep(SETTLE_SEC)
                muted.clear()

            return asyncio.create_task(_later())

        try:
            async for msg in ws:
                if isinstance(msg, bytes):
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
                    elif state == "sentence":
                        print(f"AI: {data.get('text', '')}", flush=True)
                    elif state == "stop":
                        unmute_task = schedule_unmute()
                elif mtype == "llm":
                    drive_face(data.get("emotion", ""))
                elif mtype == "emotion":
                    drive_face(data.get("emotion", ""))
                elif mtype == "capture":
                    # Gateway wants one camera frame for this turn
                    loop = asyncio.get_running_loop()
                    b64 = await loop.run_in_executor(None, capture_jpeg_b64)
                    await ws.send(json.dumps({"type": "vision_frame", "data": b64}))
        finally:
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
