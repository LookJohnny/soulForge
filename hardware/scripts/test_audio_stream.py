#!/usr/bin/env python3
"""
SoulForge 音频流端到端测试
模拟 ESP32 发送 16kHz PCM 音频到 Gateway，接收 TTS 回复。

支持两种模式:
  1. --file test.pcm  : 发送预录音频文件
  2. --tts-only       : 只测试 TTS 回路（发送文本，接收音频）
  3. 默认             : 生成合成正弦波作为测试音频

Usage:
    python hardware/scripts/test_audio_stream.py
    python hardware/scripts/test_audio_stream.py --file hardware/test_data/hello.pcm
    python hardware/scripts/test_audio_stream.py --tts-only
"""

import argparse
import asyncio
import json
import math
import os
import struct
import sys
import time
import wave

import websockets

DEFAULT_GATEWAY = "ws://127.0.0.1:8080/ws"
DEVICE_ID = "audio-test-device"
SAMPLE_RATE = 16000  # 16kHz
FRAME_SIZE = 320  # 20ms per frame (16000 * 0.02 * 2 bytes = 640... actually 320 samples * 2 bytes = 640 bytes)
FRAME_BYTES = 640  # 320 samples * 2 bytes/sample


class Colors:
    GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"; YELLOW = "\033[93m"; NC = "\033[0m"

def ok(msg): print(f"  {Colors.GREEN}[OK]{Colors.NC} {msg}")
def fail(msg): print(f"  {Colors.RED}[FAIL]{Colors.NC} {msg}")
def info(msg): print(f"  {Colors.CYAN}[INFO]{Colors.NC} {msg}")


def generate_sine_pcm(duration_s=2.0, freq=440):
    """Generate a sine wave as 16kHz 16-bit PCM for testing."""
    samples = int(SAMPLE_RATE * duration_s)
    pcm = bytearray()
    for i in range(samples):
        t = i / SAMPLE_RATE
        val = int(16000 * math.sin(2 * math.pi * freq * t))
        pcm.extend(struct.pack("<h", max(-32768, min(32767, val))))
    return bytes(pcm)


def load_pcm_file(path):
    """Load raw PCM file or WAV file."""
    if path.endswith(".wav"):
        with wave.open(path, "rb") as wf:
            assert wf.getframerate() == SAMPLE_RATE, f"Expected {SAMPLE_RATE}Hz, got {wf.getframerate()}"
            assert wf.getsampwidth() == 2, "Expected 16-bit"
            return wf.readframes(wf.getnframes())
    else:
        with open(path, "rb") as f:
            return f.read()


def save_wav(pcm_data, path, sample_rate=24000):
    """Save PCM data as WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    info(f"Saved: {path} ({len(pcm_data)} bytes, {sample_rate}Hz)")


async def test_audio_stream(gateway_url, pcm_data):
    """Send PCM audio via WebSocket, receive TTS response."""

    print(f"\n{'='*55}")
    print(f"  SoulForge 音频流测试")
    print(f"  Gateway: {gateway_url}")
    print(f"  Audio:   {len(pcm_data)} bytes ({len(pcm_data)/SAMPLE_RATE/2:.1f}s @ 16kHz)")
    print(f"{'='*55}\n")

    timings = {}

    try:
        async with websockets.connect(gateway_url, open_timeout=5, max_size=10_000_000) as ws:
            # 1. Handshake (xiaozhi protocol)
            hello = {"type": "hello", "device_id": DEVICE_ID}
            await ws.send(json.dumps(hello))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            ok(f"握手成功: {resp.get('type')}")

            # 2. Start listening
            await ws.send(json.dumps({"type": "listen", "state": "start"}))
            info("发送 listen:start")
            timings["send_start"] = time.time()

            # 3. Send audio frames (simulate real-time streaming)
            total_frames = 0
            for offset in range(0, len(pcm_data), FRAME_BYTES):
                frame = pcm_data[offset:offset + FRAME_BYTES]
                if len(frame) < FRAME_BYTES:
                    frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
                await ws.send(frame)
                total_frames += 1
                # Simulate real-time: 20ms per frame
                await asyncio.sleep(0.005)  # Faster than real-time for testing

            ok(f"发送 {total_frames} 帧音频 ({total_frames * 20}ms)")

            # 4. Stop listening
            await ws.send(json.dumps({"type": "listen", "state": "stop"}))
            timings["send_stop"] = time.time()
            info(f"发送 listen:stop (上传耗时: {int((timings['send_stop']-timings['send_start'])*1000)}ms)")

            # 5. Receive response
            text_parts = []
            audio_chunks = []
            got_response = False

            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=20)
                except asyncio.TimeoutError:
                    if not got_response:
                        fail("等待回复超时 (20s)")
                    break

                if isinstance(msg, bytes):
                    # Audio data
                    if "first_audio" not in timings:
                        timings["first_audio"] = time.time()
                    audio_chunks.append(msg)
                else:
                    data = json.loads(msg)
                    state = data.get("state", "")

                    if state == "start":
                        timings["thinking_start"] = time.time()
                        info("角色开始思考...")
                    elif state == "sentence":
                        text = data.get("text", "")
                        if text:
                            if "first_text" not in timings:
                                timings["first_text"] = time.time()
                            text_parts.append(text)
                            got_response = True
                    elif state == "stop":
                        timings["done"] = time.time()
                        break

            # 6. Results
            full_text = "".join(text_parts)
            total_audio = b"".join(audio_chunks)

            print(f"\n{Colors.CYAN}── 结果 ──{Colors.NC}")

            if full_text:
                ok(f"AI 回复: \"{full_text[:80]}\"")
            else:
                fail("未收到文本回复")

            if total_audio:
                ok(f"收到音频: {len(total_audio)} bytes")
                # Save to file
                out_dir = os.path.join(os.path.dirname(__file__), "..", "test_data")
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "response.wav")
                # Try to detect if it's WAV (has RIFF header) or raw PCM
                if total_audio[:4] == b"RIFF":
                    with open(out_path, "wb") as f:
                        f.write(total_audio)
                    info(f"保存: {out_path} (原始WAV)")
                else:
                    save_wav(total_audio, out_path, 24000)
            else:
                info("未收到音频 (可能 TTS 未配置)")

            # 7. Timing report
            print(f"\n{Colors.CYAN}── 延迟报告 ──{Colors.NC}")
            base = timings.get("send_stop", 0)

            if "thinking_start" in timings:
                info(f"上传→开始思考: {int((timings['thinking_start']-base)*1000)}ms")
            if "first_text" in timings:
                ok(f"上传→首字文本:  {int((timings['first_text']-base)*1000)}ms")
            if "first_audio" in timings:
                info(f"上传→首帧音频: {int((timings['first_audio']-base)*1000)}ms")
            if "done" in timings:
                total = int((timings["done"] - base) * 1000)
                ok(f"总端到端延迟:   {total}ms")
                if total < 3000:
                    ok("延迟达标 (< 3s)")
                elif total < 5000:
                    print(f"  {Colors.YELLOW}[WARN]{Colors.NC} 延迟偏高 (3-5s)，检查网络和 LLM 响应速度")
                else:
                    fail(f"延迟过高 ({total}ms > 5s)")

            return got_response

    except Exception as e:
        fail(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_tts_only(gateway_url):
    """Send text, receive TTS audio — no ASR needed."""
    print(f"\n{'='*55}")
    print(f"  SoulForge TTS 回路测试 (文本→语音)")
    print(f"{'='*55}\n")

    try:
        async with websockets.connect(gateway_url, open_timeout=5, max_size=10_000_000) as ws:
            # GenericWS handshake
            hello = {"action": "hello", "device_id": f"{DEVICE_ID}-tts"}
            await ws.send(json.dumps(hello))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            ok(f"握手成功: protocol={resp.get('protocol')}")

            # Send text
            start = time.time()
            await ws.send(json.dumps({"action": "chat", "text": "你好呀，给我讲个笑话"}))
            info("发送文本: 你好呀，给我讲个笑话")

            # Collect
            text_parts = []
            audio_chunks = []
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=20)
                except asyncio.TimeoutError:
                    break

                if isinstance(msg, bytes):
                    audio_chunks.append(msg)
                else:
                    data = json.loads(msg)
                    if data.get("state") == "sentence":
                        text_parts.append(data.get("text", ""))
                    elif data.get("state") == "stop":
                        break

            latency = int((time.time() - start) * 1000)
            text = "".join(text_parts)
            audio = b"".join(audio_chunks)

            if text:
                ok(f"回复: \"{text[:60]}\" ({latency}ms)")
            else:
                fail("无文本回复")

            if audio:
                out_path = os.path.join(os.path.dirname(__file__), "..", "test_data", "tts_response.wav")
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                if audio[:4] == b"RIFF":
                    with open(out_path, "wb") as f:
                        f.write(audio)
                else:
                    save_wav(audio, out_path)
                ok(f"音频已保存: {out_path}")

            return bool(text)
    except Exception as e:
        fail(f"TTS 测试失败: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SoulForge 音频流测试")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument("--file", help="PCM/WAV 文件路径")
    parser.add_argument("--tts-only", action="store_true", help="只测试 TTS 回路")
    args = parser.parse_args()

    if args.tts_only:
        success = asyncio.run(test_tts_only(args.gateway))
    else:
        if args.file:
            pcm = load_pcm_file(args.file)
            info(f"Loaded: {args.file} ({len(pcm)} bytes)")
        else:
            info("生成 2s 正弦波测试音频 (ASR 不会识别出有意义的内容)")
            info("提示: 用 --file 指定真实录音，或用 --tts-only 跳过 ASR")
            pcm = generate_sine_pcm(2.0)

        success = asyncio.run(test_audio_stream(args.gateway, pcm))

    sys.exit(0 if success else 1)
